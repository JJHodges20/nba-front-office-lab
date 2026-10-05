"""The scenario simulator for the workbench: a roster for the season ahead with the user's
assumptions laid over it, seasons drawn for it before and after, and what changed.

Everything a scenario is judged by comes from parts the lab has tested - the value
model's projections and its error, the postseason model's season steps - and the few
parameters ``configs/models/simulator.json`` measured. This service assembles the
roster, prices it, draws the seasons and dresses the result with names. It fits nothing,
and every assumption in a scenario is the user's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from front_office.config.models import load_simulator_model
from front_office.domain.scenario import Scenario, SubjectKind
from front_office.domain.simulator import SimulatorModel
from front_office.domain.stages import BRACKET_STAGE_KEYS, stage
from front_office.domain.tables.rosters import STARTING_SLOTS
from front_office.modeling.postseason import probability_key
from front_office.modeling.simulator import ROSTER_COLUMNS, expected_rating, simulate
from front_office.modeling.simulator.monte_carlo import interval, stage_frame, summarise_wins
from front_office.services.builder import ASSUMED, BENCH, FROM_CONTRACT
from front_office.services.lab import Lab

FIT_COMMAND = "fol simulate fit --write"
KEPT, ADDED, REMOVED = "kept", "added", "removed"
NO_PROJECTION = "No projection: counts as a replacement player"
PLAYER_COLUMNS = (
    "player_name",
    "team",
    "position",
    "position_group",
    "age",
    "status",
    "projected_impact",
    "projected_share",
    "projection_reliability",
    "projected_wins",
    "games_missed",
    "development",
    "share",
    "salary",
    "salary_source",
    "note",
)
COMPARISON_COLUMNS = ("key", "label", "before", "after", "change", "format")
PROFILE_COLUMNS = (
    "key",
    "area",
    "name",
    "before",
    "after",
    "before_value",
    "after_value",
    "higher_is_better",
)
LEAGUE_COLUMNS = (
    "team_name",
    "abbreviation",
    "conference",
    "players",
    "projected",
    "rating",
    "wins",
    "wins_low",
    "wins_high",
    *(probability_key(key) for key in BRACKET_STAGE_KEYS),
)
TEAM_COLUMNS = ("full_name", "abbreviation", "conference", "players")
POOL_COLUMNS = (
    "player_name",
    "team",
    "team_name",
    "team_id",
    "position",
    "position_group",
    "age",
    "projected_impact",
    "projected_share",
    "projection_reliability",
    "projected_wins",
    "label",
)
SLOT_PREFERENCE = {"Guard": ("PG", "SG"), "Forward": ("SF", "PF"), "Center": ("C", "PF")}
MONEY, SIGNED, NUMBER, PERCENT = "money", "signed", "number", "percent"


class SimulatorError(ValueError):
    """A scenario cannot be run; the message says why."""


@dataclass(frozen=True, slots=True)
class SimulatorStatus:
    revision: int | None
    """Revision of the simulator's parameters on file; ``None`` when none are measured."""
    fitted_at: datetime | None
    value_model_version: str | None
    """The value model the parameters were measured against."""
    applied_value_version: str | None
    """The value model the database was built with."""
    postseason_revision: int | None
    """The postseason model on file, whose season steps the chances come from."""
    upcoming: str | None
    """The season being looked ahead to."""
    stats_season: str | None
    """The latest season played: where the profile and the roles come from."""
    has_contracts: bool
    reason: str | None
    """Why a scenario cannot be run, when it cannot."""

    @property
    def is_fitted(self) -> bool:
        return self.revision is not None

    @property
    def is_current(self) -> bool:
        return self.is_fitted and self.value_model_version == self.applied_value_version

    @property
    def is_available(self) -> bool:
        return self.reason is None


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the seasons drawn for one side of a scenario came to."""

    players: int
    projected: int
    unprojected: tuple[str, ...]
    """Players the value model has no projection for: they count as replacement players."""
    payroll: int | None
    """Sum of the salaries known; ``None`` when none is."""
    priced: int
    unpriced: int
    expected_rating: float
    """The sum of the parts without a draw: what the optimizer would show."""
    rating: float
    """Mean strength over the seasons drawn, with its interval."""
    rating_low: float
    rating_high: float
    wins: float
    wins_median: float
    wins_low: float
    wins_high: float
    top_players: float
    shares: float
    """What the players' shares of the minutes came to, on average; five is a season."""
    stages: pd.DataFrame
    """One row per stage: ``key``, ``label``, ``probability``, ``low``, ``high``."""
    wins_distribution: pd.DataFrame
    """How often each win total came up: ``wins``, ``share``."""
    seasons: int

    def chance(self, key: str) -> float:
        return float(self.stages.set_index("key").at[key, "probability"])


@dataclass(frozen=True, slots=True)
class ScenarioReport:
    scenario: Scenario
    name: str
    season: str
    """The season ahead, which the scenario is drawn for."""
    stats_season: str
    players: pd.DataFrame
    """Indexed by ``player_id``: :data:`PLAYER_COLUMNS`, the kept and added players by
    projected share, then the removed."""
    before: Outcome
    after: Outcome
    comparison: pd.DataFrame
    """One row per headline figure: :data:`COMPARISON_COLUMNS`."""
    profile: pd.DataFrame
    """Each fit measure's percentile among the latest season's teams, before and after:
    :data:`PROFILE_COLUMNS`."""

    @property
    def is_changed(self) -> bool:
        return self.scenario.is_changed


class SimulatorService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    def model(self) -> SimulatorModel | None:
        return load_simulator_model(self._lab.settings.config_dir)

    def status(self) -> SimulatorStatus:
        model = self.model()
        value = self._lab.value.status()
        postseason = self._lab.postseason.model()
        upcoming = value.upcoming
        stats = value.seasons[0] if value.seasons else None
        if model is None:
            reason = f"the simulator's parameters have not been measured; run: {FIT_COMMAND}"
        elif postseason is None:
            reason = "no postseason model has been fitted; run: fol playoffs fit --write"
        elif upcoming is None or stats is None:
            reason = (
                "no season is being looked ahead to: the value model has to be fitted and "
                "applied first (fol value fit --write, then fol build)."
            )
        elif not value.is_fitted:
            reason = "the value model is no longer on file; fit it again: fol value fit --write"
        else:
            reason = None
        return SimulatorStatus(
            revision=None if model is None else model.revision,
            fitted_at=None if model is None else model.fitted_at,
            value_model_version=None if model is None else model.value_model_version,
            applied_value_version=value.applied_revision,
            postseason_revision=None if postseason is None else postseason.revision,
            upcoming=upcoming,
            stats_season=stats,
            has_contracts=self._lab.contracts.available,
            reason=reason,
        )

    # --- what there is to work with ------------------------------------------------------

    def teams(self) -> pd.DataFrame:
        """Teams with a projected player for the season ahead, indexed by ``team_id``:
        :data:`TEAM_COLUMNS`, by name."""
        projections = self._lab.value.projections()
        labels = self._lab.team_labels()
        counts = projections["team_id"].dropna().astype("int64").value_counts()
        frame = labels.loc[
            labels.index.isin(counts.index), ["full_name", "abbreviation", "conference"]
        ]
        frame = frame.copy()
        frame["players"] = counts.reindex(frame.index).fillna(0).astype("int64")
        return frame[list(TEAM_COLUMNS)].sort_values("full_name")

    def pool(self) -> pd.DataFrame:
        """Every player with a projection for the season ahead, indexed by ``player_id``:
        :data:`POOL_COLUMNS`, by name. Who can be added to a scenario."""
        projections = self._lab.value.projections()
        frame = projections[[column for column in POOL_COLUMNS if column != "label"]].copy()
        frame["label"] = frame["player_name"] + " · " + frame["team"].fillna("no team")
        return frame[list(POOL_COLUMNS)].sort_values("player_name")

    def roster_players(self, scenario: Scenario) -> pd.DataFrame:
        """The scenario's roster: the subject's players with the changes applied, each with
        the value model's projection and the user's assumptions. Indexed by ``player_id``:
        :data:`PLAYER_COLUMNS` and :data:`ROSTER_COLUMNS`, the kept and added players by
        projected share, then the removed."""
        return self._roster_players(scenario, self.status(), self.pool())

    def _roster_players(
        self, scenario: Scenario, status: SimulatorStatus, pool: pd.DataFrame
    ) -> pd.DataFrame:
        """:meth:`roster_players` with the status and the pool read once by the caller."""
        base, assumed = self._subject(scenario, status, pool)
        removed = [player for player in base if player in scenario.removed]
        kept = [player for player in base if player not in scenario.removed]
        members = kept + [player for player in scenario.added if player not in kept]
        order = members + removed
        index = pd.Index(order, name="player_id", dtype="int64")
        known = pool.reindex(index)
        bio = (
            self._lab.read("players", {"player_id": order}).set_index("player_id")
            if order
            else pd.DataFrame(columns=["full_name", "position"]).rename_axis("player_id")
        )
        frame = pd.DataFrame(index=index)
        frame["player_name"] = known["player_name"].fillna(bio["full_name"].reindex(index))
        frame["player_name"] = frame["player_name"].fillna(
            pd.Series([f"Player {player}" for player in index], index=index)
        )
        frame["team"] = known["team"]
        frame["position"] = known["position"].fillna(bio["position"].reindex(index))
        frame["position_group"] = known["position_group"]
        frame["age"] = known["age"]
        frame["status"] = [
            REMOVED if player in removed else ADDED if player in scenario.added else KEPT
            for player in index
        ]
        for column in (
            "projected_impact",
            "projected_share",
            "projection_reliability",
            "projected_wins",
        ):
            frame[column] = known[column].astype("float64")
        frame["games_missed"] = [scenario.adjustment(p).games_missed for p in index]
        frame["development"] = [scenario.adjustment(p).development for p in index]
        frame["share"] = [scenario.adjustment(p).share for p in index]
        for column in ("games_missed", "development", "share"):
            frame[column] = frame[column].astype("float64")
        frame["salary"], frame["salary_source"] = self._priced(index, scenario, assumed, status)
        frame["note"] = np.where(frame["projected_impact"].isna(), NO_PROJECTION, "")
        frame["_order"] = [1 if player in removed else 0 for player in index]
        frame = frame.sort_values(
            ["_order", "projected_share", "player_name"], ascending=[True, False, True]
        )
        return frame[[*PLAYER_COLUMNS, *(c for c in ROSTER_COLUMNS if c not in PLAYER_COLUMNS)]]

    def default_scenario(self, subject: SubjectKind, key: int) -> Scenario:
        """A scenario with nothing changed, drawing the number of seasons the specification
        gives."""
        model = self.model()
        simulations = 10_000 if model is None else model.spec.simulations
        return Scenario(subject=subject, key=int(key), simulations=simulations)

    # --- running a scenario ------------------------------------------------------------

    def run(self, scenario: Scenario) -> ScenarioReport:
        """Seasons drawn for the scenario and for its subject as it stands, and what
        changed between them."""
        status = self.status()
        if not status.is_available:
            raise SimulatorError(status.reason or "the simulator cannot run")
        model = self.model()
        postseason = self._lab.postseason.model()
        value_model = self._lab.value.model()
        assert model is not None and postseason is not None and value_model is not None
        name = self._subject_name(scenario)
        pool = self.pool()
        after_players = self._roster_players(scenario, status, pool)
        before_players = self._roster_players(scenario.baseline, status, pool)
        before = self._outcome(
            before_players,
            scenario.baseline,
            model,
            postseason.steps,
            value_model.replacement_level,
        )
        after = self._outcome(
            after_players, scenario, model, postseason.steps, value_model.replacement_level
        )
        return ScenarioReport(
            scenario=scenario,
            name=name,
            season=str(status.upcoming),
            stats_season=str(status.stats_season),
            players=after_players,
            before=before,
            after=after,
            comparison=self._comparison(before, after),
            profile=self._profile(before_players, after_players, str(status.stats_season), name),
        )

    def league(self, simulations: int | None = None) -> pd.DataFrame:
        """Every team with projected players, drawn as it stands: :data:`LEAGUE_COLUMNS`
        indexed by ``team_id``, the best projected rating first. Empty when the simulator
        cannot run."""
        status = self.status()
        empty = pd.DataFrame(columns=list(LEAGUE_COLUMNS)).rename_axis("team_id")
        if not status.is_available:
            return empty
        model = self.model()
        postseason = self._lab.postseason.model()
        value_model = self._lab.value.model()
        assert model is not None and postseason is not None and value_model is not None
        pool = self.pool()
        rows = []
        for team_id, team in self.teams().iterrows():
            scenario = Scenario(
                subject=SubjectKind.TEAM,
                key=int(team_id),
                simulations=simulations or model.spec.simulations,
            )
            players = self._roster_players(scenario, status, pool)
            outcome = self._outcome(
                players, scenario, model, postseason.steps, value_model.replacement_level
            )
            chances = outcome.stages.set_index("key")["probability"]
            rows.append(
                {
                    "team_id": int(team_id),
                    "team_name": team["full_name"],
                    "abbreviation": team["abbreviation"],
                    "conference": team["conference"],
                    "players": outcome.players,
                    "projected": outcome.projected,
                    "rating": outcome.rating,
                    "wins": outcome.wins,
                    "wins_low": outcome.wins_low,
                    "wins_high": outcome.wins_high,
                    **{probability_key(key): float(chances[key]) for key in BRACKET_STAGE_KEYS},
                }
            )
        if not rows:
            return empty
        frame = pd.DataFrame(rows).set_index("team_id")
        return frame[list(LEAGUE_COLUMNS)].sort_values("rating", ascending=False)

    def save(self, scenario: Scenario, name: str) -> int:
        """Create a Team Builder roster from the scenario's players and return its id.

        The five largest projected shares start, each in a slot that suits the player's
        position; everyone else is on the bench. A salary the scenario assumed is kept as
        the roster's assumption. The Team Builder can change all of it.
        """
        status = self.status()
        if status.upcoming is None or status.stats_season is None:
            raise SimulatorError("no season is being looked ahead to, so there is nothing to save")
        players = self.roster_players(scenario)
        active = players[players["status"] != REMOVED].sort_values(
            "projected_share", ascending=False, na_position="last"
        )
        roster = self._lab.builder.create(
            name, stats_season=status.stats_season, payroll_season=status.upcoming
        )
        free = list(STARTING_SLOTS)
        for player_id, row in active.iterrows():
            slot = BENCH
            if free:
                wanted = [s for s in SLOT_PREFERENCE.get(row["position_group"], ()) if s in free]
                slot = wanted[0] if wanted else free[0]
                free.remove(slot)
            assumed = row["salary"] if row["salary_source"] == ASSUMED else None
            self._lab.builder.add_player(
                roster,
                int(player_id),
                slot=slot,
                assumed_salary=None if assumed is None or pd.isna(assumed) else int(assumed),
            )
        return roster

    # --- assembly -------------------------------------------------------------------------

    def _subject(
        self, scenario: Scenario, status: SimulatorStatus, pool: pd.DataFrame
    ) -> tuple[list[int], dict[int, int]]:
        """The subject's players in order, and the salaries a built roster assumes."""
        if scenario.subject is SubjectKind.TEAM:
            mine = pool[pool["team_id"] == scenario.key].sort_values(
                "projected_share", ascending=False
            )
            members = [int(player) for player in mine.index]
            if status.upcoming is not None:
                listed = self._lab.read(
                    "team_rosters", {"season": status.upcoming, "team_id": int(scenario.key)}
                )
                members += [
                    int(player) for player in listed["player_id"] if int(player) not in members
                ]
            return members, {}
        members = self._lab.rosters.players(int(scenario.key))
        assumed = {
            int(row["player_id"]): int(row["assumed_salary"])
            for row in members.to_dict("records")
            if pd.notna(row.get("assumed_salary"))
        }
        return [int(player) for player in members["player_id"]], assumed

    def _subject_name(self, scenario: Scenario) -> str:
        if scenario.subject is SubjectKind.TEAM:
            names = self._lab.team_labels()["full_name"]
            return str(names.get(int(scenario.key), f"Team {scenario.key}"))
        return str(self._lab.rosters.get(int(scenario.key))["name"])

    def _priced(
        self,
        index: pd.Index,
        scenario: Scenario,
        assumed: dict[int, int],
        status: SimulatorStatus,
    ) -> tuple[pd.Series, pd.Series]:
        """Each player's salary: the scenario's figure, else the roster's assumption, else
        the contract file's for the season ahead."""
        salary = pd.Series(np.nan, index=index, dtype="float64")
        source = pd.Series(pd.NA, index=index, dtype="str")
        if status.has_contracts and status.upcoming is not None:
            contracts = self._lab.contracts.salaries(status.upcoming)["salary"]
            known = contracts.reindex(index).astype("float64")
            salary[known.notna()] = known[known.notna()]
            source[known.notna()] = FROM_CONTRACT
        for player in index:
            figure = scenario.adjustment(int(player)).salary
            if figure is None:
                figure = assumed.get(int(player))
            if figure is not None:
                salary[player] = float(figure)
                source[player] = ASSUMED
        return salary, source

    def _outcome(
        self,
        players: pd.DataFrame,
        scenario: Scenario,
        model: SimulatorModel,
        steps,  # type: ignore[no-untyped-def]
        replacement: float,
    ) -> Outcome:
        active = players[players["status"] != REMOVED]
        roster = active[list(ROSTER_COLUMNS)]
        simulation = simulate(
            roster,
            model=model,
            steps=steps,
            replacement=replacement,
            availability=scenario.availability,
            development=scenario.development,
            simulations=scenario.simulations,
            seed=scenario.seed,
        )
        confidence = model.spec.wins_interval
        rating_low, rating_high = interval(simulation.strength, confidence)
        wins_low, wins_high = interval(simulation.wins, confidence)
        salaries = active["salary"]
        labels = {key: stage(key).label for key in BRACKET_STAGE_KEYS}
        return Outcome(
            players=int(len(active)),
            projected=simulation.projected,
            unprojected=tuple(
                str(name) for name in active.loc[active["projected_impact"].isna(), "player_name"]
            ),
            payroll=int(salaries.dropna().sum()) if salaries.notna().any() else None,
            priced=int(salaries.notna().sum()),
            unpriced=int(salaries.isna().sum()),
            expected_rating=expected_rating(roster, replacement),
            rating=float(simulation.strength.mean()),
            rating_low=rating_low,
            rating_high=rating_high,
            wins=float(simulation.wins.mean()),
            wins_median=float(np.median(simulation.wins)),
            wins_low=wins_low,
            wins_high=wins_high,
            top_players=float(simulation.top_players.mean()),
            shares=float(simulation.shares.mean()),
            stages=stage_frame(simulation, labels),
            wins_distribution=summarise_wins(simulation.wins),
            seasons=simulation.seasons,
        )

    @staticmethod
    def _comparison(before: Outcome, after: Outcome) -> pd.DataFrame:
        rows = [
            ("payroll", "Payroll", before.payroll, after.payroll, MONEY),
            ("rating", "Projected net rating", before.rating, after.rating, SIGNED),
            ("wins", "Projected wins", before.wins, after.wins, NUMBER),
            ("top_players", "Top-player quality", before.top_players, after.top_players, SIGNED),
        ]
        for key in BRACKET_STAGE_KEYS:
            rows.append(
                (
                    probability_key(key),
                    stage(key).label,
                    before.chance(key),
                    after.chance(key),
                    PERCENT,
                )
            )
        frame = pd.DataFrame(rows, columns=["key", "label", "before", "after", "format"])
        frame["before"] = frame["before"].astype("float64")
        frame["after"] = frame["after"].astype("float64")
        frame["change"] = frame["after"] - frame["before"]
        return frame[list(COMPARISON_COLUMNS)]

    def _profile(
        self, before: pd.DataFrame, after: pd.DataFrame, season: str, name: str
    ) -> pd.DataFrame:
        """Each fit measure's percentile among the season's teams, for the players as they
        showed in the season played, weighted by their shares of the minutes."""
        placed = {}
        tables = self._lab.fit.season_tables(season)
        for side, players in (("before", before), ("after", after)):
            active = players[players["status"] != REMOVED]
            shares = active["share"].fillna(active["projected_share"]).fillna(0.0)
            report = self._lab.fit.lineup(
                [int(p) for p in active.index],
                season,
                {int(p): float(s) for p, s in shares.items()},
                name,
                tables=tables,
            )
            placed[side] = report.placed.set_index("key")
        frame = placed["before"][["area", "name", "higher_is_better"]].copy()
        frame["before"] = placed["before"]["percentile"]
        frame["after"] = placed["after"]["percentile"].reindex(frame.index)
        frame["before_value"] = placed["before"]["value"]
        frame["after_value"] = placed["after"]["value"].reindex(frame.index)
        return frame.reset_index()[list(PROFILE_COLUMNS)]
