"""The few things the simulator measures, each checked by hand on a small frame."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.eras import Era
from front_office.modeling.simulator import (
    development_bands,
    era_noise,
    missed_games,
    season_noise,
    wins_residual,
)
from front_office.modeling.simulator.measure import recent


def games_frame() -> pd.DataFrame:
    """Team 1 plays four regular-season games with margins of plus and minus ten; team 2
    one; a playoff game and an unfinished game do not count."""
    rows = []
    for number, (margin, season_type, won) in enumerate(
        [(10, "regular", True), (-10, "regular", False), (10, "regular", True), (-10, "regular", False),
         (30, "playoffs", True), (0, "regular", None)]
    ):  # fmt: skip
        rows.append(
            {
                "game_id": f"g{number}",
                "team_id": 1,
                "season": "2005-06",
                "season_type": season_type,
                "won": won,
                "pts": 100 + margin,
                "opp_pts": 100,
            }
        )
    rows.append(
        {
            "game_id": "h0",
            "team_id": 2,
            "season": "2005-06",
            "season_type": "regular",
            "won": True,
            "pts": 105,
            "opp_pts": 100,
        }
    )
    return pd.DataFrame(rows)


def teams_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": ["2005-06", "2005-06"],
            "team_id": [1, 2],
            "possessions": [400, 100],
            "games_played": [4, 1],
            "wins": [50, 30],
            "losses": [32, 52],
            "net_rating": [4.0, -4.0],
        }
    )


class TestSeasonNoise:
    def test_a_teams_noise_is_the_standard_error_of_its_margins_per_hundred_possessions(
        self,
    ) -> None:
        noise = season_noise(games_frame(), teams_frame())
        assert noise["team_id"].tolist() == [
            1
        ]  # one game is no spread; the playoff game is left out
        sd = np.std([10, -10, 10, -10], ddof=1)
        assert noise["noise"].iloc[0] == pytest.approx(sd / np.sqrt(4) * 100 / 100)
        assert noise["games"].iloc[0] == 4 and noise["season"].iloc[0] == "2005-06"

    def test_eras_average_the_seasons_they_cover(self) -> None:
        frame = pd.DataFrame(
            {"season": ["2004-05", "2005-06", "2005-06"], "team_id": [1, 1, 2], "games": 82,
             "noise": [1.0, 2.0, 4.0]}
        )  # fmt: skip
        eras = [
            Era(key="all", name="All seasons", note="x"),
            Era.between("2005-06", "2005-06"),
            Era.between("2010-11", "2011-12"),
        ]
        out = era_noise(frame, eras)
        assert [item.key for item in out] == ["all", "custom"]
        assert out[0].noise == pytest.approx((1 + 2 + 4) / 3, abs=1e-4)
        assert out[0].team_seasons == 3
        assert out[1].noise == 3.0 and out[1].first_season == out[1].last_season == "2005-06"

    def test_the_most_recent_seasons(self) -> None:
        assert recent(["2003-04", "2001-02", "2002-03", "2001-02"], 2) == ["2002-03", "2003-04"]


class TestWinsResidual:
    def test_the_spread_of_wins_around_what_the_rating_gives(self) -> None:
        teams = pd.DataFrame(
            {
                "season": ["2005-06"] * 3,
                "team_id": [1, 2, 3],
                "games_played": [82, 82, 41],
                "wins": [51, 31, 20],
                "losses": [31, 51, 21],
                "net_rating": [4.0, -4.0, 0.0],
            }
        )
        slopes = pd.Series({"2005-06": 2.5})
        residual, cases = wins_residual(teams, slopes, ["2005-06"])
        wins = np.array([51.0, 31.0, 82 * 20 / 41])
        expected = 41 + 2.5 * np.array([4.0, -4.0, 0.0])
        assert cases == 3
        assert residual == pytest.approx(np.std(wins - expected, ddof=0), abs=1e-4)
        assert wins_residual(teams, slopes, ["1999-00"]) == (0.0, 0)
        assert wins_residual(teams, pd.Series({"2004-05": 2.5}), ["2005-06"]) == (0.0, 0)


class TestDevelopmentBands:
    def test_misses_are_weighted_by_the_minutes_played_and_grouped_by_reliability(self) -> None:
        scores = pd.DataFrame(
            {
                "impact": [1.0, 3.0, 0.0, 2.0, np.nan, 1.0],
                "projected_impact": [0.0, 1.0, 1.0, 2.0, 1.0, np.nan],
                "projection_reliability": [0.2, 0.3, 0.8, 0.9, 0.5, 0.5],
                "minutes_share": [0.1, 0.3, 0.5, 0.5, 0.2, 0.2],
            }
        )
        low, high = development_bands(scores, (0.0, 0.5, 1.0))
        # Low band: misses of 1 and 2 with weights 0.1 and 0.3.
        mean = (1 * 0.1 + 2 * 0.3) / 0.4
        spread = np.sqrt(((1 - mean) ** 2 * 0.1 + (2 - mean) ** 2 * 0.3) / 0.4)
        assert (low.lower, low.upper, low.players) == (0.0, 0.5, 2)
        assert low.mean_miss == pytest.approx(mean, abs=1e-4)
        assert low.spread == pytest.approx(spread, abs=1e-4)
        # High band: misses of -1 and 0, equal weights.
        assert (high.players, high.mean_miss, high.spread) == (2, -0.5, 0.5)

    def test_a_band_with_too_few_players_is_empty_not_a_crash(self) -> None:
        scores = pd.DataFrame(
            {
                "impact": [1.0],
                "projected_impact": [0.0],
                "projection_reliability": [0.9],
                "minutes_share": [0.5],
            }
        )
        low, high = development_bands(scores, (0.0, 0.5, 1.0))
        assert (low.players, low.mean_miss, low.spread) == (0, 0.0, 0.0)
        assert (high.players, high.mean_miss, high.spread) == (1, 0.0, 0.0)


class TestMissedGames:
    def test_the_share_of_the_season_rotation_players_missed(self) -> None:
        lines = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "season": ["2005-06"] * 4,
                "season_type": ["regular", "regular", "regular", "playoffs"],
                "team_id": [1, 1, 2, 1],
                "minutes": [2000.0, 1500.0, 500.0, 2000.0],
                "games_played": [82, 41, 10, 15],
            }
        )
        teams = pd.DataFrame(
            {"season": ["2005-06", "2005-06"], "team_id": [1, 2], "games_played": [82, 82]}
        )
        missed = missed_games(lines, teams, rotation_minutes=1000, quantiles=(0.0, 0.5, 1.0))
        # Players 1 and 2 count: one missed nothing, the other half the season.
        assert missed.players == 2 and missed.mean == pytest.approx(0.25)
        assert [(q.level, q.value) for q in missed.quantiles] == [
            (0.0, 0.0),
            (0.5, 0.25),
            (1.0, 0.5),
        ]

    def test_nobody_in_the_rotation_is_an_empty_distribution(self) -> None:
        lines = pd.DataFrame(
            {"player_id": [], "season": [], "season_type": [], "team_id": [], "minutes": [],
             "games_played": []}
        )  # fmt: skip
        teams = pd.DataFrame({"season": [], "team_id": [], "games_played": []})
        missed = missed_games(lines, teams, rotation_minutes=1000, quantiles=(0.0, 1.0))
        assert missed.players == 0 and missed.mean == 0.0
        assert [q.value for q in missed.quantiles] == [0.0, 0.0]
