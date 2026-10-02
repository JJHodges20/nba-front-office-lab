"""Roster indicators: what a hand-picked group of players adds up to."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from front_office.analytics.players import PLAYER_METRICS
from front_office.analytics.rosters import (
    POOLED_KEYS,
    ROSTER_METRICS,
    league_reference,
    roster_indicators,
)
from front_office.domain.metrics import MetricFormat
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS

TATUM, BROWN = 1628369, 1627759


def member(group: str | None, age: float | None = None, **totals: float) -> dict:
    """One roster member; a player with no season line has every total missing."""
    row: dict = {"position_group": group, "age": age}
    for column in ("games_played", "minutes", "plus_minus", *BOX_SCORE_COLUMNS):
        row[column] = totals.get(column, 0) if totals else None
    return row


def roster(*members: dict) -> pd.DataFrame:
    return pd.DataFrame(list(members), index=pd.Index(range(1, len(members) + 1), name="player_id"))


class TestCatalog:
    def test_composition_then_the_pooled_rates(self) -> None:
        assert ROSTER_METRICS.categories == (
            "Composition",
            "Shooting, pooled",
            "Production, pooled",
        )
        assert ROSTER_METRICS.keys[:7] == (
            "players",
            "players_with_stats",
            "guards",
            "forwards",
            "centers",
            "age",
            "minutes_share",
        )
        assert set(POOLED_KEYS) < set(ROSTER_METRICS.keys)

    def test_pooled_metrics_keep_the_player_metrics_label_and_format(self) -> None:
        for key in POOLED_KEYS:
            ours, players = ROSTER_METRICS[key], PLAYER_METRICS[key]
            assert (ours.label, ours.format, ours.decimals) == (
                players.label,
                players.format,
                players.decimals,
            ), key
            assert ours.higher_is_better == players.higher_is_better
            assert ours.description.endswith("Computed from the group's pooled totals.")

    def test_composition_has_no_better_direction(self) -> None:
        for spec in ROSTER_METRICS.in_category("Composition"):
            assert spec.higher_is_better is None, spec.key
        assert ROSTER_METRICS["minutes_share"].format is MetricFormat.PERCENT


class TestRosterIndicators:
    def test_a_worked_example(self) -> None:
        """A 30-year-old guard with 2,000 minutes and a 20-year-old center with 1,000."""
        group = roster(
            member("Guard", 30, games_played=70, minutes=2000, pts=1500, fga=1000, fgm=500,
                   fg3m=100, fg3a=300, fta=300, ftm=250, ast=400, tov=150, reb=300, stl=80,
                   blk=20),
            member("Center", 20, games_played=60, minutes=1000, pts=500, fga=300, fgm=180,
                   fg3m=0, fg3a=0, fta=200, ftm=140, ast=60, tov=50, reb=500, stl=20, blk=80),
        )  # fmt: skip
        indicators = roster_indicators(group, team_games=82)
        assert list(indicators.index) == list(ROSTER_METRICS.keys)
        assert (indicators["players"], indicators["players_with_stats"]) == (2, 2)
        assert indicators[["guards", "forwards", "centers"]].tolist() == [1, 0, 1]
        # The minutes are older than the players: (30 x 2000 + 20 x 1000) / 3000.
        assert indicators["age"] == pytest.approx(26.6667, abs=1e-4)
        assert indicators["minutes_share"] == pytest.approx(3000 / (240 * 82))
        assert indicators["ts_pct"] == pytest.approx(2000 / (2 * (1300 + 0.44 * 500)))
        assert indicators["efg_pct"] == pytest.approx((680 + 50) / 1300)
        assert indicators["fg3_pct"] == pytest.approx(100 / 300)
        assert indicators["ft_pct"] == pytest.approx(390 / 500)
        assert indicators["fg3a_rate"] == pytest.approx(300 / 1300)
        assert indicators["ft_rate"] == pytest.approx(500 / 1300)
        assert indicators["pts_per_36"] == pytest.approx(2000 * 36 / 3000)
        assert indicators["reb_per_36"] == pytest.approx(800 * 36 / 3000)
        assert indicators["ast_per_36"] == pytest.approx(460 * 36 / 3000)
        assert indicators["stl_per_36"] == pytest.approx(100 * 36 / 3000)
        assert indicators["blk_per_36"] == pytest.approx(100 * 36 / 3000)
        assert indicators["tov_pct"] == pytest.approx(200 / (1300 + 0.44 * 500 + 200))
        assert indicators["ast_to_tov"] == pytest.approx(460 / 200)

    def test_pooling_weights_by_volume_not_by_player(self) -> None:
        group = roster(
            member("Guard", 25, games_played=1, minutes=10, pts=2, fga=10, fgm=1),
            member("Guard", 25, games_played=10, minutes=300, pts=180, fga=100, fgm=90),
        )
        indicators = roster_indicators(group, team_games=82)
        assert indicators["efg_pct"] == pytest.approx(91 / 110)

    def test_a_player_without_a_season_counts_but_adds_nothing(self) -> None:
        played = member("Forward", 28, games_played=50, minutes=1500, pts=600, fga=500, fgm=220)
        alone = roster_indicators(roster(played), team_games=82)
        both = roster_indicators(roster(played, member("Center")), team_games=82)
        assert (both["players"], both["players_with_stats"]) == (2, 1)
        assert (both["forwards"], both["centers"]) == (1, 1)
        for key in ("age", "minutes_share", *POOLED_KEYS):
            assert both[key] == pytest.approx(alone[key], nan_ok=True), key

    def test_a_player_with_no_listed_position_is_in_no_group(self) -> None:
        indicators = roster_indicators(roster(member(None, 25, minutes=100)), team_games=82)
        assert indicators["players"] == 1
        assert indicators[["guards", "forwards", "centers"]].sum() == 0

    def test_more_minutes_than_a_team_has(self) -> None:
        stars = [member("Guard", 27, games_played=80, minutes=2900) for _ in range(8)]
        indicators = roster_indicators(roster(*stars), team_games=82)
        assert indicators["minutes_share"] == pytest.approx(8 * 2900 / 19680)
        assert indicators["minutes_share"] > 1

    def test_a_shorter_season_has_fewer_minutes_to_fill(self) -> None:
        group = roster(member("Guard", 27, games_played=60, minutes=2000))
        full = roster_indicators(group, team_games=82)["minutes_share"]
        short = roster_indicators(group, team_games=66)["minutes_share"]
        assert short == pytest.approx(full * 82 / 66)

    def test_an_empty_roster(self) -> None:
        indicators = roster_indicators(
            roster(member("Guard", 25, minutes=1)).iloc[0:0], team_games=82
        )
        assert indicators["players"] == 0 and indicators["minutes_share"] == 0
        assert math.isnan(indicators["age"])
        assert indicators[list(POOLED_KEYS)].isna().all()

    def test_a_roster_of_players_without_seasons(self) -> None:
        indicators = roster_indicators(roster(member("Guard"), member("Center")), team_games=82)
        assert (indicators["players"], indicators["players_with_stats"]) == (2, 0)
        assert math.isnan(indicators["age"]) and indicators["minutes_share"] == 0
        assert indicators[list(POOLED_KEYS)].isna().all()

    def test_on_real_players(self, normalized) -> None:
        seasons = normalized["player_seasons"]
        regular = seasons[seasons["season_type"] == "regular"].set_index("player_id")
        pair = regular.loc[[TATUM, BROWN]].assign(position_group=["Forward", "Guard"])
        indicators = roster_indicators(pair, team_games=82)
        points = pair["pts"].sum()
        attempts = pair["fga"].sum() + 0.44 * pair["fta"].sum()
        assert indicators["ts_pct"] == pytest.approx(points / (2 * attempts))
        assert indicators["minutes_share"] == pytest.approx(pair["minutes"].sum() / 19680)
        assert 28 < indicators["age"] < 29

    def test_the_input_is_not_modified(self, normalized) -> None:
        seasons = normalized["player_seasons"].assign(position_group="Guard")
        before = seasons.copy(deep=True)
        roster_indicators(seasons, team_games=82)
        pd.testing.assert_frame_equal(seasons, before)


class TestLeagueReference:
    def test_pooled_rates_have_a_league_value_and_composition_does_not(self, normalized) -> None:
        seasons = normalized["player_seasons"]
        regular = seasons[seasons["season_type"] == "regular"]
        reference = league_reference(regular)
        assert list(reference.index) == list(ROSTER_METRICS.keys)
        assert reference[list(POOLED_KEYS)].notna().all()
        composition = [spec.key for spec in ROSTER_METRICS.in_category("Composition")]
        assert reference[composition].isna().all()
        attempts = regular["fga"].sum() + 0.44 * regular["fta"].sum()
        assert reference["ts_pct"] == pytest.approx(regular["pts"].sum() / (2 * attempts))

    def test_no_players(self, normalized) -> None:
        reference = league_reference(normalized["player_seasons"].iloc[0:0])
        assert reference.isna().all() and len(reference) == len(ROSTER_METRICS)
