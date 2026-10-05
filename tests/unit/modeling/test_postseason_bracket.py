"""A playoff bracket: read from the series played, who holds home court, and every team's
chance of every round - exact, and checked against a bracket played many thousand times."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.postseason import PostseasonSpec, home_pattern
from front_office.domain.stages import ROUND_STAGE_KEYS
from front_office.modeling.postseason import (
    BracketError,
    bracket_from_series,
    head_to_head,
    holds_home_court,
    keyed,
    propagate,
    series_table,
    standard_bracket,
    team_features,
)
from tests import postseason_reference as reference
from tests.postseason_reference import PLANTED

SPEC = PostseasonSpec(formats=(), resamples=50, kept_draws=10)
SEASON = "2005-06"
PARAMETERS = (PLANTED["home_advantage"], PLANTED["net_slope"], PLANTED["top_slope"])


@pytest.fixture(scope="module")
def played(postseason_league):  # type: ignore[no-untyped-def]
    """The 2005-06 postseason as played, the teams' features, its series and the
    regular-season head-to-head record (empty: the league keeps no regular-season games)."""
    league, _, frames = postseason_league
    features = team_features(frames, SPEC)
    series = series_table(frames, features, SPEC)
    teams = keyed(features).loc[SEASON]
    pairings = head_to_head(frames["team_games"])
    return league.postseasons[2005], teams, series[series["season"] == SEASON], pairings


class TestReadingABracket:
    def test_the_bracket_is_read_from_the_series_played(self, played) -> None:  # type: ignore[no-untyped-def]
        postseason, teams, series, _ = played
        bracket = bracket_from_series(series)
        assert bracket.season == SEASON
        assert len(bracket.entrants) == 16 == len(set(bracket.entrants))
        first_round = {
            frozenset((item.team_a, item.team_b)): item
            for item in postseason.series
            if item.playoff_round == 1
        }
        semifinals = {
            frozenset((item.team_a, item.team_b))
            for item in postseason.series
            if item.playoff_round == 2
        }
        for pairs in bracket.conferences:
            assert len(pairs) == 4
            winners = []
            for pair in pairs:
                match = first_round[frozenset(pair.teams)]
                assert pair.a == match.team_a and pair.b == match.team_b and pair.best_of == 7
                winners.append(match.winner)
            # The winners of the first two pairs met, and the winners of the last two.
            assert frozenset(winners[:2]) in semifinals and frozenset(winners[2:]) in semifinals
            seeds = sorted(
                teams.at[team, "conference_rank"] for pair in pairs for team in pair.teams
            )
            assert seeds == list(range(1, 9))
        assert bracket.conference_of(bracket.entrants[0]) == 0
        assert bracket.conference_of(bracket.entrants[-1]) == 1

    def test_an_incomplete_or_mixed_season_cannot_be_read(self, played) -> None:  # type: ignore[no-untyped-def]
        _, _, series, _ = played
        with pytest.raises(BracketError, match="series in rounds 1 to 4"):
            bracket_from_series(series[series["round"] < 4])
        with pytest.raises(BracketError, match="one season"):
            bracket_from_series(pd.concat([series, series.assign(season="2006-07")]))

    def test_the_standard_bracket_seeds_one_against_eight(self) -> None:
        standings = pd.DataFrame(
            {
                "team_id": range(1, 17),
                "conference": ["East"] * 8 + ["West"] * 8,
                "seed": list(range(1, 9)) * 2,
            }
        )
        bracket = standard_bracket("2025-26", standings)
        assert [(pair.a, pair.b) for pair in bracket.conferences[0]] == [
            (1, 8),
            (4, 5),
            (3, 6),
            (2, 7),
        ]
        assert [(pair.a, pair.b) for pair in bracket.conferences[1]] == [
            (9, 16),
            (12, 13),
            (11, 14),
            (10, 15),
        ]
        assert bracket.conference_of(12) == 1
        with pytest.raises(KeyError):
            bracket.conference_of(99)
        with pytest.raises(BracketError, match="seeds 1 to 8"):
            standard_bracket("2025-26", standings[standings["seed"] < 8])
        with pytest.raises(BracketError, match="two conferences"):
            standard_bracket("2025-26", standings[standings["conference"] == "East"])


class TestHomeCourt:
    @staticmethod
    def teams() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "wins": [50, 50, 50, 45],
                "conference": ["East", "East", "West", "West"],
                "conference_rank": [1.0, 2.0, 1.0, 5.0],
                "net_rating": [5.0, 6.0, 5.0, 1.0],
            },
            index=pd.Index([1, 2, 3, 4], name="team_id"),
        )

    def test_record_then_head_to_head_then_seed_then_rating_then_id(self) -> None:
        teams, season = self.teams(), "2025-26"
        assert holds_home_court(season, 1, 4, teams, {}) and not holds_home_court(
            season, 4, 1, teams, {}
        )
        # Equal records: the head-to-head record decides, whatever the seeds say.
        pairings = {(season, 2, 1): 3, (season, 1, 2): 1}
        assert holds_home_court(season, 2, 1, teams, pairings)
        assert not holds_home_court(season, 1, 2, teams, pairings)
        # No head-to-head record: the better seed within a conference.
        assert holds_home_court(season, 1, 2, teams, {}) and not holds_home_court(
            season, 2, 1, teams, {}
        )
        # Across conferences: the better net rating, then the lower id.
        assert holds_home_court(season, 1, 3, teams, {}) and not holds_home_court(
            season, 3, 1, teams, {}
        )
        teams.at[3, "net_rating"] = 7.0
        assert holds_home_court(season, 3, 1, teams, {})


class TestPropagation:
    def test_every_round_adds_up_and_nests(self, played) -> None:  # type: ignore[no-untyped-def]
        _, teams, series, pairings = played
        bracket = bracket_from_series(series)
        odds = propagate(bracket, teams, *PARAMETERS, spec=SPEC, head_to_head=pairings)
        frame = odds.frame()
        assert list(frame.index) == list(bracket.entrants) and odds.team_ids == bracket.entrants
        for key, total in zip(ROUND_STAGE_KEYS, (8, 4, 2, 1), strict=True):
            assert frame[key].sum() == pytest.approx(total)
        assert np.all(np.diff(frame[list(ROUND_STAGE_KEYS)].to_numpy(), axis=1) <= 1e-12)
        assert ((frame > 0) & (frame < 1)).all().all()

    def test_equal_teams_without_home_court_are_coin_flips(self, played) -> None:  # type: ignore[no-untyped-def]
        _, teams, series, pairings = played
        bracket = bracket_from_series(series)
        even = teams.assign(net_rating=0.0, top_players=0.0)
        frame = propagate(bracket, even, 0.0, 0.1, 0.2, spec=SPEC, head_to_head=pairings).frame()
        for key, share in zip(ROUND_STAGE_KEYS, (0.5, 0.25, 0.125, 0.0625), strict=True):
            assert frame[key].to_numpy() == pytest.approx(share)

    def test_matches_a_bracket_played_a_hundred_thousand_times(self, played) -> None:  # type: ignore[no-untyped-def]
        _, teams, series, pairings = played
        bracket = bracket_from_series(series)
        exact = propagate(bracket, teams, *PARAMETERS, spec=SPEC, head_to_head=pairings).frame()
        hosts = {
            (mine, theirs): holds_home_court(SEASON, mine, theirs, teams, pairings)
            for mine in bracket.entrants
            for theirs in bracket.entrants
            if mine != theirs
        }
        simulated = reference.simulate_bracket(
            [[(pair.a, pair.b) for pair in pairs] for pairs in bracket.conferences],
            {
                int(team): (
                    float(teams.at[team, "net_rating"]),
                    float(teams.at[team, "top_players"]),
                )
                for team in bracket.entrants
            },
            lambda mine, theirs: hosts[(mine, theirs)],
            home_advantage=PARAMETERS[0],
            net_slope=PARAMETERS[1],
            top_slope=PARAMETERS[2],
            pattern=home_pattern("2-2-1-1-1"),
            sims=100_000,
            seed=0,
        )
        for team in bracket.entrants:
            for key in ROUND_STAGE_KEYS:
                assert exact.at[team, key] == pytest.approx(simulated[team][key], abs=0.01), (
                    team,
                    key,
                )

    def test_draws_come_back_one_column_each(self, played) -> None:  # type: ignore[no-untyped-def]
        _, teams, series, pairings = played
        bracket = bracket_from_series(series)
        odds = propagate(
            bracket,
            teams,
            np.array([PARAMETERS[0], 0.3]),
            np.array([PARAMETERS[1], 0.08]),
            np.array([PARAMETERS[2], 0.1]),
            spec=SPEC,
            head_to_head=pairings,
        )
        assert odds.by_stage["won_championship"].shape == (16, 2)
        single = propagate(bracket, teams, *PARAMETERS, spec=SPEC, head_to_head=pairings).frame()
        assert odds.frame(0)["won_championship"].to_numpy() == pytest.approx(
            single["won_championship"].to_numpy()
        )
        assert odds.frame(1)["won_championship"].sum() == pytest.approx(1.0)
        assert not np.allclose(odds.frame(0)["won_championship"], odds.frame(1)["won_championship"])

    def test_a_missing_or_unknown_entrant_is_refused(self, played) -> None:  # type: ignore[no-untyped-def]
        _, teams, series, pairings = played
        bracket = bracket_from_series(series)
        with pytest.raises(BracketError, match="no features"):
            propagate(
                bracket, teams.drop(index=bracket.entrants[0]), *PARAMETERS, spec=SPEC,
                head_to_head=pairings,
            )  # fmt: skip
        unknown = teams.copy()
        unknown.loc[bracket.entrants[1], "top_players"] = np.nan
        with pytest.raises(BracketError, match="unknown"):
            propagate(bracket, unknown, *PARAMETERS, spec=SPEC, head_to_head=pairings)
