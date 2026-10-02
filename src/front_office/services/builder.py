"""The Team Builder: rosters the user assembles by hand, priced and described.

A roster is the user's assumption. This service stores it, prices it against a season's
cap, and describes the players as a group. It ranks nothing and recommends nothing:
choosing players is the user's job until the optimiser exists.

This module assembles: it reads tables, calls analytics, and joins the results with
names. It contains no formulas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from front_office.analytics import rosters as analytics
from front_office.analytics.comparison import Qualification, position_group
from front_office.analytics.finance import PayrollSummary, cap_share, payroll_summary
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.metrics import MetricCatalog
from front_office.domain.seasons import SeasonType
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS
from front_office.domain.tables.rosters import ROSTER_SLOTS, STARTING_SLOTS
from front_office.services.lab import Lab
from front_office.storage import RosterNotFound, StorageError

BENCH = ROSTER_SLOTS[-1]
FROM_CONTRACT = "contract"
ASSUMED = "assumed"

_STAT_COLUMNS = (
    "team",
    "age",
    "experience_years",
    "games_played",
    "minutes",
    "minutes_per_game",
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "ts_pct",
    "usage_pct",
)
PLAYER_COLUMNS = (
    "slot",
    "player_name",
    "position",
    "position_group",
    *_STAT_COLUMNS,
    "salary",
    "salary_cap_pct",
    "salary_source",
    "contract_salary",
    "assumed_salary",
)


class RosterError(ValueError):
    """The user asked for something a roster cannot do."""


@dataclass(frozen=True, slots=True)
class RosterCheck:
    """One thing about a roster measured against the season's roster rules."""

    key: str
    passed: bool
    message: str


@dataclass(frozen=True, slots=True)
class RosterSummary:
    roster: dict
    """The roster as stored: id, name, the two seasons, notes, timestamps."""
    players: pd.DataFrame
    """Indexed by ``player_id``, starters first: slot, identity, season line, salary."""
    payroll_total: int
    """Sum of the salaries that are known. Understated while ``unpriced`` is not zero."""
    payroll: PayrollSummary | None
    """The total against each cap line; ``None`` if the payroll season has no cap rules."""
    rules: SeasonRules | None
    priced: int
    """Players whose salary comes from the contract data."""
    assumed: int
    """Players whose salary the user entered."""
    unpriced: int
    """Players with no salary from either source."""
    indicators: pd.Series
    """One value per roster metric: what the group adds up to."""
    league: pd.Series
    """The league-wide value of each pooled indicator, for reference."""
    metrics: MetricCatalog
    checks: tuple[RosterCheck, ...]


class BuilderService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab
        self._rosters = lab.rosters

    @property
    def metrics(self) -> MetricCatalog:
        return analytics.ROSTER_METRICS

    # --- rosters ------------------------------------------------------------------------

    def rosters(self) -> pd.DataFrame:
        """Every roster, most recently changed first, with how many players each holds."""
        rosters = self._rosters.list()
        counts = self._lab.read("roster_players").groupby("roster_id").size()
        rosters["players"] = rosters["roster_id"].map(counts).fillna(0).astype("int64")
        return rosters

    def create(
        self, name: str, *, stats_season: str | None = None, payroll_season: str | None = None
    ) -> int:
        """Create an empty roster and return its id.

        By default it is described by the newest season with player statistics and
        priced in the lab's default payroll season.
        """
        status = self._lab.status()
        stats = stats_season or (status.player_seasons[0] if status.player_seasons else None)
        payroll = payroll_season or status.default_payroll_season
        if stats is None:
            raise RosterError("there are no player statistics to build a roster from yet")
        if payroll is None:
            raise RosterError("no season has cap rules to price a roster against")
        return _stored(self._rosters.create, name, stats_season=stats, payroll_season=payroll)

    def update(
        self,
        roster_id: int,
        *,
        name: str | None = None,
        stats_season: str | None = None,
        payroll_season: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Change a roster's name, seasons or notes. Arguments left out are not changed."""
        _stored(
            self._rosters.update,
            roster_id,
            name=name,
            stats_season=stats_season,
            payroll_season=payroll_season,
            notes=notes,
        )

    def delete(self, roster_id: int) -> None:
        self._rosters.delete(roster_id)

    # --- players ------------------------------------------------------------------------

    def add_player(
        self,
        roster_id: int,
        player_id: int,
        *,
        slot: str = BENCH,
        assumed_salary: int | None = None,
    ) -> None:
        """Add a player, who must exist and can be on a roster only once."""
        members = self._rosters.players(roster_id)
        if self._lab.read("players", {"player_id": int(player_id)}).empty:
            raise RosterError(f"no player with id {player_id}")
        if int(player_id) in set(members["player_id"]):
            raise RosterError("that player is already on the roster")
        self._place(roster_id, members, int(player_id), slot, assumed_salary)

    def move_player(self, roster_id: int, player_id: int, slot: str) -> None:
        """Put a player in another slot, keeping any salary the user assumed."""
        members = self._rosters.players(roster_id)
        current = _member(members, player_id)
        self._place(roster_id, members, int(player_id), slot, _assumed(current))

    def assume_salary(self, roster_id: int, player_id: int, salary: int | None) -> None:
        """Set the salary to use for a player, or ``None`` to go back to the contract data."""
        current = _member(self._rosters.players(roster_id), player_id)
        _stored(
            self._rosters.set_player,
            roster_id,
            int(player_id),
            slot=current["slot"],
            assumed_salary=None if salary is None else int(salary),
        )

    def remove_player(self, roster_id: int, player_id: int) -> None:
        self._rosters.remove_player(roster_id, int(player_id))

    def clear(self, roster_id: int) -> None:
        self._rosters.clear(roster_id)

    # --- summary ------------------------------------------------------------------------

    def summary(self, roster_id: int) -> RosterSummary:
        """The roster priced against its payroll season and described as a group."""
        roster = self._rosters.get(roster_id)
        members = self._rosters.players(roster_id).set_index("player_id")
        stats_season, payroll_season = roster["stats_season"], roster["payroll_season"]
        rules = self._lab.rules(payroll_season)

        players = self._described(members, stats_season)
        players = self._priced(players, payroll_season, rules)
        payroll_total = int(players["salary"].dropna().sum())
        source = players["salary_source"]

        seasons = self._lab.read(
            "player_seasons", {"season": stats_season, "season_type": SeasonType.REGULAR.value}
        )
        totals = seasons.set_index("player_id").reindex(players.index)
        described = totals[["games_played", "minutes", "plus_minus", "age", *BOX_SCORE_COLUMNS]]
        described = described.assign(position_group=players["position_group"])
        indicators = analytics.roster_indicators(
            described, team_games=self._team_games(stats_season)
        )

        return RosterSummary(
            roster=roster,
            players=players[list(PLAYER_COLUMNS)],
            payroll_total=payroll_total,
            payroll=None if rules is None else payroll_summary(payroll_total, rules),
            rules=rules,
            priced=int((source == FROM_CONTRACT).sum()),
            assumed=int((source == ASSUMED).sum()),
            unpriced=int(source.isna().sum()),
            indicators=indicators,
            league=analytics.league_reference(seasons),
            metrics=analytics.ROSTER_METRICS,
            checks=_checks(players, rules),
        )

    # --- assembly -----------------------------------------------------------------------

    def _described(self, members: pd.DataFrame, stats_season: str) -> pd.DataFrame:
        """Roster members with who they are and what they did in the statistics season."""
        league = self._lab.players.table(stats_season, qualification=Qualification()).players
        bio = self._lab.read("players", {"player_id": members.index.tolist()})
        bio = bio.set_index("player_id").reindex(members.index)

        players = members[["slot", "assumed_salary"]].copy()
        players["player_name"] = bio["full_name"]
        players["position"] = bio["position"]
        # From the listed position, so a player with no line that season still has one.
        players["position_group"] = players["position"].map(position_group)
        for column in _STAT_COLUMNS:
            players[column] = league[column].reindex(players.index)

        order = {slot: number for number, slot in enumerate(ROSTER_SLOTS)}
        players["slot_order"] = players["slot"].map(order)
        players = players.sort_values(
            ["slot_order", "minutes", "player_name"], ascending=[True, False, True]
        )
        return players.drop(columns="slot_order")

    def _priced(
        self, players: pd.DataFrame, payroll_season: str, rules: SeasonRules | None
    ) -> pd.DataFrame:
        """Each player's salary: the user's figure where given, else the contract data's."""
        contracts = self._lab.contracts.salaries(payroll_season)["salary"]
        priced = players.copy()
        assumed = priced["assumed_salary"].astype("Int64")
        contract = contracts.reindex(priced.index).astype("Int64")
        priced["contract_salary"] = contract
        priced["salary"] = assumed.fillna(contract)
        source = pd.Series(pd.NA, index=priced.index, dtype="str")
        source[contract.notna()] = FROM_CONTRACT
        source[assumed.notna()] = ASSUMED
        priced["salary_source"] = source
        if rules is None:
            priced["salary_cap_pct"] = float("nan")
        else:
            priced["salary_cap_pct"] = cap_share(priced["salary"], rules.salary_cap)
        return priced

    def _place(
        self,
        roster_id: int,
        members: pd.DataFrame,
        player_id: int,
        slot: str,
        assumed_salary: int | None,
    ) -> None:
        """Put a player in a slot; whoever held a starting slot goes to the bench."""
        if slot not in ROSTER_SLOTS:
            raise RosterError(f"slot must be one of {list(ROSTER_SLOTS)}, not {slot!r}")
        if slot in STARTING_SLOTS:
            holders = members[(members["slot"] == slot) & (members["player_id"] != player_id)]
            for holder in holders.to_dict("records"):
                _stored(
                    self._rosters.set_player,
                    roster_id,
                    int(holder["player_id"]),
                    slot=BENCH,
                    assumed_salary=_assumed(holder),
                )
        _stored(
            self._rosters.set_player,
            roster_id,
            player_id,
            slot=slot,
            assumed_salary=assumed_salary,
        )

    def _team_games(self, season: str) -> float:
        games = self._lab.read("team_seasons", {"season": season})["games_played"]
        return float(games.max()) if len(games) else float("nan")


def _stored(action: Callable[..., Any], *args: object, **kwargs: object) -> Any:
    """Run a repository call, turning a rejected value into a :class:`RosterError`.

    A roster that does not exist stays a ``RosterNotFound``: that is not something the
    user typed wrong.
    """
    try:
        return action(*args, **kwargs)
    except RosterNotFound:
        raise
    except (StorageError, ValueError) as error:
        raise RosterError(str(error)) from error


def _member(members: pd.DataFrame, player_id: int) -> dict:
    found = members[members["player_id"] == int(player_id)]
    if found.empty:
        raise RosterError("that player is not on the roster")
    return found.iloc[0].to_dict()


def _assumed(member: dict) -> int | None:
    value = member["assumed_salary"]
    return None if pd.isna(value) else int(value)


def _checks(players: pd.DataFrame, rules: SeasonRules | None) -> tuple[RosterCheck, ...]:
    """The roster measured against the season's roster rules. Facts, not advice."""
    size = len(players)
    checks = []
    if rules is not None:
        most = rules.roster.max_standard_contracts
        fewest = rules.roster.min_standard_contracts
        if size > most:
            verdict = f"{size - most} more than the {most} standard contracts a team may carry"
        elif size < fewest:
            verdict = f"{fewest - size} short of the {fewest} a team must generally carry"
        else:
            verdict = f"within the {fewest} to {most} standard contracts a team carries"
        checks.append(
            RosterCheck("size", fewest <= size <= most, f"{size} players: {verdict} in season.")
        )

    empty = [slot for slot in STARTING_SLOTS if not (players["slot"] == slot).any()]
    starters = "Every starting position is filled."
    if empty:
        starters = f"No starter at {', '.join(empty)}."
    checks.append(RosterCheck("starters", not empty, starters))

    unpriced = int(players["salary"].isna().sum())
    salaries = "Every player has a salary."
    if unpriced:
        subject = "player has" if unpriced == 1 else "players have"
        salaries = f"{unpriced} {subject} no salary, so the payroll is understated."
    checks.append(RosterCheck("salaries", unpriced == 0, salaries))
    return tuple(checks)
