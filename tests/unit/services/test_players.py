"""The player service, against a database built from the fixture store.

The fixture has player data for everyone who appeared for Boston or New York in
2025-26, so those two rosters are complete and the rest of the league is absent.
The ``lab`` and ``priced_lab`` fixtures are in this directory's conftest.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from front_office.analytics.players import BOX_METRIC_KEYS, PLAYER_METRICS
from front_office.config import Settings
from front_office.services import (
    DEFAULT_QUALIFICATION,
    Lab,
    LabNotBuilt,
    LabStatus,
    PlayerTable,
    Qualification,
    Window,
)
from front_office.services.players import PLAYER_AND_VALUE_METRICS
from tests.helpers import BRIDGES, TOWNS

BOS, NYK = 1610612738, 1610612752
TATUM, BROWN, VUCEVIC, ABDELNABY = 1628369, 1627759, 202696, 76001


@pytest.fixture(scope="module")
def table(lab: Lab) -> PlayerTable:
    return lab.players.table("2025-26")


class TestStatus:
    def test_reports_what_the_database_holds(self, lab: Lab) -> None:
        status = lab.status()
        assert status.is_built and status.is_current
        assert status.build_id == 1
        assert status.built_at == pd.Timestamp("2026-10-01 12:00:09").to_pydatetime()
        assert status.team_seasons == ("2025-26", "2012-13", "1996-97")
        assert status.player_seasons == ("2025-26",)
        assert status.cap_seasons == ("2026-27", "2025-26", "2024-25")
        assert status.contract_seasons == () and not status.has_contracts
        assert status.contract_as_of is None
        assert status.latest_stats_season == "2025-26"

    def test_without_contracts_payroll_defaults_to_the_newest_cap_season(self, lab: Lab) -> None:
        assert lab.status().default_payroll_season == "2026-27"

    def test_with_contracts_payroll_defaults_to_the_league_year_the_file_was_current_in(
        self, priced_lab: Lab
    ) -> None:
        status = priced_lab.status()
        assert status.contract_seasons == ("2027-28", "2026-27")
        assert status.has_contracts
        assert status.contract_as_of == date(2026, 10, 1)
        assert status.default_payroll_season == "2026-27"

    def test_an_unbuilt_lab_says_so_instead_of_failing(self, settings: Settings) -> None:
        with Lab(settings) as empty:
            status = empty.status()
            assert not status.is_built and status.build_id is None
            assert status.team_seasons == () and status.latest_stats_season is None
            assert status.cap_seasons == ("2026-27", "2025-26", "2024-25")
            with pytest.raises(LabNotBuilt, match="fol refresh"):
                empty.players.table("2025-26")
            with pytest.raises(LabNotBuilt):
                empty.require_built()

    @pytest.mark.parametrize(
        ("covered", "as_of", "expected"),
        [
            # A file that looks ahead, imported during 2025-26, is priced in 2025-26.
            (("2027-28", "2026-27", "2025-26"), date(2026, 3, 1), "2025-26"),
            # A history current in 2026-27 is priced in 2026-27, not in its first season.
            (("2026-27", "2025-26", "2024-25", "2015-16"), date(2026, 7, 7), "2026-27"),
            # A history that stops before its date is priced in its latest priced season.
            (("2025-26", "2024-25", "2023-24"), date(2026, 8, 1), "2025-26"),
            # A file that starts after its date is priced in its earliest priced season.
            (("2028-29", "2027-28", "2026-27"), date(2026, 6, 15), "2026-27"),
            # Without a date, the earliest priced season.
            (("2027-28", "2026-27", "2025-26"), None, "2025-26"),
        ],
    )
    def test_payroll_defaults_to_the_season_the_file_was_current_for(
        self, covered: tuple[str, ...], as_of: date | None, expected: str
    ) -> None:
        status = LabStatus(
            is_built=True,
            is_current=True,
            build_id=1,
            built_at=None,
            team_seasons=(),
            player_seasons=(),
            cap_seasons=("2026-27", "2025-26", "2024-25"),
            contract_seasons=covered,
            contract_as_of=as_of,
        )
        assert status.default_payroll_season == expected

    def test_cap_rules_by_season(self, lab: Lab) -> None:
        assert lab.rules("2026-27").salary_cap == 164_961_000
        assert lab.rules("2019-20") is None

    def test_team_labels(self, lab: Lab) -> None:
        labels = lab.team_labels()
        assert len(labels) == 30
        assert labels.loc[BOS].tolist() == ["BOS", "Boston Celtics", "East", "Atlantic"]


class TestTable:
    def test_one_row_per_player_with_every_metric(self, table: PlayerTable) -> None:
        players = table.players
        assert players.index.name == "player_id" and players.index.is_unique
        assert len(players) == 41
        assert set(PLAYER_METRICS.keys) <= set(players.columns)
        # A whole regular season carries what the value model makes of it as well.
        assert table.metrics is PLAYER_AND_VALUE_METRICS
        assert set(table.metrics.keys) <= set(players.columns)
        assert players["player_name"].is_monotonic_increasing
        assert table.percentiles.index.equals(players.index)
        assert (table.season, table.season_type) == ("2025-26", "regular")
        assert table.window.is_full_season

    def test_identity_is_joined_from_the_player_and_team_tables(self, table: PlayerTable) -> None:
        tatum = table.players.loc[TATUM]
        assert (tatum["player_name"], tatum["team"], tatum["team_name"]) == (
            "Jayson Tatum",
            "BOS",
            "Boston Celtics",
        )
        assert (tatum["position"], tatum["position_group"]) == ("F-G", "Forward")
        assert (tatum["age"], tatum["height_inches"], tatum["weight_lbs"]) == (28, 80, 210)
        assert tatum["experience_years"] == 8
        assert tatum["birth_date"] == pd.Timestamp("1998-03-03")

    def test_metrics_are_the_analytics_values(self, table: PlayerTable) -> None:
        tatum = table.players.loc[TATUM]
        assert tatum["pts_per_game"] == pytest.approx(348 / 16)
        assert tatum["ts_pct"] == pytest.approx(348 / (2 * (287 + 0.44 * 79)))
        assert tatum["usage_pct"] == pytest.approx(0.29)
        assert tatum["on_off_net"] == pytest.approx(2.7)
        assert tatum["games_played_share"] == pytest.approx(16 / 82)

    def test_a_traded_player_shows_the_team_he_finished_with(self, table: PlayerTable) -> None:
        vucevic = table.players.loc[VUCEVIC]
        assert (vucevic["team"], vucevic["team_count"]) == ("BOS", 2)

    def test_qualification_marks_players_and_limits_percentiles(self, table: PlayerTable) -> None:
        players = table.players
        assert table.qualification == DEFAULT_QUALIFICATION
        expected = (players["games_played"] >= 20) & (players["minutes"] >= 300)
        assert (players["is_qualified"] == expected).all()
        assert table.qualified_count == int(expected.sum())
        assert not players.loc[TATUM, "is_qualified"]  # 16 games
        assert table.percentiles.loc[TATUM].isna().all()
        assert table.percentiles.loc[players["is_qualified"], "pts_per_game"].notna().all()

    def test_a_looser_qualification_ranks_more_players(self, lab: Lab) -> None:
        loose = lab.players.table("2025-26", qualification=Qualification())
        assert loose.qualified_count == len(loose.players) == 41
        assert loose.percentiles.loc[TATUM, "pts_per_game"] > 90

    def test_percentiles_are_oriented_so_higher_is_better(self, table: PlayerTable) -> None:
        ranked = table.players[table.players["is_qualified"]]
        careless = ranked["tov_per_game"].idxmax()
        careful = ranked["tov_per_game"].idxmin()
        assert table.percentiles.loc[careless, "tov_per_game"] < 10
        assert table.percentiles.loc[careful, "tov_per_game"] > 90

    def test_by_position_ranks_within_the_position_group(
        self, lab: Lab, table: PlayerTable
    ) -> None:
        grouped = lab.players.table("2025-26", by_position=True)
        players = grouped.players[grouped.players["is_qualified"]]
        for _, members in players.groupby("position_group"):
            ranked = grouped.percentiles.loc[members.index, "reb_per_game"]
            assert ranked.loc[members["reb_per_game"].idxmax()] == ranked.max()
            assert ranked.mean() == pytest.approx(50.0)
        assert not grouped.percentiles["reb_per_game"].equals(table.percentiles["reb_per_game"])

    def test_playoffs(self, lab: Lab) -> None:
        playoffs = lab.players.table("2025-26", "playoffs", qualification=Qualification())
        assert len(playoffs.players) == 30
        assert playoffs.players.loc[TATUM, "games_played"] == 6
        assert playoffs.players["games_played_share"].isna().all()
        assert playoffs.players["on_off_net"].isna().all()  # on/off is regular season only

    def test_a_season_without_player_data_is_empty(self, lab: Lab) -> None:
        empty = lab.players.table("2012-13")
        assert len(empty.players) == 0 and empty.qualified_count == 0
        assert set(PLAYER_METRICS.keys) <= set(empty.players.columns)

    def test_without_a_payroll_season_contract_columns_are_empty(self, table: PlayerTable) -> None:
        assert table.payroll_season is None
        assert table.players[["salary", "salary_cap_pct", "years_remaining"]].isna().all().all()


class TestContracts:
    def test_salaries_are_joined_for_the_payroll_season(self, priced_lab: Lab) -> None:
        priced = priced_lab.players.table("2025-26", payroll_season="2026-27")
        tatum, brown = priced.players.loc[TATUM], priced.players.loc[BROWN]
        cap = priced_lab.rules("2026-27").salary_cap
        assert tatum["salary"] == 40_000_000
        assert tatum["salary_cap_pct"] == pytest.approx(40_000_000 / cap)
        assert (tatum["years_remaining"], brown["years_remaining"]) == (1, 0)
        assert brown["salary"] == 30_000_000
        assert priced.payroll_season == "2026-27"
        # Paid by two teams within the season: the sum is his salary.
        assert priced.players.loc[BRIDGES, "salary"] == 25_000_000
        others = priced.players.drop(index=[TATUM, BROWN, BRIDGES])
        assert others["salary"].isna().all()

    def test_dead_money_is_not_shown_as_a_players_salary(self, priced_lab: Lab) -> None:
        priced = priced_lab.players.table("2025-26", payroll_season="2026-27")
        # Brown has an active deal and dead money elsewhere: the active one is his salary.
        assert priced.players.loc[BROWN, "salary"] == 30_000_000
        # Vucevic is owed dead money only: he has no salary for the season.
        assert pd.isna(priced.players.loc[VUCEVIC, "salary"])
        owed = priced_lab.read("contract_years", {"player_id": VUCEVIC})
        assert owed["salary"].tolist() == [5_000_000]

    def test_a_later_season_shows_that_seasons_salary_and_option(self, priced_lab: Lab) -> None:
        later = priced_lab.players.table("2025-26", payroll_season="2027-28")
        tatum = later.players.loc[TATUM]
        assert (tatum["salary"], tatum["option"]) == (44_000_000, "player")
        assert math.isnan(tatum["salary_cap_pct"])  # no cap is configured for 2027-28
        assert pd.isna(later.players.loc[BROWN, "salary"])

    def test_profile_carries_the_contract(self, priced_lab: Lab) -> None:
        profile = priced_lab.players.profile(TATUM)
        assert profile.contract_years["season"].tolist() == ["2026-27", "2027-28"]
        assert profile.contract_years["team"].tolist() == ["BOS", "BOS"]
        assert profile.contract["total_salary"] == 84_000_000
        assert profile.contract["source_label"] == "invented for tests"


class TestWindow:
    def test_a_window_offers_box_metrics_only(self, lab: Lab) -> None:
        last = lab.players.table(
            "2025-26", window=Window(last_games=5), qualification=Qualification()
        )
        assert last.metrics.keys == BOX_METRIC_KEYS
        assert "usage_pct" not in last.players.columns
        assert last.players["games_played"].max() == 5
        assert not last.window.is_full_season

    def test_window_values_come_from_the_game_log(self, lab: Lab) -> None:
        last = lab.players.table(
            "2025-26", window=Window(last_games=5), qualification=Qualification()
        )
        log = lab.players.game_log(TATUM, "2025-26").head(5)
        assert last.players.loc[TATUM, "pts_per_game"] == pytest.approx(log["pts"].mean())

    def test_qualification_applies_to_the_games_in_the_window(self, lab: Lab) -> None:
        rule = Qualification(min_games=10)
        last = lab.players.table("2025-26", window=Window(last_games=10), qualification=rule)
        assert last.players.loc[TATUM, "is_qualified"]
        strict = lab.players.table(
            "2025-26", window=Window(last_games=10), qualification=Qualification(min_games=11)
        )
        assert strict.qualified_count == 0

    def test_a_date_range(self, lab: Lab) -> None:
        january = Window(start=date(2026, 1, 1), end=date(2026, 1, 31))
        span = lab.players.table("2025-26", window=january, qualification=Qualification())
        assert 0 < len(span.players) <= 41
        assert span.players["games_played"].max() <= 17
        assert TATUM not in span.players.index  # he did not play in January

    @pytest.mark.parametrize(
        ("window", "text"),
        [
            (Window(), "Full season"),
            (Window(last_games=10), "Last 10 games"),
            (Window(start=date(2026, 1, 1), end=date(2026, 1, 31)), "Jan 01, 2026 to Jan 31, 2026"),
            (Window(start=date(2026, 3, 1)), "From Mar 01, 2026"),
            (Window(end=date(2025, 12, 25)), "Through Dec 25, 2025"),
            (Window(last_games=5, end=date(2025, 12, 25)), "Last 5 games, through Dec 25, 2025"),
        ],
    )
    def test_description(self, window: Window, text: str) -> None:
        assert window.describe() == text

    @pytest.mark.parametrize(
        "kwargs", [{"last_games": 0}, {"start": date(2026, 2, 1), "end": date(2026, 1, 1)}]
    )
    def test_impossible_windows_are_rejected(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            Window(**kwargs)


class TestProfile:
    def test_who_he_is(self, lab: Lab) -> None:
        player = lab.players.profile(TATUM).player
        assert player["full_name"] == "Jayson Tatum"
        assert player["current_team"] == "Boston Celtics"
        assert player["position_group"] == "Forward"
        assert (player["draft_year"], player["draft_number"]) == (2017, 3)

    def test_every_season_newest_first_regular_before_playoffs(self, lab: Lab) -> None:
        seasons = lab.players.profile(TATUM).seasons
        assert seasons[["season", "season_type"]].values.tolist() == [
            ["2025-26", "regular"],
            ["2025-26", "playoffs"],
        ]
        assert seasons["team"].tolist() == ["BOS", "BOS"]
        assert seasons.iloc[0]["pts_per_game"] == pytest.approx(348 / 16)
        assert seasons.iloc[1]["pts_per_game"] == pytest.approx(140 / 6)

    def test_on_off_stints(self, lab: Lab) -> None:
        stints = lab.players.profile(TATUM).on_off
        assert len(stints) == 1
        stint = stints.iloc[0]
        assert (stint["team"], stint["on_court_minutes"]) == ("BOS", 522.0)
        assert stint["on_off_net"] == pytest.approx(10.5 - 7.8)

    def test_a_retired_player_has_a_profile_with_no_seasons(self, lab: Lab) -> None:
        profile = lab.players.profile(ABDELNABY)
        assert profile.player["current_team"] is None
        assert len(profile.seasons) == 0 and len(profile.on_off) == 0
        assert profile.contract is None and len(profile.contract_years) == 0

    def test_an_unknown_player(self, lab: Lab) -> None:
        with pytest.raises(KeyError, match="no player with id 1"):
            lab.players.profile(1)


class TestGameLog:
    def test_newest_first_with_opponent_venue_and_result(self, lab: Lab) -> None:
        log = lab.players.game_log(TATUM, "2025-26")
        assert len(log) == 16
        assert log["game_date"].is_monotonic_decreasing
        assert set(log["team"]) == {"BOS"}
        assert set(log["venue"]) <= {"Home", "Away", "Neutral"}
        assert log["result"].str.match(r"^[WL] \d+-\d+$").all()
        assert log["pts"].sum() == 348

    def test_results_agree_with_the_team_table(self, lab: Lab) -> None:
        log = lab.players.game_log(TATUM, "2025-26")
        games = lab.read("team_games", {"team_id": BOS, "game_id": log["game_id"].tolist()})
        games = games.set_index("game_id")
        for row in log.itertuples():
            game = games.loc[row.game_id]
            letter = "W" if game["won"] else "L"
            assert row.result == f"{letter} {game['pts']}-{game['opp_pts']}"
            assert row.venue == ("Home" if game["is_home"] else "Away")

    def test_single_game_true_shooting(self, lab: Lab) -> None:
        row = lab.players.game_log(TATUM, "2025-26").iloc[0]
        expected = row["pts"] / (2 * (row["fga"] + 0.44 * row["fta"]))
        assert row["ts_pct"] == pytest.approx(expected)

    def test_a_traded_players_log_spans_both_teams(self, lab: Lab) -> None:
        log = lab.players.game_log(VUCEVIC, "2025-26")
        assert log["team"].nunique() == 2
        assert log.iloc[0]["team"] == "BOS"

    def test_a_neutral_site_game_is_neither_home_nor_away(self, lab: Lab) -> None:
        """New York met Orlando in Las Vegas in the in-season tournament (0022501229)."""
        logs = lab.read("player_game_logs", {"game_id": "0022501229", "team_id": NYK})
        knick = int(logs["player_id"].iloc[0])
        log = lab.players.game_log(knick, "2025-26").set_index("game_id")
        assert log.loc["0022501229", "venue"] == "Neutral"
        assert set(log["venue"]) == {"Home", "Away", "Neutral"}

    def test_no_games(self, lab: Lab) -> None:
        log = lab.players.game_log(TATUM, "2012-13")
        assert len(log) == 0 and "result" in log.columns


class TestRollingAndAvailability:
    def test_rolling_metrics_end_at_the_last_window(self, lab: Lab) -> None:
        rolling = lab.players.rolling(TATUM, "2025-26", games=5)
        assert len(rolling) == 16
        assert rolling["game_date"].is_monotonic_increasing
        assert rolling["games_played"].tolist()[:6] == [1, 2, 3, 4, 5, 5]
        last_five = lab.players.game_log(TATUM, "2025-26").head(5)
        assert rolling.iloc[-1]["pts_per_game"] == pytest.approx(last_five["pts"].mean())
        first = lab.players.game_log(TATUM, "2025-26").iloc[-1]
        assert rolling.iloc[0]["pts_per_game"] == first["pts"]

    def test_full_spans_start_at_the_first_complete_one(self, lab: Lab) -> None:
        every = lab.players.rolling(TATUM, "2025-26", games=5)
        rolling = lab.players.rolling(TATUM, "2025-26", games=5, full_spans=True)
        assert len(rolling) == 12 and (rolling["games_played"] == 5).all()
        pd.testing.assert_frame_equal(rolling, every.iloc[4:].reset_index(drop=True))
        first_five = lab.players.game_log(TATUM, "2025-26").tail(5)  # the log is newest first
        assert rolling.iloc[0]["pts_per_game"] == pytest.approx(first_five["pts"].mean())
        # Sixteen games played: there is no span of twenty.
        assert len(lab.players.rolling(TATUM, "2025-26", games=20, full_spans=True)) == 0

    def test_availability(self, lab: Lab) -> None:
        availability = lab.players.availability("2025-26", team_games_back=20)
        row = availability.loc[TATUM]
        assert (row["team_id"], row["team_games"]) == (BOS, 20)
        assert 0 <= row["availability"] <= 1


class TestCompare:
    def test_side_by_side(self, lab: Lab) -> None:
        table = lab.players.table("2025-26", qualification=Qualification())
        result = lab.players.compare(table, [TATUM, BROWN], ["pts_per_game", "ts_pct", "tov_pct"])
        assert result["label"].tolist() == ["PPG", "PPG", "TS%", "TS%", "TOV%", "TOV%"]
        assert result["player_name"].tolist()[:2] == ["Jayson Tatum", "Jaylen Brown"]
        assert result["category"].tolist()[::2] == ["Scoring", "Scoring", "Creation"]
        tatum_ts = result[(result["metric"] == "ts_pct") & (result["player_id"] == TATUM)].iloc[0]
        assert tatum_ts["shown"] == f"{tatum_ts['value'] * 100:.1f}%"
        assert 0 < tatum_ts["percentile"] < 100

    def test_an_unknown_player_is_an_error(self, lab: Lab, table: PlayerTable) -> None:
        with pytest.raises(KeyError):
            lab.players.compare(table, [TATUM, 1], ["pts_per_game"])

    def test_metric_lookup(self, lab: Lab) -> None:
        assert lab.players.metric("ts_pct").label == "TS%"
        assert lab.players.metrics is PLAYER_METRICS


class TestValueInThePlayerViews:
    """Where a whole regular season has been valued, the player views carry the estimates."""

    def test_the_season_table_holds_the_value_services_numbers(self, lab: Lab, table) -> None:
        valued = lab.value.season("2025-26")
        for key in ("impact", "impact_offense", "impact_defense", "wins_added", "reliability"):
            assert (
                table.players[key].to_dict() == valued[key].reindex(table.players.index).to_dict()
            )
        assert [spec.key for spec in table.metrics.in_category("Value")] == [
            "impact", "impact_offense", "impact_defense", "wins_added", "minutes_share",
            "reliability",
        ]  # fmt: skip

    def test_value_is_ranked_like_any_other_metric(self, table: PlayerTable) -> None:
        qualified = table.players[table.players["is_qualified"]]
        best = qualified["impact"].idxmax()
        assert table.percentiles.loc[best, "impact"] == table.percentiles["impact"].max()
        assert table.percentiles.loc[~table.players["is_qualified"], "impact"].isna().all()

    @pytest.mark.parametrize(
        "view",
        [
            {"season_type": "playoffs"},
            {"window": Window(last_games=10)},
        ],
        ids=["playoffs", "a span of games"],
    )
    def test_only_a_whole_regular_season_is_valued(self, lab: Lab, view: dict) -> None:
        narrowed = lab.players.table("2025-26", **view)
        assert "impact" not in narrowed.players.columns
        assert "impact" not in narrowed.metrics

    def test_a_profile_carries_the_players_value_history(self, lab: Lab) -> None:
        profile = lab.players.profile(TATUM)
        pd.testing.assert_frame_equal(profile.value, lab.value.player(TATUM))
        assert profile.metrics is PLAYER_AND_VALUE_METRICS
        regular = profile.seasons[profile.seasons["season_type"] == "regular"].iloc[0]
        playoffs = profile.seasons[profile.seasons["season_type"] == "playoffs"]
        assert regular["impact"] == profile.value.set_index("season").at["2025-26", "impact"]
        assert playoffs["impact"].isna().all() and playoffs["wins_added"].isna().all()
        assert len(profile.seasons) == len(lab.read("player_seasons", {"player_id": TATUM}))

    def test_a_player_who_never_played_has_no_value(self, lab: Lab) -> None:
        profile = lab.players.profile(ABDELNABY)
        assert profile.value.empty and profile.seasons.empty


class TestRolesInThePlayerViews:
    def test_the_table_names_each_players_main_role_and_every_role(self, lab: Lab, table) -> None:
        filled = lab.value.roles("2025-26")
        players = table.players
        assert players.loc[TATUM, ["role", "roles"]].tolist() == filled.loc[TATUM].tolist()
        assert players.loc[TATUM, "role"] == "Primary Creator"
        with_roles = players[players["role"].notna()]
        assert set(with_roles.index) == set(filled.index)
        assert with_roles["roles"].to_dict() == filled["roles"].to_dict()
        assert pd.isna(players.loc[TOWNS, "role"]) and pd.isna(players.loc[TOWNS, "roles"])

    def test_a_role_is_not_a_metric(self, table: PlayerTable) -> None:
        assert "role" not in table.metrics and "roles" not in table.metrics
        assert "role" not in table.percentiles.columns

    def test_a_role_is_the_seasons_whatever_part_of_it_is_looked_at(self, lab: Lab) -> None:
        # Roles are given for a whole regular season. A span of games or the playoffs
        # shows the same player in the same role.
        playoffs = lab.players.table("2025-26", season_type="playoffs").players
        recent = lab.players.table("2025-26", window=Window(last_games=10)).players
        assert playoffs.loc[TATUM, "role"] == recent.loc[TATUM, "role"] == "Primary Creator"

    def test_on_the_invented_league_too(self, value_lab: Lab) -> None:
        table = value_lab.players.table("2006-07")
        filled = value_lab.value.roles("2006-07")
        assert len(filled) > 20
        assert table.players["role"].dropna().to_dict() == filled["role"].to_dict()
        assert table.players["roles"].dropna().to_dict() == filled["roles"].to_dict()
