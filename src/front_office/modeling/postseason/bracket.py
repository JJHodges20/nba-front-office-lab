"""A playoff bracket: its structure, who holds home court, and the chance of every team
reaching every round, carried exactly from the series model.

A bracket is two conferences of four first-round pairs in slot order: the winners of
the first two pairs meet, and the winners of the last two, then those winners, and the
conference champions play the Finals. A team's chance of reaching a round is its chance
of being there one round earlier times the chance of beating whoever comes through the
opposing slot, summed over who that might be - exact, because the two halves of any
matchup are decided independently.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from front_office.domain.postseason import (
    CONFERENCE_FINALS,
    FINALS,
    FIRST_ROUND,
    SEMIFINALS,
    PostseasonSpec,
)
from front_office.domain.stages import ROUND_STAGE_KEYS
from front_office.modeling.postseason.features import pattern_for
from front_office.modeling.postseason.series import series_win_probability

PAIRS_PER_CONFERENCE = 4
ENTRANTS = 2 * 2 * PAIRS_PER_CONFERENCE
STANDARD_SLOTS: tuple[tuple[int, int], ...] = ((1, 8), (4, 5), (3, 6), (2, 7))
"""First-round pairs by seed in slot order: 1-8 and 4-5 feed one semifinal, 3-6 and 2-7
the other."""
HeadToHead = dict[tuple[str, int, int], int]


@dataclass(frozen=True, slots=True)
class Pair:
    """A first-round series. ``a`` holds home court."""

    a: int
    b: int
    best_of: int = 7

    @property
    def teams(self) -> tuple[int, int]:
        return (self.a, self.b)


@dataclass(frozen=True, slots=True)
class Bracket:
    season: str
    conferences: tuple[tuple[Pair, Pair, Pair, Pair], tuple[Pair, Pair, Pair, Pair]]

    @property
    def entrants(self) -> tuple[int, ...]:
        return tuple(team for pairs in self.conferences for pair in pairs for team in pair.teams)

    def conference_of(self, team: int) -> int:
        for number, pairs in enumerate(self.conferences):
            if any(team in pair.teams for pair in pairs):
                return number
        raise KeyError(f"team {team} is not in the {self.season} bracket")


class BracketError(ValueError):
    """The series on record do not form a bracket the model can read."""


def bracket_from_series(series: pd.DataFrame) -> Bracket:
    """The bracket a season's series were played in, from the first three rounds: which
    first-round winners met decides the slots. ``series`` is one season of
    :func:`front_office.modeling.postseason.features.series_table` or of
    ``playoff_results`` with ``round``, ``team_a_id``, ``team_b_id`` and ``best_of``."""
    seasons = set(series["season"].astype(str))
    if len(seasons) != 1:
        raise BracketError(f"a bracket is one season's series, not {sorted(seasons)}")
    season = seasons.pop()
    by_round = {
        number: series[series["round"] == number]
        for number in (FIRST_ROUND, SEMIFINALS, CONFERENCE_FINALS, FINALS)
    }
    counts = tuple(
        len(by_round[number]) for number in (FIRST_ROUND, SEMIFINALS, CONFERENCE_FINALS, FINALS)
    )
    if counts != (8, 4, 2, 1):
        raise BracketError(
            f"{season}: {counts} series in rounds 1 to 4; a bracket has 8, 4, 2 and 1"
        )
    first = {}
    for row in by_round[FIRST_ROUND].itertuples(index=False):
        pair = Pair(int(row.team_a_id), int(row.team_b_id), int(row.best_of))
        first[pair.a] = pair
        first[pair.b] = pair
    semifinals = []
    for row in by_round[SEMIFINALS].itertuples(index=False):
        try:
            semifinals.append((first[int(row.team_a_id)], first[int(row.team_b_id)]))
        except KeyError as error:
            raise BracketError(f"{season}: a semifinalist won no first-round series") from error
    slot_of = {}
    for number, (one, two) in enumerate(semifinals):
        for pair in (one, two):
            for team in pair.teams:
                slot_of[team] = number
    conferences = []
    for row in by_round[CONFERENCE_FINALS].itertuples(index=False):
        try:
            left, right = slot_of[int(row.team_a_id)], slot_of[int(row.team_b_id)]
        except KeyError as error:
            raise BracketError(f"{season}: a conference finalist won no semifinal") from error
        if left == right:
            raise BracketError(f"{season}: a conference final between one semifinal's teams")
        conferences.append((*semifinals[left], *semifinals[right]))
    if len({team for pairs in conferences for pair in pairs for team in pair.teams}) != ENTRANTS:
        raise BracketError(f"{season}: the conference finals do not cover sixteen distinct teams")
    return Bracket(season, (conferences[0], conferences[1]))


def standard_bracket(season: str, standings: pd.DataFrame, *, best_of: int = 7) -> Bracket:
    """The bracket the league's seeding gives: ``standings`` has one row per team with
    ``team_id``, ``conference`` and ``seed``; the eight best seeds of each of two
    conferences go in, 1 against 8, 4 against 5, 3 against 6, 2 against 7."""
    conferences = []
    for _, group in standings.groupby("conference", sort=True):
        seeded = group.set_index("seed")["team_id"]
        try:
            pairs = tuple(
                Pair(int(seeded.loc[high]), int(seeded.loc[low]), best_of)
                for high, low in STANDARD_SLOTS
            )
        except KeyError as error:
            raise BracketError(f"{season}: a conference lacks seeds 1 to 8") from error
        conferences.append(pairs)
    if len(conferences) != 2:
        raise BracketError(f"{season}: a bracket needs two conferences")
    return Bracket(season, (conferences[0], conferences[1]))


def holds_home_court(
    season: str, mine: int, theirs: int, teams: pd.DataFrame, head_to_head: HeadToHead
) -> bool:
    """Whether ``mine`` would host game 1 against ``theirs``: the better regular-season
    record, then the head-to-head record, then (in one conference) the better seed,
    then the better net rating. The league's full tie-break goes further; this reproduces
    the home court of all but a handful of series on record."""
    a, b = teams.loc[mine], teams.loc[theirs]
    if a["wins"] != b["wins"]:
        return bool(a["wins"] > b["wins"])
    mine_over = head_to_head.get((season, mine, theirs), 0)
    theirs_over = head_to_head.get((season, theirs, mine), 0)
    if mine_over != theirs_over:
        return mine_over > theirs_over
    if (
        a["conference"] == b["conference"]
        and pd.notna(a["conference_rank"])
        and pd.notna(b["conference_rank"])
    ):
        if a["conference_rank"] != b["conference_rank"]:
            return bool(a["conference_rank"] < b["conference_rank"])
    if a["net_rating"] != b["net_rating"]:
        return bool(a["net_rating"] > b["net_rating"])
    return mine < theirs


@dataclass(frozen=True, slots=True)
class BracketOdds:
    """Every entrant's chance of reaching each round, one column per parameter draw."""

    team_ids: tuple[int, ...]
    by_stage: dict[str, np.ndarray]
    """Stage key -> array of shape (entrants, draws): :data:`ROUND_STAGE_KEYS`."""

    def frame(self, column: int = 0) -> pd.DataFrame:
        """One draw's probabilities as a table indexed by team."""
        return pd.DataFrame(
            {key: values[:, column] for key, values in self.by_stage.items()},
            index=pd.Index(self.team_ids, name="team_id"),
        )


def propagate(
    bracket: Bracket,
    teams: pd.DataFrame,
    home_advantage: np.ndarray | float,
    net_slope: np.ndarray | float,
    top_slope: np.ndarray | float,
    *,
    spec: PostseasonSpec,
    head_to_head: HeadToHead,
) -> BracketOdds:
    """Carry the series model through the bracket. ``teams`` is indexed by ``team_id``
    with ``wins``, ``conference``, ``conference_rank``, ``net_rating`` and
    ``top_players`` for every entrant; the parameters may be arrays of draws."""
    season = bracket.season
    neutral = spec.is_neutral(season)
    h = np.atleast_1d(np.asarray(home_advantage, dtype="float64"))
    s_net = np.atleast_1d(np.asarray(net_slope, dtype="float64"))
    s_top = np.atleast_1d(np.asarray(top_slope, dtype="float64"))
    draws = len(h)
    missing = [team for team in bracket.entrants if team not in teams.index]
    if missing:
        raise BracketError(f"{season}: no features for teams {missing}")
    lacking = [
        team
        for team in bracket.entrants
        if not np.isfinite(teams.at[team, "net_rating"])
        or not np.isfinite(teams.at[team, "top_players"])
    ]
    if lacking:
        raise BracketError(
            f"{season}: net rating or top-player quality unknown for teams {lacking}"
        )

    def beats(
        mine: int, theirs: int, playoff_round: int, best_of: int, *, host: int | None = None
    ) -> np.ndarray:
        """P(mine beats theirs) in a series of that round. ``host`` names who holds home
        court when it is known (a first-round pair); otherwise the rule decides."""
        if host is None:
            host = mine if holds_home_court(season, mine, theirs, teams, head_to_head) else theirs
        if host != mine:
            return 1.0 - beats(theirs, mine, playoff_round, best_of, host=host)
        pattern = pattern_for(spec, playoff_round, season, best_of)
        return np.asarray(
            series_win_probability(
                h,
                s_net,
                s_top,
                float(teams.at[mine, "net_rating"] - teams.at[theirs, "net_rating"]),
                float(teams.at[mine, "top_players"] - teams.at[theirs, "top_players"]),
                pattern=pattern,
                neutral=neutral,
            ),
            dtype="float64",
        ).reshape(draws)

    reach: dict[int, dict[int, np.ndarray]] = {}  # round reached -> team -> probability
    reach[SEMIFINALS] = {}
    for pairs in bracket.conferences:
        for pair in pairs:
            p = beats(pair.a, pair.b, FIRST_ROUND, pair.best_of, host=pair.a)
            reach[SEMIFINALS][pair.a] = p
            reach[SEMIFINALS][pair.b] = 1.0 - p
    reach[CONFERENCE_FINALS] = {}
    reach[FINALS] = {}
    finalists: list[list[int]] = []
    for pairs in bracket.conferences:
        semis = ((pairs[0], pairs[1]), (pairs[2], pairs[3]))
        for one, two in semis:
            for mine_pair, other_pair in ((one, two), (two, one)):
                for team in mine_pair.teams:
                    total = np.zeros(draws)
                    for other in other_pair.teams:
                        total += reach[SEMIFINALS][other] * beats(team, other, SEMIFINALS, 7)
                    reach[CONFERENCE_FINALS][team] = reach[SEMIFINALS][team] * total
        halves = (
            [*semis[0][0].teams, *semis[0][1].teams],
            [*semis[1][0].teams, *semis[1][1].teams],
        )
        for mine_half, other_half in ((halves[0], halves[1]), (halves[1], halves[0])):
            for team in mine_half:
                total = np.zeros(draws)
                for other in other_half:
                    total += reach[CONFERENCE_FINALS][other] * beats(
                        team, other, CONFERENCE_FINALS, 7
                    )
                reach[FINALS][team] = reach[CONFERENCE_FINALS][team] * total
        finalists.append([team for pair in pairs for team in pair.teams])
    champion: dict[int, np.ndarray] = {}
    for mine_conference, other_conference in (
        (finalists[0], finalists[1]),
        (finalists[1], finalists[0]),
    ):
        for team in mine_conference:
            total = np.zeros(draws)
            for other in other_conference:
                total += reach[FINALS][other] * beats(team, other, FINALS, 7)
            champion[team] = reach[FINALS][team] * total
    order = bracket.entrants
    stacked = {
        ROUND_STAGE_KEYS[0]: np.vstack([reach[SEMIFINALS][team] for team in order]),
        ROUND_STAGE_KEYS[1]: np.vstack([reach[CONFERENCE_FINALS][team] for team in order]),
        ROUND_STAGE_KEYS[2]: np.vstack([reach[FINALS][team] for team in order]),
        ROUND_STAGE_KEYS[3]: np.vstack([champion[team] for team in order]),
    }
    return BracketOdds(order, stacked)
