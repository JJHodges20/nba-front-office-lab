"""Player value for the workbench: what the fitted model says, and what it rests on.

This module reads ``player_value_scores`` and the fitted model file and joins them with
names and teams. It fits nothing and scores nothing: a build did that, with the model
on file at the time, and every row says which revision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from front_office.analytics import comparison as compare
from front_office.config.archetypes import load_archetypes
from front_office.config.models import load_value_model
from front_office.domain.archetypes import ArchetypeSet
from front_office.domain.metrics import MetricCatalog
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.value_model import NET, SIDES, Comparison, ValueModel
from front_office.modeling import archetypes as roles
from front_office.modeling.value import (
    COMPONENTS,
    FEATURES,
    LEVEL_DESCRIPTIONS,
    LEVEL_KEYS,
    LEVEL_LABELS,
)
from front_office.modeling.value.catalog import (
    PART_KEYS,
    PROJECTION_KEYS,
    SEASON_KEYS,
    VALUE_METRICS,
)
from front_office.modeling.value.market import SURPLUS_COLUMNS, Market, fit_market, surplus
from front_office.services.lab import Lab

TABLE = "player_value_scores"
ROLES = "player_archetypes"
REGULAR = SeasonType.REGULAR.value
LEVELS = "Levels"
MODEL_ROW = "value_model"
ASSUMED = "Assumed"
"""What the part of an impact that the minutes do not vouch for is called on screen."""

SEASON_COLUMNS = (
    "player_name",
    "team",
    "team_name",
    "team_id",
    "position",
    "position_group",
    "age",
    "games_played",
    "minutes",
    *SEASON_KEYS,
    "wins_rank",
    "impact_rank",
    *PART_KEYS,
    *PROJECTION_KEYS,
)
PROJECTION_COLUMNS = (
    "player_name",
    "team",
    "team_name",
    "team_id",
    "position",
    "position_group",
    "age",
    *PROJECTION_KEYS,
    "projection_seasons",
    "last_season",
    "last_impact",
    "last_minutes_share",
)
HISTORY_COLUMNS = ("season", "age", "team", *SEASON_KEYS, *PART_KEYS, *PROJECTION_KEYS)
MONEY_COLUMNS = (
    "player_name",
    "team",
    "team_id",
    "position",
    "age",
    "salary",
    "salary_cap_pct",
    "years_remaining",
    "rating",
    "wins",
    *SURPLUS_COLUMNS,
)

PLAYED = "played"
PROJECTED = "projected"

ROLE_COLUMNS = ("role", "roles")
ROLE_PLAYER_COLUMNS = (
    "player_name",
    "team",
    "team_id",
    "position",
    "age",
    "score",
    "is_primary",
    "roles",
    "impact",
    "wins_added",
)
ROLE_SUMMARY_COLUMNS = (
    "archetype",
    "name",
    "description",
    "open_to",
    "measures",
    "fills_at",
    "fills_below",
    "note",
    "scored",
    "filled",
    "primary",
    "again",
    "anyone",
)
ROLE_SEPARATOR = ", "


@dataclass(frozen=True, slots=True)
class ValueStatus:
    """Where player value stands: is there a model, has it been applied, is it current."""

    revision: int | None
    """Revision of the fitted model on file, or ``None`` if there is none."""
    fitted_at: datetime | None
    fitted_through: str | None
    """The last season the model on file was fitted on."""
    applied_revision: str | None
    """The revision stamped on the rows in the database, or ``None`` if there are none."""
    seasons: tuple[str, ...]
    """Seasons with a season impact, newest first."""
    upcoming: str | None
    """The season that projections look ahead to, if any row is a projection alone."""
    finished_since: tuple[str, ...]
    """Finished seasons with player statistics that the model was not fitted on."""

    @property
    def is_fitted(self) -> bool:
        return self.revision is not None

    @property
    def is_available(self) -> bool:
        """Whether there is anything to show."""
        return bool(self.seasons)

    @property
    def needs_build(self) -> bool:
        """Whether the model on file is not the one the database was built with."""
        return self.is_fitted and self.applied_revision != f"r{self.revision}"


@dataclass(frozen=True, slots=True)
class ModelCard:
    """A fitted model laid out for reading: what it is, and the evidence for it."""

    model: ValueModel
    terms: pd.DataFrame
    """One row per weight: label, group, the weight on each side with its interval."""
    baselines: pd.DataFrame
    """The model and each simpler method on the out-of-sample test, best first."""
    ablations: pd.DataFrame
    """The model with each part left out, the costliest omission first."""
    backtest: pd.DataFrame
    """Every team-season of the test: predicted and actual rating relative to the league."""
    by_season: pd.DataFrame


@dataclass(frozen=True, slots=True)
class ValueForMoney:
    """Salaries on file set against what the value model says the players are worth."""

    season: str
    basis: str | None
    """``played``: what the season showed. ``projected``: what is expected going into
    it. ``None``: the season has not been valued, and ``players`` is empty."""
    market: Market | None
    """What the contracts on file pay for a win, if a price can be read off them."""
    players: pd.DataFrame
    """Indexed by ``player_id``: :data:`MONEY_COLUMNS`, the largest surplus first.
    ``rating`` and ``wins`` are the impact and wins of the ``basis``."""
    unvalued: int
    """Players with a salary in the season and no value to set it against."""


class ValueService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def metrics(self) -> MetricCatalog:
        return VALUE_METRICS

    def model(self) -> ValueModel | None:
        """The fitted model on file. A build may have applied an earlier revision."""
        return load_value_model(self._lab.settings.config_dir)

    def status(self) -> ValueStatus:
        model = self.model()
        warehouse = self._lab.warehouse
        valued = warehouse.distinct(TABLE, "season")
        applied = warehouse.distinct(TABLE, "model_version")
        played = set(warehouse.distinct("player_seasons", "season", {"season_type": REGULAR}))
        ahead = warehouse.distinct(TABLE, "season", {"impact": None})
        return ValueStatus(
            revision=None if model is None else model.revision,
            fitted_at=None if model is None else model.fitted_at,
            fitted_through=None if model is None else model.fitted_on.last_season,
            applied_revision=applied[0] if applied else None,
            seasons=tuple(sorted((season for season in valued if season in played), reverse=True)),
            upcoming=max(ahead, default=None),
            finished_since=() if model is None else self._finished_since(model),
        )

    def season(self, season: str) -> pd.DataFrame:
        """Everyone with an impact in a season, the most valuable first.

        Indexed by ``player_id``: :data:`SEASON_COLUMNS`. The two ranks are among
        everyone who played that season, 1 being best. Empty when the season has not
        been valued.
        """
        scores = self._lab.read(TABLE, {"season": season})
        scores = scores[scores["impact"].notna()].set_index("player_id")
        lines = self._lab.read("player_seasons", {"season": season, "season_type": REGULAR})
        lines = lines.set_index("player_id")[["player_name", "team_id", "games_played", "minutes"]]
        frame = lines.join(scores.drop(columns=["season", "model_version"]), how="inner")
        frame = self._with_identity(frame)
        frame["wins_rank"] = compare.ranks(frame, VALUE_METRICS, "wins_added")
        frame["impact_rank"] = compare.ranks(frame, VALUE_METRICS, "impact")
        return frame[list(SEASON_COLUMNS)].sort_values("wins_added", ascending=False)

    def projections(self) -> pd.DataFrame:
        """What is expected of each player in the season still to be played.

        Indexed by ``player_id``: :data:`PROJECTION_COLUMNS`, the most projected wins
        first. ``last_...`` columns recall the newest season each player has on record.
        Empty when no season is being looked ahead to.
        """
        upcoming = self.status().upcoming
        empty = pd.DataFrame(columns=list(PROJECTION_COLUMNS)).rename_axis("player_id")
        if upcoming is None:
            return empty
        scores = self._lab.read(TABLE, {"season": upcoming})
        scores = scores[scores["impact"].isna()].set_index("player_id")
        if scores.empty:
            return empty
        players = self._lab.read("players", {"player_id": scores.index.tolist()})
        players = players.set_index("player_id")
        frame = scores[["age", *PROJECTION_KEYS, "projection_seasons"]].copy()
        frame["player_name"] = players["full_name"].reindex(frame.index)
        frame["team_id"] = players["current_team_id"].reindex(frame.index)

        earlier = self._lab.read(TABLE, {"player_id": frame.index.tolist()})
        earlier = earlier[earlier["impact"].notna()].sort_values("season")
        newest = earlier.groupby("player_id").tail(1).set_index("player_id")
        frame["last_season"] = newest["season"].reindex(frame.index)
        frame["last_impact"] = newest["impact"].reindex(frame.index)
        frame["last_minutes_share"] = newest["minutes_share"].reindex(frame.index)
        frame = self._with_identity(frame, players)
        return frame[list(PROJECTION_COLUMNS)].sort_values("projected_wins", ascending=False)

    def player(self, player_id: int) -> pd.DataFrame:
        """One player's value in every season, oldest first: :data:`HISTORY_COLUMNS`.

        The last row is the projection into the season still to be played, if the
        player has one. ``team`` is the team the season ended with.
        """
        scores = self._lab.read(TABLE, {"player_id": int(player_id)}).sort_values("season")
        lines = self._lab.read(
            "player_seasons", {"player_id": int(player_id), "season_type": REGULAR}
        )
        teams = self._lab.team_labels()["abbreviation"]
        team_of = lines.set_index("season")["team_id"].map(teams)
        scores["team"] = scores["season"].map(team_of)
        return scores[list(HISTORY_COLUMNS)].reset_index(drop=True)

    def parts(self, player_id: int, season: str) -> pd.DataFrame:
        """Where one season's impact comes from: a row per part, adding up to the impact.

        ``key``, ``label``, ``description`` and ``value``, in the order the parts are
        defined. Empty when the player has no impact in that season.
        """
        columns = ["key", "label", "description", "value"]
        scores = self._lab.read(TABLE, {"player_id": int(player_id), "season": season})
        scores = scores[scores["impact"].notna()]
        if scores.empty:
            return pd.DataFrame(columns=columns)
        row = scores.iloc[0]
        specs = [VALUE_METRICS[key] for key in PART_KEYS]
        return pd.DataFrame(
            {
                "key": [spec.key for spec in specs],
                "label": [*(component.label for component in COMPONENTS), ASSUMED],
                "description": [spec.description for spec in specs],
                "value": [float(row[spec.key]) for spec in specs],
            },
            columns=columns,
        )

    # --- roles ----------------------------------------------------------------------------

    def archetypes(self) -> ArchetypeSet:
        """The archetype definitions on file."""
        return load_archetypes(self._lab.settings.config_dir)

    def roles(self, season: str) -> pd.DataFrame:
        """The roles each player fills in a season, indexed by ``player_id``.

        ``role`` is the name of the primary role and ``roles`` every role filled, in the
        order the archetypes are defined, joined by commas. Only players who fill at
        least one role appear.
        """
        filled = self._lab.read(ROLES, {"season": season, "fills": True})
        empty = pd.DataFrame(columns=list(ROLE_COLUMNS)).rename_axis("player_id")
        if filled.empty:
            return empty
        spec = self.archetypes()
        names = {archetype.key: archetype.name for archetype in spec}
        order = {key: position for position, key in enumerate(spec.keys)}
        known = filled[filled["archetype"].isin(names)]
        known = known.assign(
            order=known["archetype"].map(order), name=known["archetype"].map(names)
        ).sort_values(["player_id", "order"])
        frame = known.groupby("player_id")["name"].agg(ROLE_SEPARATOR.join).to_frame("roles")
        primary = known[known["is_primary"]].set_index("player_id")["name"]
        frame.insert(0, "role", primary.reindex(frame.index))
        return frame

    def role_players(self, season: str, archetype: str) -> pd.DataFrame:
        """Who fills one role in a season, the highest score first.

        Indexed by ``player_id``: :data:`ROLE_PLAYER_COLUMNS`. ``roles`` is every role
        the player fills; ``impact`` and ``wins_added`` are the value model's.
        """
        scored = self._lab.read(ROLES, {"season": season, "archetype": archetype, "fills": True})
        scored = scored.set_index("player_id")[["score", "is_primary"]]
        valued = self.season(season)
        frame = scored.join(valued, how="inner").join(self.roles(season)[["roles"]])
        return frame[list(ROLE_PLAYER_COLUMNS)].sort_values("score", ascending=False)

    def role_summary(self, season: str) -> pd.DataFrame:
        """Each archetype as defined, how many players it scored and how many fill it in
        one season, and how well it carries over between seasons on the whole record.

        :data:`ROLE_SUMMARY_COLUMNS`, in the order the archetypes are defined. ``again``
        is the share of players filling a role who fill it the next season too, and
        ``anyone`` the share of all players scored for it who do.
        """
        spec = self.archetypes()
        assigned = self._lab.read(ROLES)
        mine = assigned[assigned["season"] == season]
        counts = mine.groupby("archetype").agg(
            scored=("score", "size"), filled=("fills", "sum"), primary=("is_primary", "sum")
        )
        carried = roles.persistence(assigned, spec).set_index("archetype")
        groups = {group.key: group.label for group in roles.GROUPS}
        measures = {measure.key: measure.label for measure in roles.MEASURES}
        rows = []
        for archetype in spec:
            count = counts.loc[archetype.key] if archetype.key in counts.index else None
            rows.append(
                {
                    "archetype": archetype.key,
                    "name": archetype.name,
                    "description": archetype.description,
                    "open_to": groups[archetype.among],
                    "measures": ", ".join(measures[key].lower() for key in archetype.measures),
                    "fills_at": spec.cut(archetype),
                    "fills_below": archetype.fills_below,
                    "note": archetype.note,
                    "scored": 0 if count is None else int(count["scored"]),
                    "filled": 0 if count is None else int(count["filled"]),
                    "primary": 0 if count is None else int(count["primary"]),
                    "again": carried.at[archetype.key, "again"],
                    "anyone": carried.at[archetype.key, "anyone"],
                }
            )
        return pd.DataFrame(rows, columns=list(ROLE_SUMMARY_COLUMNS))

    def for_money(self, season: str) -> ValueForMoney:
        """One season's salaries against the wins they pay for.

        A season that has been played is judged on what it showed; the season still to
        be played, on its projection. Later seasons of a contract are not valued: the
        model looks one season ahead and no further.
        """
        status = self.status()
        salaries = self._lab.contracts.salaries(season)
        columns = {
            PLAYED: ("impact", "wins_added"),
            PROJECTED: ("projected_impact", "projected_wins"),
        }
        basis = (
            PROJECTED if season == status.upcoming else PLAYED if season in status.seasons else None
        )
        empty = pd.DataFrame(columns=list(MONEY_COLUMNS)).rename_axis("player_id")
        if basis is None or salaries.empty:
            return ValueForMoney(season, basis, None, empty, len(salaries))

        rating, wins = columns[basis]
        scores = self._lab.read(TABLE, {"season": season}).set_index("player_id")
        valued = salaries.join(scores[["age", rating, wins]], how="left")
        valued = valued.rename(columns={rating: "rating", wins: "wins"})
        known = valued[valued["wins"].notna()].copy()
        market = fit_market(known["salary"], known["wins"])
        known = known.join(surplus(known["salary"], known["wins"], market))

        players = self._lab.read("players", {"player_id": known.index.tolist()})
        players = players.set_index("player_id")
        known["player_name"] = players["full_name"].reindex(known.index)
        teams = self._lab.read("contract_years", {"season": season})
        teams = teams.drop_duplicates("player_id").set_index("player_id")["team_id"]
        known["team_id"] = teams.reindex(known.index)
        known = self._with_identity(known, players)
        order = "surplus" if market is not None else "wins"
        ranked = known[list(MONEY_COLUMNS)].sort_values(order, ascending=False)
        return ValueForMoney(season, basis, market, ranked, len(valued) - len(known))

    def card(self) -> ModelCard | None:
        """The fitted model on file, laid out for reading; ``None`` if there is none."""
        model = self.model()
        if model is None:
            return None
        return ModelCard(
            model=model,
            terms=term_table(model),
            baselines=baseline_table(model),
            ablations=comparison_table(model.validation.ablations).sort_values(
                "difference", ascending=False, ignore_index=True
            ),
            backtest=self._backtest(model),
            by_season=pd.DataFrame(
                [score.model_dump() for score in model.validation.by_season],
                columns=["season", "teams", "rmse"],
            ),
        )

    # --- assembly -----------------------------------------------------------------------

    def _with_identity(
        self, frame: pd.DataFrame, players: pd.DataFrame | None = None
    ) -> pd.DataFrame:
        teams = self._lab.team_labels()
        if players is None:
            players = self._lab.read("players", {"player_id": frame.index.tolist()})
            players = players.set_index("player_id")
        frame = frame.copy()
        frame["team"] = frame["team_id"].map(teams["abbreviation"])
        frame["team_name"] = frame["team_id"].map(teams["full_name"])
        frame["position"] = players["position"].reindex(frame.index)
        frame["position_group"] = frame["position"].map(compare.position_group)
        return frame

    def _backtest(self, model: ValueModel) -> pd.DataFrame:
        columns = [
            "season", "team_id", "team", "team_name", "predicted", "actual", "error",
            "predicted_offense", "actual_offense", "predicted_defense", "actual_defense",
        ]  # fmt: skip
        if not model.backtest:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame([row.model_dump() for row in model.backtest])
        frame["predicted"] = frame["predicted_offense"] + frame["predicted_defense"]
        frame["actual"] = frame["actual_offense"] + frame["actual_defense"]
        frame["error"] = frame["predicted"] - frame["actual"]
        teams = self._lab.team_labels()
        frame["team"] = frame["team_id"].map(teams["abbreviation"])
        frame["team_name"] = frame["team_id"].map(teams["full_name"])
        return frame[columns]

    def _finished_since(self, model: ValueModel) -> tuple[str, ...]:
        teams = self._lab.read("team_seasons")
        finished = set(teams.loc[teams["won_championship"].notna(), "season"])
        with_players = set(self._lab.warehouse.distinct("player_seasons", "season"))
        last = Season.parse(model.fitted_on.last_season)
        newer = [season for season in finished & with_players if Season.parse(season) > last]
        return tuple(sorted(newer))


def term_table(model: ValueModel) -> pd.DataFrame:
    """Every weight of a model with its name, its group and its intervals.

    ``known`` says whether the interval of the weight on both sides together excludes
    zero: whether the data can tell the term from nothing.
    """
    group_of = {component.key: component.label for component in COMPONENTS}
    named = {
        feature.key: (feature.label, group_of[feature.component], feature.description)
        for feature in FEATURES
    }
    named.update({key: (LEVEL_LABELS[key], LEVELS, LEVEL_DESCRIPTIONS[key]) for key in LEVEL_KEYS})
    rows = []
    for term in model.terms:
        label, group, description = named[term.key]
        row = {"key": term.key, "label": label, "group": group, "description": description}
        for side in (*SIDES, NET):
            low, high = term.interval(side)
            row.update({side: term.weight(side), f"{side}_low": low, f"{side}_high": high})
        row["known"] = term.net_low > 0 or term.net_high < 0
        rows.append(row)
    return pd.DataFrame(rows)


def comparison_table(items: tuple[Comparison, ...]) -> pd.DataFrame:
    columns = ["key", "label", "rmse", "mae", "difference", "low", "high", "distinguishable"]
    rows = [{**item.model_dump(), "distinguishable": item.is_distinguishable} for item in items]
    return pd.DataFrame(rows, columns=columns)


def baseline_table(model: ValueModel) -> pd.DataFrame:
    """The model and the methods it is set against, the smallest error first.

    The model's own row has no difference. For every other row ``difference`` is the
    model's error less that method's, so negative means the model predicted better.
    """
    tested = model.validation
    table = comparison_table(tested.baselines)
    own = {
        "key": MODEL_ROW,
        "label": "Value model",
        "rmse": tested.net.rmse,
        "mae": tested.net.mae,
        "difference": None,
        "low": None,
        "high": None,
        "distinguishable": None,
    }
    table = pd.concat([pd.DataFrame([own]).astype(object), table.astype(object)], ignore_index=True)
    for column in ("rmse", "mae", "difference", "low", "high"):
        table[column] = pd.to_numeric(table[column])
    return table.sort_values("rmse", ignore_index=True)
