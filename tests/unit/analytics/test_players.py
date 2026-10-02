"""Player metrics, on real fixture seasons and on small hand-built ones."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from front_office.analytics import formulas as f
from front_office.analytics.players import (
    BOX_METRIC_KEYS,
    IDENTITY_COLUMNS,
    PLAYER_METRICS,
    box_metrics,
    combined_on_off,
    player_season_metrics,
    recent_availability,
    rolling_metrics,
    team_minutes,
    window_metrics,
    window_totals,
)
from front_office.domain.schema import Provenance
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS

BOS, NYK = 1610612738, 1610612752
TATUM, VUCEVIC = 1628369, 202696


def totals(**values: float) -> pd.DataFrame:
    """One row of box-score totals; anything not given is zero."""
    row = {column: 0 for column in (*BOX_SCORE_COLUMNS, "games_played", "minutes", "plus_minus")}
    row.update(values)
    return pd.DataFrame([row])


@pytest.fixture(scope="module")
def regular(normalized) -> pd.DataFrame:
    seasons = normalized["player_seasons"]
    return seasons[seasons["season_type"] == "regular"].reset_index(drop=True)


@pytest.fixture(scope="module")
def metrics(normalized, regular) -> pd.DataFrame:
    season_games = normalized["team_seasons"].groupby("season")["games_played"].max()
    return player_season_metrics(regular, normalized["player_on_off"], season_games)


class TestCatalog:
    def test_keys_are_unique_and_every_metric_is_explained(self) -> None:
        assert len(PLAYER_METRICS.keys) == len(set(PLAYER_METRICS.keys))
        for spec in PLAYER_METRICS:
            assert spec.description.endswith("."), spec.key
            assert len(spec.label) <= 8, spec.key

    def test_categories_follow_the_roadmaps_player_profile(self) -> None:
        assert PLAYER_METRICS.categories == (
            "Availability",
            "Scoring",
            "Creation",
            "Rebounding",
            "Defense",
            "Impact",
        )

    def test_lower_is_better_for_the_things_a_player_wants_fewer_of(self) -> None:
        worse_when_higher = {s.key for s in PLAYER_METRICS if s.higher_is_better is False}
        assert worse_when_higher == {"tov_per_game", "tov_pct", "pf_per_36", "def_rating"}

    def test_league_measurements_are_tagged_measured(self) -> None:
        measured = {s.key for s in PLAYER_METRICS if s.provenance is Provenance.MEASURED}
        assert {"usage_pct", "assist_pct", "reb_pct", "net_rating", "games_played"} <= measured
        assert "ts_pct" not in measured and "pts_per_game" not in measured

    def test_box_metrics_are_a_subset_of_the_catalog(self) -> None:
        assert set(BOX_METRIC_KEYS) < set(PLAYER_METRICS.keys)


class TestBoxMetrics:
    def test_a_worked_example(self) -> None:
        line = box_metrics(
            totals(
                games_played=10, minutes=300, pts=250, fgm=80, fga=160, fg3m=20, fg3a=50,
                ftm=70, fta=80, oreb=20, dreb=60, reb=80, ast=60, tov=30, stl=15, blk=5,
                pf=25, plus_minus=40,
            )
        ).iloc[0]  # fmt: skip
        assert line["minutes_per_game"] == 30.0
        assert line["pts_per_game"] == 25.0
        assert line["pts_per_36"] == 30.0
        assert line["fg_pct"] == 0.5
        assert line["fg3_pct"] == 0.4
        assert line["ft_pct"] == 0.875
        assert line["efg_pct"] == 90 / 160
        assert line["ts_pct"] == pytest.approx(250 / (2 * (160 + 0.44 * 80)))
        assert line["fg3a_rate"] == 50 / 160
        assert line["ft_rate"] == 0.5
        assert line["ast_per_game"] == 6.0
        assert line["tov_pct"] == pytest.approx(30 / (160 + 0.44 * 80 + 30))
        assert line["ast_to_tov"] == 2.0
        assert (line["reb_per_game"], line["oreb_per_game"], line["dreb_per_game"]) == (8, 2, 6)
        assert line["stocks_per_36"] == pytest.approx((15 + 5) * 36 / 300)
        assert line["pf_per_36"] == 3.0
        assert line["plus_minus_per_game"] == 4.0

    def test_has_exactly_the_box_metric_columns(self) -> None:
        assert tuple(box_metrics(totals(games_played=1, minutes=10)).columns) == BOX_METRIC_KEYS

    def test_a_player_who_never_shot_has_no_shooting_percentages(self) -> None:
        line = box_metrics(totals(games_played=3, minutes=12, reb=2)).iloc[0]
        for key in ("fg_pct", "fg3_pct", "ft_pct", "efg_pct", "ts_pct", "tov_pct", "ast_to_tov"):
            assert math.isnan(line[key]), key
        assert line["pts_per_game"] == 0.0
        assert line["reb_per_game"] == pytest.approx(2 / 3)

    def test_no_minutes_gives_no_per_36(self) -> None:
        line = box_metrics(totals(games_played=1, minutes=0)).iloc[0]
        assert math.isnan(line["pts_per_36"]) and math.isnan(line["stocks_per_36"])

    def test_no_infinities_anywhere_on_real_data(self, regular) -> None:
        import numpy as np

        values = box_metrics(regular).to_numpy(dtype="float64")
        assert not np.isinf(values).any()


class TestSeasonMetrics:
    def test_one_row_per_player_season_with_every_metric(self, metrics, regular) -> None:
        assert len(metrics) == len(regular)
        assert tuple(metrics.columns) == (*IDENTITY_COLUMNS, *PLAYER_METRICS.keys)
        assert not metrics.duplicated(["player_id", "season", "season_type"]).any()

    def test_a_real_line(self, metrics) -> None:
        """Jayson Tatum, 2025-26: 348 points in 16 games and 521.85 minutes."""
        tatum = metrics.set_index("player_id").loc[TATUM]
        assert tatum["player_name"] == "Jayson Tatum"
        assert tatum["pts_per_game"] == pytest.approx(348 / 16)
        assert tatum["minutes_per_game"] == pytest.approx(521.85 / 16)
        assert tatum["pts_per_36"] == pytest.approx(348 * 36 / 521.85)
        assert tatum["pts_per_100"] == pytest.approx(348 * 100 / 1069)
        assert tatum["fg_pct"] == pytest.approx(118 / 287)
        assert tatum["fg3_pct"] == pytest.approx(47 / 143)
        assert tatum["efg_pct"] == pytest.approx((118 + 23.5) / 287)
        assert tatum["ts_pct"] == pytest.approx(348 / (2 * (287 + 0.44 * 79)))
        assert tatum["ast_to_tov"] == pytest.approx(85 / 39)
        assert tatum["plus_minus_per_game"] == pytest.approx(118 / 16)
        assert (tatum["games_started"], tatum["start_share"]) == (16, 1.0)
        assert tatum["games_played_share"] == pytest.approx(16 / 82)

    def test_league_measurements_pass_through_unchanged(self, metrics, regular) -> None:
        source = regular.set_index("player_id")
        ours = metrics.set_index("player_id")
        for key in ("usage_pct", "assist_pct", "oreb_pct", "dreb_pct", "reb_pct", "off_rating",
                    "def_rating", "net_rating", "player_impact_estimate"):  # fmt: skip
            pd.testing.assert_series_equal(
                ours[key], source[key].astype("float64"), check_names=False, obj=key
            )

    def test_on_off_difference_for_a_one_team_player(self, metrics, normalized) -> None:
        stint = normalized["player_on_off"].set_index("player_id").loc[TATUM]
        expected = stint["on_court_net_rating"] - stint["off_court_net_rating"]
        assert metrics.set_index("player_id").loc[TATUM, "on_off_net"] == pytest.approx(expected)
        assert expected == pytest.approx(10.5 - 7.8)

    def test_players_without_on_off_data_have_no_difference(self, regular, normalized) -> None:
        on_off = normalized["player_on_off"]
        without_tatum = on_off[on_off["player_id"] != TATUM]
        result = player_season_metrics(regular, without_tatum).set_index("player_id")
        assert math.isnan(result.loc[TATUM, "on_off_net"])
        assert result["on_off_net"].notna().sum() == without_tatum["player_id"].nunique()

    def test_without_on_off_or_season_length_those_metrics_are_missing(self, regular) -> None:
        bare = player_season_metrics(regular)
        assert bare["on_off_net"].isna().all()
        assert bare["games_played_share"].isna().all()
        assert bare["ts_pct"].notna().any()

    def test_share_of_season_is_only_defined_for_the_regular_season(self, normalized) -> None:
        seasons = normalized["player_seasons"]
        season_games = normalized["team_seasons"].groupby("season")["games_played"].max()
        both = player_season_metrics(seasons, None, season_games)
        playoffs = both[both["season_type"] == "playoffs"]
        assert len(playoffs) > 0 and playoffs["games_played_share"].isna().all()
        assert both.loc[both["season_type"] == "regular", "games_played_share"].notna().all()
        assert both["games_played_share"].max() <= 1.0

    def test_metrics_stay_within_sensible_bounds(self, metrics) -> None:
        for key in ("fg_pct", "fg3_pct", "ft_pct", "tov_pct", "start_share", "games_played_share"):
            values = metrics[key].dropna()
            assert ((values >= 0) & (values <= 1)).all(), key
        assert metrics["efg_pct"].dropna().max() <= 1.5
        assert (metrics["minutes_per_game"] <= 48).all()

    def test_an_empty_season_gives_an_empty_frame_with_every_column(self, regular) -> None:
        empty = player_season_metrics(regular.iloc[0:0])
        assert len(empty) == 0
        assert tuple(empty.columns) == (*IDENTITY_COLUMNS, *PLAYER_METRICS.keys)

    def test_the_input_frame_is_not_modified(self, regular, normalized) -> None:
        before = regular.copy(deep=True)
        player_season_metrics(regular, normalized["player_on_off"])
        pd.testing.assert_frame_equal(regular, before)


class TestCombinedOnOff:
    def stint(
        self, team: int, on_min: float, on_net: float, off_min: float, off_net: float
    ) -> dict:
        return {
            "player_id": 1,
            "season": "2025-26",
            "season_type": "regular",
            "team_id": team,
            "on_court_minutes": on_min,
            "on_court_net_rating": on_net,
            "off_court_minutes": off_min,
            "off_court_net_rating": off_net,
        }

    def test_two_teams_are_weighted_by_the_minutes_behind_each_rating(self) -> None:
        frame = pd.DataFrame(
            [self.stint(BOS, 1000, 10.0, 2000, 2.0), self.stint(NYK, 500, -2.0, 1000, 5.0)]
        )
        on = (10.0 * 1000 + -2.0 * 500) / 1500
        off = (2.0 * 2000 + 5.0 * 1000) / 3000
        result = combined_on_off(frame)
        assert result.loc[(1, "2025-26", "regular"), "on_off_net"] == pytest.approx(on - off)

    def test_a_stint_with_no_off_court_rating_is_left_out_of_both_sides(self) -> None:
        frame = pd.DataFrame(
            [self.stint(BOS, 1000, 10.0, 2000, 2.0), self.stint(NYK, 500, -20.0, None, None)]
        )
        result = combined_on_off(frame)
        assert result.loc[(1, "2025-26", "regular"), "on_off_net"] == pytest.approx(8.0)

    def test_no_usable_stint_gives_missing(self) -> None:
        result = combined_on_off(pd.DataFrame([self.stint(BOS, 500, 3.0, None, None)]))
        assert math.isnan(result.loc[(1, "2025-26", "regular"), "on_off_net"])

    def test_an_empty_table(self, normalized) -> None:
        result = combined_on_off(normalized["player_on_off"].iloc[0:0])
        assert len(result) == 0 and list(result.columns) == ["on_off_net"]


@pytest.fixture(scope="module")
def logs(normalized) -> pd.DataFrame:
    frame = normalized["player_game_logs"]
    return frame[frame["season_type"] == "regular"]


@pytest.fixture(scope="module")
def season(normalized) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Regular-season player logs and team games for 2025-26."""
    player_logs, games = normalized["player_game_logs"], normalized["team_games"]
    return (
        player_logs[
            (player_logs["season"] == "2025-26") & (player_logs["season_type"] == "regular")
        ],
        games[(games["season"] == "2025-26") & (games["season_type"] == "regular")],
    )


class TestWindows:
    def test_the_whole_season_reproduces_the_season_line(self, logs, regular) -> None:
        window = window_totals(logs)
        season = regular.set_index("player_id")
        for column in ("games_played", "pts", "fgm", "fga", "fg3m", "ftm", "fta", "ast", "stl"):
            assert (window[column] == season[column].reindex(window.index)).all(), column

    def test_whole_season_metrics_equal_the_season_metrics(self, logs, metrics) -> None:
        window = window_metrics(logs)
        season = metrics.set_index("player_id").reindex(window.index)
        for key in ("pts_per_game", "fg_pct", "fg3_pct", "ft_pct", "efg_pct", "ts_pct"):
            pd.testing.assert_series_equal(
                window[key], season[key], check_names=False, check_exact=False, obj=key
            )

    def test_last_games_takes_each_players_most_recent(self, logs) -> None:
        window = window_totals(logs, last_games=5)
        assert window["games_played"].max() == 5
        tatum_logs = logs[logs["player_id"] == TATUM].sort_values("game_date")
        last_five = tatum_logs.tail(5)
        assert window.loc[TATUM, "pts"] == last_five["pts"].sum()
        assert window.loc[TATUM, "first_game"] == last_five["game_date"].min()
        assert window.loc[TATUM, "last_game"] == tatum_logs["game_date"].max()

    def test_a_player_with_fewer_games_than_the_window_keeps_them_all(self, logs) -> None:
        counts = logs.groupby("player_id").size()
        few = counts[counts < 20]
        assert TATUM in few.index  # he played 16 games
        window = window_totals(logs, last_games=20)
        assert (window.loc[few.index, "games_played"] == few).all()
        assert window["games_played"].max() == 20

    def test_a_date_range(self, logs) -> None:
        start, end = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-31")
        window = window_totals(logs, start=start, end=end)
        january = logs[(logs["game_date"] >= start) & (logs["game_date"] <= end)]
        assert window["games_played"].sum() == len(january)
        assert window["first_game"].min() >= start and window["last_game"].max() <= end
        assert window["pts"].sum() == january["pts"].sum()

    def test_date_range_then_last_games(self, logs) -> None:
        end = pd.Timestamp("2026-01-31")
        window = window_totals(logs, end=end, last_games=3)
        assert window["last_game"].max() <= end
        assert window["games_played"].max() == 3

    def test_players_with_no_games_in_the_span_are_absent(self, logs) -> None:
        window = window_totals(logs, start=pd.Timestamp("2030-01-01"))
        assert len(window) == 0

    def test_window_metrics_carry_the_span(self, logs) -> None:
        window = window_metrics(logs, last_games=10)
        assert list(window.columns[:2]) == ["first_game", "last_game"]
        assert tuple(window.columns[2:]) == BOX_METRIC_KEYS

    def test_a_window_must_be_at_least_one_game(self, logs) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            window_totals(logs, last_games=0)


class TestRolling:
    def test_one_row_per_game_in_playing_order(self, logs) -> None:
        rolling = rolling_metrics(logs, games=5)
        assert len(rolling) == len(logs)
        assert list(rolling.columns[:3]) == ["player_id", "game_id", "game_date"]
        assert tuple(rolling.columns[3:]) == BOX_METRIC_KEYS
        tatum = rolling[rolling["player_id"] == TATUM]
        assert tatum["game_date"].is_monotonic_increasing
        assert tatum["games_played"].tolist()[:6] == [1, 2, 3, 4, 5, 5]
        assert rolling["games_played"].max() == 5

    def test_the_last_row_is_the_last_window(self, logs) -> None:
        rolling = rolling_metrics(logs, games=5)
        window = window_metrics(logs, last_games=5)
        last = rolling.groupby("player_id").tail(1).set_index("player_id")
        for key in ("games_played", "pts_per_game", "ast_per_game", "ts_pct", "fg3_pct"):
            pd.testing.assert_series_equal(
                last[key],
                window[key].reindex(last.index),
                check_names=False,
                check_dtype=False,
                obj=key,
            )

    def test_the_first_row_is_the_first_game_alone(self, logs) -> None:
        rolling = rolling_metrics(logs, games=5)
        first = rolling[rolling["player_id"] == TATUM].iloc[0]
        opener = logs[logs["player_id"] == TATUM].sort_values(["game_date", "game_id"]).iloc[0]
        assert first["game_id"] == opener["game_id"]
        assert first["pts_per_game"] == opener["pts"]

    def test_full_spans_leave_out_the_early_games(self, logs) -> None:
        every = rolling_metrics(logs, games=5)
        full = rolling_metrics(logs, games=5, full_spans=True)
        assert (full["games_played"] == 5).all()
        # What is kept is unchanged: the same rows, without each player's first four.
        kept = every[every["games_played"] == 5].reset_index(drop=True)
        pd.testing.assert_frame_equal(full, kept)
        tatum = full[full["player_id"] == TATUM]
        assert len(tatum) == 16 - 4
        opening = logs[logs["player_id"] == TATUM].sort_values(["game_date", "game_id"]).head(5)
        assert tatum.iloc[0]["game_id"] == opening.iloc[-1]["game_id"]
        assert tatum.iloc[0]["pts_per_game"] == pytest.approx(opening["pts"].mean())

    def test_a_player_with_too_few_games_has_no_full_span(self, logs) -> None:
        every = rolling_metrics(logs, games=20)
        full = rolling_metrics(logs, games=20, full_spans=True)
        assert TATUM in set(every["player_id"])
        assert TATUM not in set(full["player_id"])  # he played 16 games
        assert list(full.columns) == list(every.columns)
        counts = logs.groupby("player_id").size()
        assert set(full["player_id"]) == set(counts[counts >= 20].index)

    def test_the_span_must_be_at_least_one_game(self, logs) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            rolling_metrics(logs, games=0)


class TestRecentAvailability:
    def test_counts_appearances_in_the_teams_latest_games(self, season) -> None:
        logs, games = season
        result = recent_availability(logs, games, team_games_back=20)
        celtics_last_20 = (
            games[games["team_id"] == BOS].sort_values("game_date").tail(20)["game_id"]
        )
        tatum_played = logs[(logs["player_id"] == TATUM) & logs["game_id"].isin(celtics_last_20)]
        row = result.loc[TATUM]
        assert (row["team_id"], row["team_games"]) == (BOS, 20)
        assert row["games_played"] == len(tatum_played)
        assert row["availability"] == pytest.approx(len(tatum_played) / 20)

    def test_availability_is_a_fraction(self, season) -> None:
        result = recent_availability(*season, team_games_back=10)
        assert ((result["availability"] >= 0) & (result["availability"] <= 1)).all()
        assert (result["games_played"] <= result["team_games"]).all()

    def test_a_traded_player_is_measured_against_his_latest_team(self, season) -> None:
        logs, games = season
        result = recent_availability(logs, games, team_games_back=82)
        row = result.loc[VUCEVIC]
        assert row["team_id"] == BOS
        with_boston = logs[(logs["player_id"] == VUCEVIC) & (logs["team_id"] == BOS)]
        assert row["games_played"] == len(with_boston)
        assert row["games_played"] < len(logs[logs["player_id"] == VUCEVIC])

    def test_no_logs(self, season) -> None:
        _, games = season
        result = recent_availability(season[0].iloc[0:0], games)
        assert len(result) == 0
        assert list(result.columns) == ["team_id", "team_games", "games_played", "availability"]

    def test_the_span_must_be_at_least_one_game(self, season) -> None:
        with pytest.raises(ValueError):
            recent_availability(*season, team_games_back=0)


def test_true_shooting_in_metrics_is_the_formula(metrics, regular) -> None:
    """The metric table calls the formula module; it does not carry its own copy."""
    expected = f.true_shooting_pct(regular["pts"], regular["fga"], regular["fta"])
    pd.testing.assert_series_equal(metrics["ts_pct"], expected, check_names=False)


class TestTeamMinutes:
    """A season's minutes divided between the teams a player appeared for."""

    def seasons(self, *rows: tuple[int, int, float]) -> pd.DataFrame:
        columns = ["player_id", "team_id", "minutes"]
        return pd.DataFrame(rows, columns=columns).assign(season="2025-26", season_type="regular")

    def logs(self, *rows: tuple[int, int, int]) -> pd.DataFrame:
        """(player, team, minutes) for one game each."""
        frame = pd.DataFrame(rows, columns=["player_id", "team_id", "minutes"])
        return frame.assign(
            season="2025-26",
            season_type="regular",
            game_id=[f"{number:010d}" for number in range(len(frame))],
        )

    def minutes(self, seasons: pd.DataFrame, logs: pd.DataFrame) -> dict[tuple[int, int], float]:
        found = team_minutes(seasons, logs)
        assert not found.duplicated(["player_id", "season", "season_type", "team_id"]).any()
        return {(row.player_id, row.team_id): row.minutes for row in found.itertuples()}

    def test_a_player_who_stayed_put_keeps_the_published_minutes(self) -> None:
        # The log rounds each game to the whole minute; the season total does not.
        found = self.minutes(self.seasons((7, BOS, 71.4)), self.logs((7, BOS, 36), (7, BOS, 35)))
        assert found == {(7, BOS): 71.4}

    def test_a_traded_player_is_divided_in_proportion_to_the_logged_minutes(self) -> None:
        logs = self.logs((7, BOS, 30), (7, BOS, 30), (7, NYK, 20))
        found = self.minutes(self.seasons((7, NYK, 82.0)), logs)
        assert found == {(7, BOS): pytest.approx(61.5), (7, NYK): pytest.approx(20.5)}
        assert sum(found.values()) == pytest.approx(82.0)

    def test_logged_minutes_that_are_missing_do_not_lose_published_ones(self) -> None:
        # Some box scores of 2005-07 credit players with a fraction of what they played.
        logs = self.logs((7, BOS, 30), (7, NYK, 10))
        found = self.minutes(self.seasons((7, NYK, 120.0)), logs)
        assert found == {(7, BOS): pytest.approx(90.0), (7, NYK): pytest.approx(30.0)}

    def test_a_player_logged_at_zero_minutes_is_divided_by_games(self) -> None:
        logs = self.logs((7, BOS, 0), (7, BOS, 0), (7, NYK, 0))
        found = self.minutes(self.seasons((7, NYK, 1.5)), logs)
        assert found == {(7, BOS): pytest.approx(1.0), (7, NYK): pytest.approx(0.5)}

    def test_a_player_with_no_log_goes_to_the_team_the_season_names(self) -> None:
        found = self.minutes(self.seasons((7, NYK, 300.0)), self.logs((8, BOS, 30)))
        assert found == {(7, NYK): 300.0}

    def test_a_log_without_a_season_line_is_not_a_stint(self) -> None:
        found = self.minutes(self.seasons((7, NYK, 300.0)), self.logs((7, NYK, 30), (8, BOS, 30)))
        assert set(found) == {(7, NYK)}

    def test_seasons_and_phases_are_divided_apart(self) -> None:
        seasons = pd.concat(
            [
                self.seasons((7, NYK, 100.0)),
                self.seasons((7, BOS, 40.0)).assign(season_type="playoffs"),
            ]
        )
        logs = pd.concat(
            [
                self.logs((7, BOS, 10), (7, NYK, 30)),
                self.logs((7, BOS, 40)).assign(season_type="playoffs", game_id="P1"),
            ]
        )
        found = team_minutes(seasons, logs).set_index(["season_type", "team_id"])["minutes"]
        assert found.to_dict() == {
            ("regular", BOS): pytest.approx(25.0),
            ("regular", NYK): pytest.approx(75.0),
            ("playoffs", BOS): pytest.approx(40.0),
        }

    def test_on_the_fixture_every_published_minute_is_assigned_once(self, normalized) -> None:
        seasons, logs = normalized["player_seasons"], normalized["player_game_logs"]
        found = team_minutes(seasons, logs)
        assert str(found["team_id"].dtype) == "int64"
        keys = ["player_id", "season", "season_type"]
        summed = found.groupby(keys)["minutes"].sum()
        published = seasons.set_index(keys)["minutes"]
        assert len(summed) == len(published)
        assert (summed - published.reindex(summed.index)).abs().max() < 1e-9
        # A traded player has one row for each team: the season line counts the teams.
        teams = found.groupby(keys).size()
        assert (teams == seasons.set_index(keys)["team_count"].reindex(teams.index)).all()
        assert teams.max() >= 2
