"""The team service, against a database built from the fixture store.

The fixture has every team's season and games for 1996-97, 2012-13 and 2025-26, and
player data for everyone who appeared for Boston or New York in 2025-26.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from front_office.analytics.players import BOX_METRIC_KEYS
from front_office.analytics.teams import (
    ESTIMATED_IN_A_WINDOW,
    TEAM_METRICS,
    WINDOW_METRIC_KEYS,
)
from front_office.config import Settings
from front_office.services import Lab, LabNotBuilt, TeamTable, Window

BOS, NYK, OKC, ORL = 1610612738, 1610612752, 1610612760, 1610612753
TATUM, BROWN, VUCEVIC, WHITE = 1628369, 1627759, 202696, 1628401
CALIBRATION_2025 = 0.9823337135398879


@pytest.fixture(scope="module")
def table(lab: Lab) -> TeamTable:
    return lab.teams.table("2025-26")


class TestTable:
    def test_one_row_per_team_with_every_metric(self, table: TeamTable) -> None:
        teams = table.teams
        assert teams.index.name == "team_id" and teams.index.is_unique
        assert len(teams) == 30
        assert set(TEAM_METRICS.keys) <= set(teams.columns)
        assert teams["team_name"].is_monotonic_increasing
        assert table.metrics is TEAM_METRICS
        assert (table.season, table.season_type) == ("2025-26", "regular")
        assert table.window.is_full_season

    def test_the_full_season_carries_the_leagues_published_ratings(self, table: TeamTable) -> None:
        boston = table.teams.loc[BOS]
        assert (boston["off_rating"], boston["def_rating"], boston["net_rating"]) == (
            120.0,
            111.7,
            8.3,
        )
        assert boston["pace"] == 95.58
        assert table.estimated == ()
        assert boston["win_pct"] == pytest.approx(56 / 82)
        assert boston["rel_off_rating"] == pytest.approx(120.0 - 100 * 284395 / 247827)

    def test_how_the_season_ended(self, table: TeamTable) -> None:
        assert table.teams.loc[NYK, "postseason_result"] == "Champion"
        assert table.teams.loc[BOS, "postseason_result"] == "Lost First Round"
        assert table.teams.loc[NYK, "won_championship"]

    def test_ranks_put_the_best_team_first(self, table: TeamTable) -> None:
        ranks = table.ranks
        assert ranks.index.equals(table.teams.index)
        assert list(ranks.columns) == list(TEAM_METRICS.keys)
        boston = ranks.loc[BOS]
        assert (boston["net_rating"], boston["off_rating"], boston["def_rating"]) == (4, 2, 4)
        assert boston["opp_pts_per_game"] == 1  # fewest points allowed
        assert boston["tov_pct"] == 3  # third-fewest turnovers per possession
        assert ranks.loc[table.teams["net_rating"].idxmax(), "net_rating"] == 1
        assert ranks.loc[table.teams["def_rating"].idxmin(), "def_rating"] == 1
        assert set(ranks["net_rating"]) <= set(range(1, 31))

    def test_percentiles_read_higher_is_better(self, table: TeamTable) -> None:
        percentiles = table.percentiles
        assert percentiles.index.equals(table.teams.index)
        assert list(percentiles.columns) == list(TEAM_METRICS.keys)
        stingiest = table.teams["def_rating"].idxmin()
        assert percentiles.loc[stingiest, "def_rating"] == percentiles["def_rating"].max()
        best = table.teams["net_rating"].idxmax()
        assert percentiles.loc[best, "net_rating"] == pytest.approx(100 * 29.5 / 30)
        assert percentiles["net_rating"].mean() == pytest.approx(50.0)

    def test_where_no_direction_is_better_the_highest_ranks_first(self, table: TeamTable) -> None:
        assert table.ranks.loc[table.teams["pace"].idxmax(), "pace"] == 1
        assert table.ranks.loc[BOS, "pace"] == 30  # the slowest team in the league

    def test_the_league_average_is_the_reference_line(self, table: TeamTable) -> None:
        league = table.league
        assert list(league.index) == list(TEAM_METRICS.keys)
        assert league["off_rating"] == pytest.approx(100 * 284395 / 247827)
        assert league["net_rating"] == 0 and league["win_pct"] == 0.5
        better = table.teams["off_rating"] > league["off_rating"]
        assert (table.teams.loc[better, "rel_off_rating"] > 0).all()

    def test_an_older_season(self, lab: Lab) -> None:
        old = lab.teams.table("1996-97")
        assert len(old.teams) == 29
        assert old.ranks["net_rating"].max() == 29
        bulls = old.teams[old.teams["team_name"] == "Chicago Bulls"].iloc[0]
        assert (bulls["wins"], bulls["losses"], bulls["postseason_result"]) == (69, 13, "Champion")

    def test_an_unknown_season(self, lab: Lab) -> None:
        with pytest.raises(KeyError, match="no team statistics for 2031-32"):
            lab.teams.table("2031-32")

    def test_an_unbuilt_lab_says_so(self, settings: Settings) -> None:
        with Lab(settings) as empty, pytest.raises(LabNotBuilt):
            empty.teams.table("2025-26")

    def test_metric_lookup(self, lab: Lab) -> None:
        assert lab.teams.metric("net_rating").label == "NetRtg"
        assert lab.teams.metrics is TEAM_METRICS


@pytest.fixture(scope="module")
def last(lab: Lab) -> TeamTable:
    """The last fifteen games of each team's 2025-26 season."""
    return lab.teams.table("2025-26", window=Window(last_games=15))


class TestWindow:
    def test_a_span_is_computed_from_game_box_scores(self, last: TeamTable) -> None:
        boston = last.teams.loc[BOS]
        assert (boston["games_played"], boston["wins"], boston["losses"]) == (15, 12, 3)
        assert boston["net_rating"] == pytest.approx(10.0627, abs=1e-4)
        assert boston["last_game"] == pd.Timestamp("2026-04-12")
        assert (last.teams["games_played"] == 15).all()
        assert not last.window.is_full_season

    def test_its_ratings_are_marked_as_estimates(self, last: TeamTable) -> None:
        assert last.estimated == ESTIMATED_IN_A_WINDOW
        assert last.metrics.keys == WINDOW_METRIC_KEYS
        assert "rel_off_rating" not in last.teams.columns
        assert list(last.ranks.columns) == list(WINDOW_METRIC_KEYS)
        assert list(last.percentiles.columns) == list(WINDOW_METRIC_KEYS)
        assert list(last.league.index) == list(WINDOW_METRIC_KEYS)

    def test_identity_and_outcomes_come_from_the_season(self, last: TeamTable) -> None:
        boston = last.teams.loc[BOS]
        assert (boston["team_name"], boston["conference"], boston["conference_rank"]) == (
            "Boston Celtics",
            "East",
            2,
        )
        assert boston["postseason_result"] == "Lost First Round"
        assert last.teams["team_name"].is_monotonic_increasing

    def test_counts_stay_whole_numbers(self, last: TeamTable) -> None:
        for key in ("games_played", "wins", "losses"):
            assert str(last.teams[key].dtype) == "int64", key

    def test_ranks_are_within_the_span(self, last: TeamTable, table: TeamTable) -> None:
        assert last.ranks.loc[BOS, "net_rating"] == 6
        assert table.ranks.loc[BOS, "net_rating"] == 4

    def test_a_date_range(self, lab: Lab) -> None:
        january = Window(start=date(2026, 1, 1), end=date(2026, 1, 31))
        span = lab.teams.table("2025-26", window=january)
        boston = span.teams.loc[BOS]
        assert (boston["games_played"], boston["wins"], boston["losses"]) == (16, 10, 6)
        assert span.teams["first_game"].min() >= pd.Timestamp("2026-01-01")
        assert span.teams["last_game"].max() <= pd.Timestamp("2026-01-31")

    def test_the_postseason_is_a_span_too(self, lab: Lab) -> None:
        playoffs = lab.teams.table("2025-26", "playoffs")
        assert len(playoffs.teams) == 16
        knicks = playoffs.teams.loc[NYK]
        assert (knicks["games_played"], knicks["wins"], knicks["losses"]) == (19, 16, 3)
        assert playoffs.ranks.loc[NYK, "net_rating"] == 1
        assert playoffs.estimated == ESTIMATED_IN_A_WINDOW
        assert playoffs.window.is_full_season and playoffs.season_type == "playoffs"

    def test_the_play_in(self, lab: Lab) -> None:
        play_in = lab.teams.table("2025-26", "playin")
        assert len(play_in.teams) == 8
        assert play_in.teams["games_played"].sum() == 12
        assert play_in.teams["wins"].sum() == 6

    def test_a_span_with_no_games_is_empty(self, lab: Lab) -> None:
        empty = lab.teams.table("2025-26", window=Window(start=date(2030, 1, 1)))
        assert len(empty.teams) == 0 and len(empty.ranks) == 0
        assert empty.metrics.keys == WINDOW_METRIC_KEYS


class TestProfile:
    def test_who_the_franchise_is(self, lab: Lab) -> None:
        team = lab.teams.profile(BOS).team
        assert (team["full_name"], team["abbreviation"]) == ("Boston Celtics", "BOS")
        assert (team["conference"], team["division"]) == ("East", "Atlantic")

    def test_every_season_newest_first(self, lab: Lab) -> None:
        profile = lab.teams.profile(BOS)
        seasons = profile.seasons
        assert seasons["season"].tolist() == ["2025-26", "2012-13", "1996-97"]
        assert seasons[["wins", "losses"]].values.tolist() == [[56, 26], [41, 40], [15, 67]]
        assert seasons["postseason_result"].tolist() == [
            "Lost First Round",
            "Lost First Round",
            "Missed playoffs",
        ]
        assert set(TEAM_METRICS.keys) <= set(seasons.columns)
        assert profile.metrics is TEAM_METRICS

    def test_each_season_carries_its_league_ranks(self, lab: Lab) -> None:
        seasons = lab.teams.profile(BOS).seasons.set_index("season")
        ranks = ["net_rating_rank", "off_rating_rank", "def_rating_rank"]
        assert seasons.loc["2025-26", ranks].tolist() == [4, 2, 4]
        assert seasons.loc["2012-13", ranks].tolist() == [16, 24, 7]
        assert seasons.loc["1996-97", ranks].tolist() == [27, 20, 26]
        assert seasons["league_teams"].tolist() == [30, 30, 29]

    def test_a_franchise_keeps_its_history_through_a_change_of_name(self, lab: Lab) -> None:
        wizards = lab.read("teams", {"abbreviation": "WAS"})["team_id"].iloc[0]
        seasons = lab.teams.profile(int(wizards)).seasons.set_index("season")
        assert seasons.loc["1996-97", "team_name"] == "Washington Bullets"
        assert seasons.loc["2025-26", "team_name"] == "Washington Wizards"

    def test_an_unknown_team(self, lab: Lab) -> None:
        with pytest.raises(KeyError, match="no team with id 7"):
            lab.teams.profile(7)


class TestGameLog:
    def test_newest_first_with_opponent_venue_and_result(self, lab: Lab) -> None:
        log = lab.teams.game_log(BOS, "2025-26")
        assert len(log) == 82
        assert log["game_date"].is_monotonic_decreasing
        latest = log.iloc[0]
        assert (latest["opponent"], latest["opponent_name"]) == ("ORL", "Orlando Magic")
        assert (latest["venue"], latest["result"]) == ("Home", "W 113-108")
        assert (latest["pts"], latest["opp_pts"]) == (113, 108)
        assert log["result"].str.match(r"^[WL] \d+-\d+$").all()
        assert log["result"].str.startswith("W").sum() == 56

    def test_each_game_carries_its_own_estimated_ratings(self, lab: Lab) -> None:
        """Boston 113, Orlando 108: 107.44 estimated possessions before calibration."""
        latest = lab.teams.game_log(BOS, "2025-26").iloc[0]
        possessions = 107.44 * CALIBRATION_2025
        assert latest["off_rating"] == pytest.approx(100 * 113 / possessions)
        assert latest["def_rating"] == pytest.approx(100 * 108 / possessions)
        assert latest["pace"] == pytest.approx(possessions)
        assert latest["efg_pct"] == pytest.approx((36 + 0.5 * 19) / 87)
        assert latest["point_diff_per_game"] == 5.0

    def test_results_agree_with_the_team_table(self, lab: Lab) -> None:
        log = lab.teams.game_log(BOS, "2025-26").set_index("game_id")
        games = lab.read("team_games", {"team_id": BOS, "season": "2025-26"}).set_index("game_id")
        for game_id, row in log.iterrows():
            game = games.loc[game_id]
            assert row["result"] == f"{'W' if game['won'] else 'L'} {game['pts']}-{game['opp_pts']}"
            assert row["venue"] == ("Home" if game["is_home"] else "Away")

    def test_a_neutral_site_game_is_neither_home_nor_away(self, lab: Lab) -> None:
        """New York met Orlando in Las Vegas in the in-season tournament (0022501229)."""
        log = lab.teams.game_log(NYK, "2025-26").set_index("game_id")
        cup = log.loc["0022501229"]
        assert (cup["opponent"], cup["venue"], cup["result"]) == ("ORL", "Neutral", "W 132-120")
        assert log["venue"].value_counts().to_dict() == {"Away": 41, "Home": 40, "Neutral": 1}

    def test_playoffs(self, lab: Lab) -> None:
        log = lab.teams.game_log(NYK, "2025-26", "playoffs")
        assert len(log) == 19
        assert log["result"].str.startswith("W").sum() == 16

    def test_an_older_season_has_a_game_log_too(self, lab: Lab) -> None:
        log = lab.teams.game_log(BOS, "1996-97")
        assert len(log) == 82 and log["off_rating"].notna().all()

    def test_no_games(self, lab: Lab) -> None:
        for log in (lab.teams.game_log(7, "2025-26"), lab.teams.game_log(BOS, "2031-32")):
            assert len(log) == 0
            assert {"result", "off_rating", "venue"} <= set(log.columns)


class TestRolling:
    def test_trailing_spans_oldest_first(self, lab: Lab) -> None:
        rolling = lab.teams.rolling(BOS, "2025-26", games=10)
        assert len(rolling) == 82
        assert rolling["game_date"].is_monotonic_increasing
        assert rolling["games_played"].tolist()[:11] == [*range(1, 11), 10]
        assert "team_id" not in rolling.columns
        last = rolling.iloc[-1]
        assert (last["games_played"], last["wins"]) == (10, 8)
        assert last["net_rating"] == pytest.approx(11.6102, abs=1e-4)

    def test_full_spans_start_at_the_tenth_game(self, lab: Lab) -> None:
        every = lab.teams.rolling(BOS, "2025-26", games=10)
        rolling = lab.teams.rolling(BOS, "2025-26", games=10, full_spans=True)
        assert len(rolling) == 73 and (rolling["games_played"] == 10).all()
        pd.testing.assert_frame_equal(rolling, every.iloc[9:].reset_index(drop=True))
        # Seven playoff games: there is no span of ten, and there are three of five.
        assert len(lab.teams.rolling(BOS, "2025-26", "playoffs", games=10, full_spans=True)) == 0
        assert len(lab.teams.rolling(BOS, "2025-26", "playoffs", games=5, full_spans=True)) == 3

    def test_the_last_row_matches_the_last_games_table(self, lab: Lab) -> None:
        rolling = lab.teams.rolling(BOS, "2025-26", games=15)
        span = lab.teams.table("2025-26", window=Window(last_games=15)).teams.loc[BOS]
        assert rolling.iloc[-1]["net_rating"] == pytest.approx(span["net_rating"])
        assert rolling.iloc[-1]["efg_pct"] == pytest.approx(span["efg_pct"])

    def test_no_games(self, lab: Lab) -> None:
        assert len(lab.teams.rolling(BOS, "2031-32")) == 0


class TestRotation:
    def test_most_minutes_first(self, lab: Lab) -> None:
        rotation = lab.teams.rotation(BOS, "2025-26")
        assert rotation.index.name == "player_id" and len(rotation) == 21
        assert rotation["minutes"].is_monotonic_decreasing
        leader = rotation.iloc[0]
        assert (rotation.index[0], leader["player_name"]) == (WHITE, "Derrick White")
        assert (leader["position"], leader["age"]) == ("G", 31)
        assert (leader["games_played"], leader["minutes"]) == (77, 2623)
        assert set(BOX_METRIC_KEYS) <= set(rotation.columns)

    def test_a_traded_player_shows_only_what_he_did_for_this_team(self, lab: Lab) -> None:
        """Vucevic played 64 games in 2025-26, the last 16 of them for Boston."""
        rotation = lab.teams.rotation(BOS, "2025-26")
        assert rotation.loc[VUCEVIC, "games_played"] == 16
        season = lab.players.table("2025-26").players
        assert season.loc[VUCEVIC, "games_played"] == 64

    def test_a_one_team_player_matches_his_season_line(self, lab: Lab) -> None:
        rotation = lab.teams.rotation(BOS, "2025-26")
        assert rotation.loc[TATUM, "games_played"] == 16
        assert rotation.loc[TATUM, "pts_per_game"] == pytest.approx(348 / 16)

    def test_without_a_payroll_season_there_are_no_salaries(self, lab: Lab) -> None:
        rotation = lab.teams.rotation(BOS, "2025-26")
        assert rotation[["salary", "salary_cap_pct", "years_remaining"]].isna().all().all()

    def test_with_a_payroll_season_contracts_are_joined(self, priced_lab: Lab) -> None:
        rotation = priced_lab.teams.rotation(BOS, "2025-26", payroll_season="2026-27")
        assert rotation.loc[TATUM, "salary"] == 40_000_000
        assert rotation.loc[BROWN, "salary"] == 30_000_000
        cap = priced_lab.rules("2026-27").salary_cap
        assert rotation.loc[TATUM, "salary_cap_pct"] == pytest.approx(40_000_000 / cap)
        assert pd.isna(rotation.loc[WHITE, "salary"])

    def test_playoffs(self, lab: Lab) -> None:
        rotation = lab.teams.rotation(BOS, "2025-26", "playoffs")
        assert len(rotation) == 15
        assert (rotation.loc[TATUM, "games_played"], rotation.loc[TATUM, "minutes"]) == (6, 218)

    def test_a_season_without_player_detail_is_empty(self, lab: Lab) -> None:
        rotation = lab.teams.rotation(BOS, "2012-13")
        assert len(rotation) == 0
        assert {"player_name", "minutes", "ts_pct", "salary"} <= set(rotation.columns)
        assert rotation.index.name == "player_id"
