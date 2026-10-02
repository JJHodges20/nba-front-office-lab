"""Team metrics, on real fixture seasons and on small hand-built ones.

The fixture holds every team's season and every game of 1996-97, 2012-13 and 2025-26.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from front_office.analytics import formulas as f
from front_office.analytics.teams import (
    ESTIMATED_IN_A_WINDOW,
    IDENTITY_COLUMNS,
    OUTCOME_COLUMNS,
    POSTSEASON_RESULTS,
    SEASON_ONLY,
    TEAM_METRICS,
    WINDOW_METRIC_KEYS,
    league_averages,
    possession_calibration,
    postseason_result,
    record_splits,
    rolling_team_metrics,
    season_over_season,
    standings,
    team_season_metrics,
    team_window_metrics,
    with_opponent_box,
)
from front_office.domain.datasets import NbaStatsDataset
from front_office.domain.schema import Provenance
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS

D = NbaStatsDataset
BOS, NYK, DET, OKC, SAS, ORL = (
    1610612738,
    1610612752,
    1610612765,
    1610612760,
    1610612759,
    1610612753,
)
SACRAMENTO = 1610612758
PUBLISHED_TO_THREE_DECIMALS = 0.00051
LAST_BOSTON_GAME = "0022501186"  # Boston 113, Orlando 108, 2026-04-12


@pytest.fixture(scope="module")
def team_seasons(normalized) -> pd.DataFrame:
    return normalized["team_seasons"]


@pytest.fixture(scope="module")
def metrics(team_seasons) -> pd.DataFrame:
    return team_season_metrics(team_seasons)


@pytest.fixture(scope="module")
def latest(metrics) -> pd.DataFrame:
    """2025-26, indexed by team."""
    return metrics[metrics["season"] == "2025-26"].set_index("team_id")


@pytest.fixture(scope="module")
def calibration(team_seasons) -> pd.Series:
    return possession_calibration(team_seasons)


@pytest.fixture(scope="module")
def games(normalized) -> pd.DataFrame:
    """Every regular-season team-game of 2025-26."""
    frame = normalized["team_games"]
    return frame[(frame["season"] == "2025-26") & (frame["season_type"] == "regular")]


def season_games(normalized, season: str, season_type: str = "regular") -> pd.DataFrame:
    frame = normalized["team_games"]
    return frame[(frame["season"] == season) & (frame["season_type"] == season_type)]


class TestCatalog:
    def test_keys_are_unique_and_every_metric_is_explained(self) -> None:
        assert len(TEAM_METRICS.keys) == len(set(TEAM_METRICS.keys))
        for spec in TEAM_METRICS:
            assert spec.description.endswith("."), spec.key
            assert len(spec.label) <= 8, spec.key

    def test_categories(self) -> None:
        assert TEAM_METRICS.categories == (
            "Record",
            "Scoring",
            "Efficiency",
            "Offense: four factors",
            "Defense: four factors",
            "Style",
        )

    def test_the_four_factors_are_there_at_both_ends(self) -> None:
        offense = [spec.key for spec in TEAM_METRICS.in_category("Offense: four factors")]
        defense = [spec.key for spec in TEAM_METRICS.in_category("Defense: four factors")]
        assert offense == ["efg_pct", "tov_pct", "oreb_pct", "ft_rate"]
        assert defense == ["opp_efg_pct", "opp_tov_pct", "dreb_pct", "opp_ft_rate"]

    def test_lower_is_better_for_what_a_team_wants_less_of(self) -> None:
        worse_when_higher = {s.key for s in TEAM_METRICS if s.higher_is_better is False}
        assert worse_when_higher == {
            "losses",
            "opp_pts_per_game",
            "def_rating",
            "tov_pct",
            "opp_efg_pct",
            "opp_ft_rate",
        }

    def test_style_metrics_have_no_better_direction(self) -> None:
        neither = {s.key for s in TEAM_METRICS if s.higher_is_better is None}
        assert neither == {"games_played", "pace", "fg3a_rate", "ast_pct"}

    def test_league_published_figures_are_tagged_measured(self) -> None:
        measured = {s.key for s in TEAM_METRICS if s.provenance is Provenance.MEASURED}
        assert measured == {
            "games_played",
            "wins",
            "losses",
            "off_rating",
            "def_rating",
            "net_rating",
            "pace",
        }

    def test_a_span_of_games_has_everything_but_the_league_relative_ratings(self) -> None:
        assert SEASON_ONLY == ("rel_off_rating", "rel_def_rating")
        assert set(WINDOW_METRIC_KEYS) == set(TEAM_METRICS.keys) - set(SEASON_ONLY)
        assert set(ESTIMATED_IN_A_WINDOW) < set(WINDOW_METRIC_KEYS)
        assert {"off_rating", "def_rating", "net_rating", "pace"} <= set(ESTIMATED_IN_A_WINDOW)


class TestSeasonMetrics:
    def test_one_row_per_team_season_with_every_metric(self, metrics, team_seasons) -> None:
        assert len(metrics) == len(team_seasons) == 89
        assert tuple(metrics.columns) == (*IDENTITY_COLUMNS, *TEAM_METRICS.keys, *OUTCOME_COLUMNS)
        assert not metrics.duplicated(["season", "team_id"]).any()
        assert metrics[list(TEAM_METRICS.keys)].notna().all().all()

    def test_a_real_line(self, latest) -> None:
        """Boston, 2025-26: 56-26, 9,418 points scored and 8,787 allowed on 7,850 possessions."""
        boston = latest.loc[BOS]
        assert (boston["team_name"], boston["conference"]) == ("Boston Celtics", "East")
        assert (boston["games_played"], boston["wins"], boston["losses"]) == (82, 56, 26)
        assert boston["win_pct"] == pytest.approx(56 / 82)
        assert boston["pts_per_game"] == pytest.approx(9418 / 82)
        assert boston["opp_pts_per_game"] == pytest.approx(8787 / 82)
        assert boston["point_diff_per_game"] == pytest.approx((9418 - 8787) / 82)
        assert boston["ts_pct"] == pytest.approx(9418 / (2 * (7398 + 0.44 * 1534)))
        assert boston["efg_pct"] == pytest.approx((3456 + 0.5 * 1268) / 7398)
        assert boston["tov_pct"] == pytest.approx(1014 / 7850)
        assert boston["oreb_pct"] == pytest.approx(1025 / (1025 + 2489))
        assert boston["ft_rate"] == pytest.approx(1534 / 7398)
        assert boston["opp_efg_pct"] == pytest.approx((3145 + 0.5 * 1149) / 7115)
        assert boston["opp_tov_pct"] == pytest.approx(1018 / 7850)
        assert boston["dreb_pct"] == pytest.approx(2777 / (2777 + 890))
        assert boston["opp_ft_rate"] == pytest.approx(1740 / 7115)
        assert boston["fg3a_rate"] == pytest.approx(3456 / 7398)
        assert boston["fg3_pct"] == pytest.approx(1268 / 3456)
        assert boston["ast_pct"] == pytest.approx(2021 / 3456)

    def test_ratings_and_pace_are_the_leagues_published_figures(
        self, metrics, team_seasons
    ) -> None:
        for key in ("off_rating", "def_rating", "net_rating", "pace"):
            pd.testing.assert_series_equal(
                metrics[key], team_seasons[key].reset_index(drop=True), check_names=False, obj=key
            )
        boston = metrics[(metrics["team_id"] == BOS) & (metrics["season"] == "2025-26")].iloc[0]
        assert (boston["off_rating"], boston["def_rating"], boston["net_rating"]) == (
            120.0,
            111.7,
            8.3,
        )
        assert boston["pace"] == 95.58

    def test_relative_ratings_compare_with_the_league_that_season(self, latest) -> None:
        """The league scored 284,395 points on 247,827 possessions in 2025-26."""
        league = 100 * 284395 / 247827
        assert league == pytest.approx(114.755, abs=0.001)
        boston = latest.loc[BOS]
        assert boston["rel_off_rating"] == pytest.approx(120.0 - league)
        assert boston["rel_def_rating"] == pytest.approx(league - 111.7)

    def test_a_good_defense_has_a_positive_relative_defensive_rating(self, latest) -> None:
        stingiest = latest["def_rating"].idxmin()
        leakiest = latest["def_rating"].idxmax()
        assert latest.loc[stingiest, "rel_def_rating"] > 5
        assert latest.loc[leakiest, "rel_def_rating"] < -3
        assert latest["rel_def_rating"].idxmax() == stingiest

    def test_relative_ratings_use_each_seasons_own_league_average(self, metrics) -> None:
        """An average offense of 1996-97 would be a dreadful one in 2025-26."""
        for _, season in metrics.groupby("season"):
            assert abs(season["rel_off_rating"].mean()) < 0.2
            assert abs(season["rel_def_rating"].mean()) < 0.2
        gap = metrics["off_rating"] - metrics["rel_off_rating"]
        by_season = gap.groupby(metrics["season"]).mean()
        assert by_season["2025-26"] - by_season["1996-97"] == pytest.approx(9.73, abs=0.01)

    def test_outcomes_pass_through(self, latest) -> None:
        knicks = latest.loc[NYK]
        assert knicks["won_championship"] and knicks["playoff_round_reached"] == 4
        assert (knicks["playoff_wins"], knicks["playoff_losses"]) == (16, 3)
        assert not latest.loc[BOS, "won_championship"]

    def test_metrics_stay_within_sensible_bounds(self, metrics) -> None:
        for key in ("win_pct", "efg_pct", "tov_pct", "oreb_pct", "dreb_pct", "fg3_pct", "ast_pct"):
            assert ((metrics[key] > 0) & (metrics[key] < 1)).all(), key
        assert metrics["off_rating"].between(90, 130).all()
        assert metrics["pace"].between(80, 110).all()
        assert not np.isinf(metrics[list(TEAM_METRICS.keys)].to_numpy(dtype="float64")).any()

    def test_an_empty_table_gives_an_empty_frame_with_every_column(self, team_seasons) -> None:
        empty = team_season_metrics(team_seasons.iloc[0:0])
        assert len(empty) == 0
        assert tuple(empty.columns) == (*IDENTITY_COLUMNS, *TEAM_METRICS.keys, *OUTCOME_COLUMNS)

    def test_the_input_frame_is_not_modified(self, team_seasons) -> None:
        before = team_seasons.copy(deep=True)
        team_season_metrics(team_seasons)
        pd.testing.assert_frame_equal(team_seasons, before)

    def test_a_team_that_has_not_played_has_no_rates(self, team_seasons) -> None:
        season = team_seasons[team_seasons["season"] == "2025-26"].copy()
        numeric = ["games_played", "wins", "losses", "possessions", "minutes"]
        numeric += [*BOX_SCORE_COLUMNS, *(f"opp_{column}" for column in BOX_SCORE_COLUMNS)]
        season.loc[season["team_id"] == BOS, numeric] = 0
        boston = team_season_metrics(season).set_index("team_id").loc[BOS]
        for key in ("win_pct", "pts_per_game", "efg_pct", "tov_pct", "oreb_pct", "ast_pct"):
            assert math.isnan(boston[key]), key


class TestAgainstTheLeague:
    """Where the league publishes the same quantity, ours must be the league's figure."""

    @staticmethod
    def published(raw, season: int) -> pd.DataFrame:
        snapshot = raw(D.TEAM_SEASON_ADVANCED, Season(season), SeasonType.REGULAR)
        result_set = snapshot.payload["resultSets"][0]
        frame = pd.DataFrame(result_set["rowSet"], columns=result_set["headers"])
        return frame.set_index("TEAM_ID")

    @pytest.mark.parametrize("season", [1996, 2012, 2025])
    def test_turnover_rate_and_assist_percentage(self, raw, metrics, season: int) -> None:
        published = self.published(raw, season)
        ours = metrics[metrics["season"] == Season(season).label].set_index("team_id")
        ours = ours.reindex(published.index)
        assert (ours["tov_pct"] - published["TM_TOV_PCT"]).abs().max() < PUBLISHED_TO_THREE_DECIMALS
        assert (ours["efg_pct"] - published["EFG_PCT"]).abs().max() < PUBLISHED_TO_THREE_DECIMALS
        assert (ours["ts_pct"] - published["TS_PCT"]).abs().max() < PUBLISHED_TO_THREE_DECIMALS
        assist_gap = (ours["ast_pct"] - published["AST_PCT"]).abs()
        off = assist_gap[assist_gap >= PUBLISHED_TO_THREE_DECIMALS]
        # The league's own 1996-97 Sacramento figures disagree with each other
        # (docs/decisions/0003-source-quirks.md): 1,799 assists on 3,000 field goals
        # is 0.600, and it publishes 0.598.
        assert off.index.tolist() == ([SACRAMENTO] if season == 1996 else [])

    @pytest.mark.parametrize("season", [2012, 2025])
    def test_pace_follows_from_possessions_and_minutes(self, raw, team_seasons, season) -> None:
        """Our pace formula on the league's possessions and minutes is the league's pace."""
        rows = team_seasons[team_seasons["season"] == Season(season).label]
        ours = f.pace(rows["possessions"], rows["minutes"])
        assert (ours - rows["pace"]).abs().max() < 0.2

    def test_the_leagues_rebound_percentage_is_a_different_quantity(self, raw, latest) -> None:
        """Ours is the four-factors definition; the league's runs several points higher."""
        published = self.published(raw, 2025)["OREB_PCT"]
        gap = published - latest["oreb_pct"].reindex(published.index)
        assert gap.min() > 0.02


class TestLeagueAverages:
    def test_one_row_per_season_with_every_metric(self, team_seasons) -> None:
        league = league_averages(team_seasons)
        assert league.index.tolist() == ["1996-97", "2012-13", "2025-26"]
        assert list(league.columns) == ["teams", *TEAM_METRICS.keys]
        assert league["teams"].tolist() == [29, 30, 30]

    def test_the_league_is_pooled_not_averaged_over_teams(self, team_seasons) -> None:
        league = league_averages(team_seasons).loc["2025-26"]
        assert league["off_rating"] == pytest.approx(100 * 284395 / 247827)
        assert league["pace"] == pytest.approx(48 * 247827 / 118699.906666)
        assert league["pts_per_game"] == pytest.approx(284395 / 2460)
        assert league["efg_pct"] == pytest.approx((103227 + 0.5 * 32717) / 219160)
        assert league["fg3a_rate"] == pytest.approx(90970 / 219160)
        assert league["oreb_pct"] == pytest.approx(27989 / (27989 + 79683))
        assert league["tov_pct"] == pytest.approx(35695 / 247827)

    def test_every_point_scored_is_a_point_allowed(self, team_seasons) -> None:
        league = league_averages(team_seasons)
        assert (league["off_rating"] == league["def_rating"]).all()
        assert (league["net_rating"] == 0).all()
        assert (league["point_diff_per_game"] == 0).all()
        assert (league["rel_off_rating"] == 0).all() and (league["rel_def_rating"] == 0).all()
        assert (league["win_pct"] == 0.5).all()

    def test_the_two_ends_of_the_floor_mirror_each_other(self, team_seasons) -> None:
        league = league_averages(team_seasons)
        assert (league["oreb_pct"] + league["dreb_pct"]).tolist() == pytest.approx([1, 1, 1])
        assert league["opp_efg_pct"].tolist() == pytest.approx(league["efg_pct"].tolist(), abs=1e-4)

    def test_counts_are_per_team(self, team_seasons) -> None:
        league = league_averages(team_seasons)
        assert league.loc["2025-26", ["games_played", "wins", "losses"]].tolist() == [82, 41, 41]
        # One game of 2012-13 was cancelled and never replayed.
        assert league.loc["2012-13", "games_played"] == pytest.approx(2458 / 30)

    def test_the_game_changed(self, team_seasons) -> None:
        league = league_averages(team_seasons)
        assert league["fg3a_rate"].is_monotonic_increasing
        assert league.loc["2025-26", "fg3a_rate"] > 2 * league.loc["1996-97", "fg3a_rate"] * 0.95
        assert league.loc["2025-26", "pace"] > league.loc["1996-97", "pace"] + 8


class TestStandings:
    def test_conference_order_with_games_behind(self, metrics) -> None:
        table = standings(metrics[metrics["season"] == "2025-26"])
        assert len(table) == 30
        assert table["conference"].tolist() == ["East"] * 15 + ["West"] * 15
        assert table["conference_rank"].tolist() == [*range(1, 16), *range(1, 16)]
        rows = table.set_index("team_id")
        assert rows.loc[[DET, OKC], "games_behind"].tolist() == [0.0, 0.0]
        assert rows.loc[BOS, "games_behind"] == 4.0  # 56-26 behind 60-22
        assert rows.loc[NYK, "games_behind"] == 7.0
        assert rows.loc[SAS, "games_behind"] == 2.0  # 62-20 behind 64-18

    def test_games_behind_counts_wins_and_losses_equally(self) -> None:
        """41-39 trails 45-37 by three games: four wins fewer and two losses more."""
        frame = pd.DataFrame(
            {
                "season": "2025-26",
                "conference": "East",
                "conference_rank": [1, 2],
                "team_name": ["A", "B"],
                "wins": [45, 41],
                "losses": [37, 39],
            }
        )
        assert standings(frame)["games_behind"].tolist() == [0.0, 3.0]

    def test_teams_level_with_the_leader_are_zero_games_behind(self, metrics) -> None:
        table = standings(metrics[metrics["season"] == "1996-97"])
        east = table[table["conference"] == "East"]
        # Charlotte and Detroit both finished 54-28 and share fifth place.
        tied = east[east["conference_rank"] == 5]
        assert tied["team_name"].tolist() == ["Charlotte Hornets", "Detroit Pistons"]
        assert tied["games_behind"].tolist() == [15.0, 15.0]
        assert (table["games_behind"] >= 0).all()

    def test_one_season_at_a_time(self, metrics) -> None:
        with pytest.raises(ValueError, match="one season"):
            standings(metrics)

    def test_the_input_is_not_modified(self, metrics) -> None:
        season = metrics[metrics["season"] == "2025-26"]
        before = season.copy(deep=True)
        standings(season)
        pd.testing.assert_frame_equal(season, before)


class TestPostseasonResult:
    def test_every_way_a_season_can_end(self, metrics) -> None:
        results = postseason_result(metrics)
        assert results.value_counts().to_dict() == {
            "Missed playoffs": 37,
            "Lost First Round": 24,
            "Lost Conference Semifinals": 12,
            "Lost Conference Finals": 6,
            "Lost Play-In": 4,
            "Champion": 3,
            "Lost NBA Finals": 3,
        }
        assert set(results) == set(POSTSEASON_RESULTS)

    def test_results_are_listed_best_first(self) -> None:
        assert POSTSEASON_RESULTS == (
            "Champion",
            "Lost NBA Finals",
            "Lost Conference Finals",
            "Lost Conference Semifinals",
            "Lost First Round",
            "Lost Play-In",
            "Missed playoffs",
        )

    def test_real_seasons(self, latest) -> None:
        results = postseason_result(latest)
        assert results.loc[NYK] == "Champion"
        assert results.loc[SAS] == "Lost NBA Finals"
        assert results.loc[BOS] == "Lost First Round"

    def test_a_play_in_team_that_advanced_is_judged_by_its_playoff_run(self, latest) -> None:
        through = latest[latest["made_play_in"] & latest["made_playoffs"]]
        assert len(through) == 4
        assert postseason_result(through).str.startswith("Lost").all()
        assert "Lost Play-In" not in set(postseason_result(through))
        out = latest[latest["made_play_in"] & ~latest["made_playoffs"]]
        assert set(postseason_result(out)) == {"Lost Play-In"}

    def test_an_undecided_season_has_no_result(self, latest) -> None:
        pending = latest.copy()
        pending[list(OUTCOME_COLUMNS)] = pd.NA
        assert postseason_result(pending).isna().all()


class TestRecordSplits:
    def test_home_road_recent_and_streak(self, games) -> None:
        splits = record_splits(games)
        assert len(splits) == 30
        assert splits.loc[BOS].tolist() == [30, 11, 26, 15, 8, 2, 2]
        assert list(splits.columns) == [
            "home_wins",
            "home_losses",
            "road_wins",
            "road_losses",
            "recent_wins",
            "recent_losses",
            "streak",
        ]

    def test_a_neutral_site_game_is_neither_home_nor_road(self, games, latest) -> None:
        """New York went 53-29 with one win in Las Vegas: 30-10 at home, 22-19 away."""
        knicks = record_splits(games).loc[NYK]
        assert knicks[["home_wins", "home_losses", "road_wins", "road_losses"]].tolist() == [
            30,
            10,
            22,
            19,
        ]
        assert knicks[["home_wins", "road_wins"]].sum() == latest.loc[NYK, "wins"] - 1

    def test_everything_else_adds_up_to_the_record(self, games, latest) -> None:
        splits = record_splits(games)
        neutral = games[games["is_neutral_site"]].groupby("team_id")["won"].agg(["sum", "size"])
        wins = splits["home_wins"] + splits["road_wins"]
        wins = wins.add(neutral["sum"], fill_value=0)
        assert (wins == latest["wins"].reindex(wins.index)).all()

    def test_a_losing_streak_is_negative(self, games) -> None:
        assert record_splits(games).loc[NYK, "streak"] == -1
        assert record_splits(games).loc[NYK, ["recent_wins", "recent_losses"]].tolist() == [6, 4]

    def test_recent_span_is_adjustable(self, games) -> None:
        splits = record_splits(games, recent=3)
        assert splits.loc[BOS, ["recent_wins", "recent_losses"]].tolist() == [2, 1]
        assert (splits["recent_wins"] + splits["recent_losses"] == 3).all()

    def test_streaks_by_hand(self) -> None:
        def game(number: int, team: int, won: bool) -> dict:
            return {
                "game_id": f"{number:03d}",
                "team_id": team,
                "game_date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=number),
                "is_home": True,
                "is_neutral_site": False,
                "won": won,
            }

        results = {1: [True, False, True, True, True], 2: [True, True, False], 3: [False]}
        rows = [
            game(number, team, won)
            for team, outcomes in results.items()
            for number, won in enumerate(outcomes)
        ]
        # Order in the frame must not matter: the streak follows the dates.
        frame = pd.DataFrame(rows).sample(frac=1, random_state=3)
        frame["won"] = frame["won"].astype("boolean")
        splits = record_splits(frame)
        assert splits["streak"].to_dict() == {1: 3, 2: -1, 3: -1}
        assert splits["home_wins"].to_dict() == {1: 4, 2: 2, 3: 0}

    def test_unfinished_games_are_ignored(self, games) -> None:
        pending = games.copy()
        pending.loc[pending["game_id"] == LAST_BOSTON_GAME, "won"] = pd.NA
        splits = record_splits(pending)
        assert splits.loc[BOS, ["home_wins", "home_losses"]].tolist() == [29, 11]
        assert splits.loc[BOS, "streak"] == 1

    def test_no_games(self, games) -> None:
        splits = record_splits(games.iloc[0:0])
        assert len(splits) == 0 and "streak" in splits.columns

    def test_the_recent_span_must_be_at_least_one_game(self, games) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            record_splits(games, recent=0)


class TestPossessionCalibration:
    def test_scales_the_leagues_estimate_to_its_count(self, team_seasons, calibration) -> None:
        assert calibration.index.tolist() == ["1996-97", "2012-13", "2025-26"]
        season = team_seasons[team_seasons["season"] == "2025-26"]
        own = f.estimated_possessions(season["fga"], season["fta"], season["oreb"], season["tov"])
        opponent = f.estimated_possessions(
            season["opp_fga"], season["opp_fta"], season["opp_oreb"], season["opp_tov"]
        )
        expected = season["possessions"].sum() / ((own + opponent) / 2).sum()
        assert calibration["2025-26"] == pytest.approx(expected)
        assert calibration["2025-26"] == pytest.approx(0.98233, abs=1e-5)

    def test_the_estimate_runs_high_by_one_to_two_percent(self, calibration) -> None:
        assert calibration.between(0.975, 0.995).all()

    def test_a_season_without_possessions_has_no_factor(self, team_seasons) -> None:
        season = team_seasons[team_seasons["season"] == "2025-26"].copy()
        for column in ("fga", "fta", "oreb", "tov", "opp_fga", "opp_fta", "opp_oreb", "opp_tov"):
            season[column] = 0
        assert math.isnan(possession_calibration(season)["2025-26"])


class TestOpponentBox:
    def test_each_row_gains_the_other_teams_box_score(self, games) -> None:
        paired = with_opponent_box(games)
        assert len(paired) == len(games)
        row = paired[(paired["game_id"] == LAST_BOSTON_GAME) & (paired["team_id"] == BOS)].iloc[0]
        assert (row["pts"], row["opp_pts"]) == (113, 108)
        assert (row["opp_fga"], row["opp_fta"], row["opp_oreb"], row["opp_tov"]) == (91, 30, 14, 19)
        assert row["opponent_team_id"] == ORL

    def test_the_opponents_points_agree_with_the_stored_column(self, games) -> None:
        paired = with_opponent_box(games).set_index(["game_id", "team_id"])
        stored = games.set_index(["game_id", "team_id"])["opp_pts"]
        assert (paired["opp_pts"] == stored.reindex(paired.index)).all()

    def test_a_game_with_one_row_is_an_error(self, games) -> None:
        lonely = games[~((games["game_id"] == LAST_BOSTON_GAME) & (games["team_id"] == ORL))]
        with pytest.raises(ValueError, match=f"without the opponent's row.*{LAST_BOSTON_GAME}"):
            with_opponent_box(lonely)


class TestWindowMetrics:
    def test_a_single_game_by_hand(self, games, calibration) -> None:
        """Boston 113, Orlando 108 in regulation.

        Boston: 87 FGA, 22 FTA, 8 OREB, 17 TOV -> 105.68 estimated possessions.
        Orlando: 91 FGA, 30 FTA, 14 OREB, 19 TOV -> 109.20. Their mean is 107.44.
        """
        possessions = 107.44 * calibration["2025-26"]
        window = team_window_metrics(games, calibration, last_games=1).loc[BOS]
        assert (window["games_played"], window["wins"], window["losses"]) == (1, 1, 0)
        assert window["first_game"] == window["last_game"] == pd.Timestamp("2026-04-12")
        assert window["off_rating"] == pytest.approx(100 * 113 / possessions)
        assert window["def_rating"] == pytest.approx(100 * 108 / possessions)
        assert window["net_rating"] == pytest.approx(100 * 5 / possessions)
        assert window["pace"] == pytest.approx(possessions)  # 48 minutes of game time
        assert window["tov_pct"] == pytest.approx(17 / possessions)
        assert window["opp_tov_pct"] == pytest.approx(19 / possessions)
        assert window["efg_pct"] == pytest.approx((36 + 0.5 * 19) / 87)
        assert window["oreb_pct"] == pytest.approx(8 / (8 + 36))
        assert window["dreb_pct"] == pytest.approx(38 / (38 + 14))
        assert window["ft_rate"] == pytest.approx(22 / 87)
        assert window["opp_ft_rate"] == pytest.approx(30 / 91)
        assert window["point_diff_per_game"] == 5.0

    def test_without_calibration_possessions_are_the_raw_estimate(self, games) -> None:
        window = team_window_metrics(games, last_games=1).loc[BOS]
        assert window["off_rating"] == pytest.approx(100 * 113 / 107.44)
        assert window["pace"] == pytest.approx(107.44)

    def test_both_teams_of_a_game_share_its_possessions(self, games, calibration) -> None:
        single = games[games["game_id"] == LAST_BOSTON_GAME]
        window = team_window_metrics(single, calibration)
        assert window.loc[BOS, "pace"] == pytest.approx(window.loc[ORL, "pace"])
        assert window.loc[BOS, "off_rating"] == pytest.approx(window.loc[ORL, "def_rating"])
        assert window.loc[BOS, "net_rating"] == pytest.approx(-window.loc[ORL, "net_rating"])

    def test_columns(self, games, calibration) -> None:
        window = team_window_metrics(games, calibration, last_games=10)
        assert window.index.name == "team_id" and len(window) == 30
        assert list(window.columns) == ["first_game", "last_game", *WINDOW_METRIC_KEYS]
        assert "rel_off_rating" not in window.columns

    def test_the_whole_season_reproduces_the_record_and_box_score_rates(
        self, games, calibration, latest
    ) -> None:
        window = team_window_metrics(games, calibration)
        season = latest.reindex(window.index)
        for key in ("games_played", "wins", "losses"):
            assert (window[key] == season[key]).all(), key
        for key in ("pts_per_game", "opp_pts_per_game", "efg_pct", "opp_efg_pct", "ft_rate",
                    "fg3a_rate", "fg3_pct", "ast_pct", "ts_pct"):  # fmt: skip
            assert (window[key] - season[key]).abs().max() < 1e-3, key
        # The season table's opponent rebounds come from another endpoint and differ by a few.
        assert (window["oreb_pct"] - season["oreb_pct"]).abs().max() < 2e-3

    @pytest.mark.parametrize("season", ["1996-97", "2012-13", "2025-26"])
    def test_estimated_ratings_track_the_leagues_published_ones(
        self, normalized, metrics, calibration, season: str
    ) -> None:
        """Over a whole season the estimate is the test of the estimator."""
        window = team_window_metrics(season_games(normalized, season), calibration)
        published = metrics[metrics["season"] == season].set_index("team_id").reindex(window.index)
        for key, mean_error, worst_error in (
            ("off_rating", 0.35, 1.0),
            ("def_rating", 0.35, 1.0),
            ("net_rating", 0.25, 0.8),
            ("pace", 0.30, 0.8),
        ):
            error = (window[key] - published[key]).abs()
            assert error.mean() < mean_error, key
            assert error.max() < worst_error, key

    def test_calibration_removes_the_bias_of_the_raw_estimate(
        self, games, calibration, latest
    ) -> None:
        published = latest["off_rating"]
        raw_bias = (team_window_metrics(games)["off_rating"] - published).mean()
        calibrated_bias = (team_window_metrics(games, calibration)["off_rating"] - published).mean()
        assert raw_bias < -1.5  # too many possessions, so ratings come out too low
        assert abs(calibrated_bias) < 0.1

    def test_last_games_takes_each_teams_most_recent(self, games, calibration) -> None:
        window = team_window_metrics(games, calibration, last_games=3).loc[BOS]
        assert (window["games_played"], window["wins"], window["losses"]) == (3, 2, 1)
        assert window["pts_per_game"] == pytest.approx((106 + 144 + 113) / 3)
        assert window["opp_pts_per_game"] == pytest.approx((112 + 118 + 108) / 3)
        assert window["first_game"] == pd.Timestamp("2026-04-09")
        assert window["last_game"] == pd.Timestamp("2026-04-12")

    def test_a_date_range(self, games, calibration) -> None:
        start, end = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-31")
        window = team_window_metrics(games, calibration, start=start, end=end)
        january = games[(games["game_date"] >= start) & (games["game_date"] <= end)]
        assert window["games_played"].sum() == len(january)
        assert window["first_game"].min() >= start and window["last_game"].max() <= end
        assert window["wins"].sum() == window["losses"].sum() == len(january) / 2

    def test_date_range_then_last_games(self, games, calibration) -> None:
        end = pd.Timestamp("2026-01-31")
        window = team_window_metrics(games, calibration, end=end, last_games=5)
        assert (window["games_played"] == 5).all()
        assert window["last_game"].max() <= end

    def test_the_league_nets_out_to_zero_over_any_span(self, games, calibration) -> None:
        window = team_window_metrics(games, calibration, start=pd.Timestamp("2026-03-01"))
        assert window["point_diff_per_game"].mul(window["games_played"]).sum() == pytest.approx(0)

    def test_playoffs(self, normalized, calibration) -> None:
        playoffs = season_games(normalized, "2025-26", "playoffs")
        window = team_window_metrics(playoffs, calibration)
        assert len(window) == 16
        assert window.loc[NYK, ["games_played", "wins", "losses"]].tolist() == [19, 16, 3]
        assert window.loc[BOS, ["games_played", "wins", "losses"]].tolist() == [7, 3, 4]
        assert window.loc[NYK, "net_rating"] > 10

    def test_overtime_counts_toward_pace(self, games, calibration) -> None:
        overtime = games[games["minutes"] > 240]
        game_id = overtime["game_id"].iloc[0]
        single = games[games["game_id"] == game_id]
        team = int(single["team_id"].iloc[0])
        window = team_window_metrics(single, calibration).loc[team]
        game_minutes = single["minutes"].iloc[0] / 5
        own = f.estimated_possessions(single["fga"], single["fta"], single["oreb"], single["tov"])
        possessions = own.mean() * calibration["2025-26"]
        assert game_minutes > 48
        assert window["pace"] == pytest.approx(48 * possessions / game_minutes)

    def test_unfinished_games_are_left_out(self, games, calibration) -> None:
        pending = games.copy()
        pending.loc[pending["game_id"] == LAST_BOSTON_GAME, "won"] = pd.NA
        window = team_window_metrics(pending, calibration)
        assert window.loc[BOS, "games_played"] == 81
        assert window.loc[ORL, "games_played"] == 81
        assert window.loc[NYK, "games_played"] == 82

    def test_a_season_the_calibration_does_not_cover_has_no_ratings(
        self, games, calibration
    ) -> None:
        window = team_window_metrics(games, calibration.drop("2025-26"), last_games=5)
        for key in ESTIMATED_IN_A_WINDOW:
            assert window[key].isna().all(), key
        assert window["efg_pct"].notna().all()
        assert (window["games_played"] == 5).all()

    def test_no_games(self, games, calibration) -> None:
        window = team_window_metrics(games.iloc[0:0], calibration)
        assert len(window) == 0
        assert list(window.columns) == ["first_game", "last_game", *WINDOW_METRIC_KEYS]
        late = team_window_metrics(games, calibration, start=pd.Timestamp("2030-01-01"))
        assert len(late) == 0

    def test_a_window_must_be_at_least_one_game(self, games) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            team_window_metrics(games, last_games=0)

    def test_the_input_frame_is_not_modified(self, games, calibration) -> None:
        before = games.copy(deep=True)
        team_window_metrics(games, calibration, last_games=4)
        pd.testing.assert_frame_equal(games, before)


class TestRolling:
    def test_one_row_per_game_in_playing_order(self, games, calibration) -> None:
        rolling = rolling_team_metrics(games, calibration, games=5)
        assert len(rolling) == len(games)
        assert list(rolling.columns) == ["team_id", "game_id", "game_date", *WINDOW_METRIC_KEYS]
        boston = rolling[rolling["team_id"] == BOS]
        assert len(boston) == 82 and boston["game_date"].is_monotonic_increasing
        assert boston["games_played"].tolist()[:6] == [1, 2, 3, 4, 5, 5]
        assert boston["games_played"].max() == 5

    def test_the_last_row_is_the_last_window(self, games, calibration) -> None:
        rolling = rolling_team_metrics(games, calibration, games=10)
        window = team_window_metrics(games, calibration, last_games=10)
        last = rolling.groupby("team_id").tail(1).set_index("team_id")
        for key in ("wins", "net_rating", "off_rating", "pace", "efg_pct", "oreb_pct"):
            pd.testing.assert_series_equal(
                last[key], window[key], check_names=False, check_dtype=False, obj=key
            )

    def test_the_first_row_is_the_first_game_alone(self, games, calibration) -> None:
        rolling = rolling_team_metrics(games, calibration, games=10)
        first = rolling[rolling["team_id"] == BOS].iloc[0]
        opener = games[games["team_id"] == BOS].sort_values("game_date").iloc[0]
        assert first["game_id"] == opener["game_id"]
        assert first["pts_per_game"] == opener["pts"]
        assert first["wins"] == int(opener["won"])

    def test_full_spans_leave_out_the_early_games(self, games, calibration) -> None:
        every = rolling_team_metrics(games, calibration, games=10)
        full = rolling_team_metrics(games, calibration, games=10, full_spans=True)
        assert (full["games_played"] == 10).all()
        # What is kept is unchanged: the same rows, without each team's first nine.
        kept = every[every["games_played"] == 10].reset_index(drop=True)
        pd.testing.assert_frame_equal(full, kept)
        boston = full[full["team_id"] == BOS]
        assert len(boston) == 82 - 9
        opening = games[games["team_id"] == BOS].sort_values(["game_date", "game_id"]).head(10)
        assert boston.iloc[0]["game_id"] == opening.iloc[-1]["game_id"]
        assert boston.iloc[0]["pts_per_game"] == pytest.approx(opening["pts"].mean())
        assert boston.iloc[0]["wins"] == opening["won"].sum()

    def test_a_team_with_too_few_games_has_no_full_span(self, games, calibration) -> None:
        opening = games[games["team_id"] == BOS].sort_values(["game_date", "game_id"]).head(4)
        few = games[games["game_id"].isin(opening["game_id"])]
        every = rolling_team_metrics(few, calibration, games=5)
        full = rolling_team_metrics(few, calibration, games=5, full_spans=True)
        assert len(every) == len(few) and len(full) == 0
        assert list(full.columns) == list(every.columns)

    def test_a_span_of_one_is_each_game_on_its_own(self, games, calibration) -> None:
        single = rolling_team_metrics(games, calibration, games=1)
        row = single[(single["team_id"] == BOS) & (single["game_id"] == LAST_BOSTON_GAME)].iloc[0]
        assert row["off_rating"] == pytest.approx(100 * 113 / (107.44 * calibration["2025-26"]))
        assert (single["games_played"] == 1).all()
        assert set(single["wins"]) == {0, 1}

    def test_counts_are_whole_numbers(self, games, calibration) -> None:
        rolling = rolling_team_metrics(games, calibration, games=4)
        for key in ("games_played", "wins", "losses"):
            assert str(rolling[key].dtype) == "int64", key
        assert (rolling["wins"] + rolling["losses"] == rolling["games_played"]).all()

    def test_no_games(self, games, calibration) -> None:
        rolling = rolling_team_metrics(games.iloc[0:0], calibration)
        assert len(rolling) == 0
        assert list(rolling.columns) == ["team_id", "game_id", "game_date", *WINDOW_METRIC_KEYS]

    def test_the_span_must_be_at_least_one_game(self, games) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            rolling_team_metrics(games, games=0)


class TestSeasonOverSeason:
    def test_each_season_against_the_one_before(self, team_seasons) -> None:
        league = league_averages(team_seasons)
        changes = season_over_season(league)
        assert changes.index.tolist() == ["1996-97", "2012-13", "2025-26"]
        assert list(changes.columns) == list(TEAM_METRICS.keys)
        assert changes.loc["1996-97"].isna().all()
        expected = league.loc["2025-26", "pace"] - league.loc["2012-13", "pace"]
        assert changes.loc["2025-26", "pace"] == pytest.approx(expected)
        assert changes.loc["2012-13", "fg3a_rate"] == pytest.approx(
            league.loc["2012-13", "fg3a_rate"] - league.loc["1996-97", "fg3a_rate"]
        )

    def test_order_of_the_input_does_not_matter(self, team_seasons) -> None:
        league = league_averages(team_seasons)
        shuffled = season_over_season(league.iloc[::-1])
        pd.testing.assert_frame_equal(shuffled, season_over_season(league))
