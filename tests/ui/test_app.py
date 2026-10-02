"""The workbench as a whole: its frame, its filters, and what it says before data exists."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from front_office.services import Window
from tests.helpers import BOS, TATUM
from tests.ui.conftest import figures, texts
from wb import state


class TestFrame:
    def test_it_opens_on_the_league_overview(self, app, plain_home: Path) -> None:
        opened = app(plain_home)
        assert [title.value for title in opened.title] == ["League Overview"]
        assert "Offensive rating" in figures(opened)

    def test_the_global_filters_are_in_the_sidebar(self, app, plain_home: Path) -> None:
        opened = app(plain_home)
        labels = [box.label for box in opened.sidebar.selectbox]
        assert labels == ["Season", "Team", "Player", "Comparison window"]
        assert [control.label for control in opened.sidebar.segmented_control] == ["Phase"]

    def test_data_status_is_shown_on_every_page(self, app, plain_home: Path) -> None:
        opened = app(plain_home)
        sidebar = "\n".join(element.value for element in opened.sidebar.markdown)
        assert "stats.nba.com:" in sidebar
        assert "Contract file: not supplied" in sidebar
        captions = [caption.value for caption in opened.sidebar.caption]
        assert any(caption.startswith("Build 1, Oct 01, 2026 12:00 UTC") for caption in captions)
        assert any("No contract file has been imported" in caption for caption in captions)

    def test_an_imported_contract_file_is_reported_as_supplied(
        self, app, contract_template: Path
    ) -> None:
        opened = app(contract_template)
        sidebar = "\n".join(element.value for element in opened.sidebar.markdown)
        assert "Contract file: supplied" in sidebar
        captions = "\n".join(caption.value for caption in opened.sidebar.caption)
        assert "invented for tests" in captions

    def test_before_any_data_it_says_how_to_get_some(self, app, project: Path) -> None:
        opened = app(project)
        assert [title.value for title in opened.title] == ["NBA Front Office Lab"]
        assert "No data has been built yet" in texts(opened)
        assert [code.value for code in opened.code] == ["fol refresh"]
        assert len(opened.sidebar.selectbox) == 0


class TestFilters:
    def test_defaults_are_the_newest_season_in_full(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league")
        filters = opened.session_state[state.CURRENT]
        assert (filters.season, filters.season_type) == ("2025-26", "regular")
        assert filters.team_id is None and filters.player_id is None
        assert filters.window == Window() and filters.has_players
        assert filters.build == 1
        assert filters.payroll_season is None
        assert filters.scope == "2025-26 · Regular season · Full season"

    def test_every_season_with_team_data_is_offered(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league")
        season = opened.sidebar.selectbox[0]
        assert list(season.options) == ["2025-26", "2012-13", "1996-97"]

    def test_with_contracts_the_payroll_season_is_the_files_first(
        self, page, contract_template: Path
    ) -> None:
        opened = page(contract_template, "league")
        assert opened.session_state[state.CURRENT].payroll_season == "2026-27"

    def test_a_choice_made_on_a_page_is_applied_before_the_filters_are_drawn(
        self, page, plain_home: Path
    ) -> None:
        pending = {state.TEAM: BOS, state.PLAYER: TATUM}
        opened = page(plain_home, "league", **{state.PENDING: pending})
        filters = opened.session_state[state.CURRENT]
        assert (filters.team_id, filters.player_id) == (BOS, TATUM)
        assert state.PENDING not in opened.session_state

    def test_a_player_who_did_not_play_that_season_is_dropped(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league", **{state.PLAYER: 76001})
        assert opened.session_state[state.CURRENT].player_id is None

    def test_an_unknown_team_or_season_falls_back(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league", **{state.TEAM: 7, state.SEASON: "1950-51"})
        filters = opened.session_state[state.CURRENT]
        assert filters.team_id is None and filters.season == "2025-26"

    def test_a_season_without_player_data_disables_the_player_filter(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "league", **{state.SEASON: "2012-13", state.PLAYER: TATUM})
        filters = opened.session_state[state.CURRENT]
        assert not filters.has_players and filters.player_id is None
        player = opened.sidebar.selectbox[2]
        assert player.disabled and player.help.startswith("There are no player statistics")

    def test_a_span_of_recent_games(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league", **{state.SPAN: "Last 10 games"})
        filters = opened.session_state[state.CURRENT]
        assert filters.window == Window(last_games=10)
        assert filters.scope == "2025-26 · Regular season · Last 10 games"

    def test_a_date_range_starts_as_the_whole_season(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league", **{state.SPAN: state.DATE_RANGE})
        window = opened.session_state[state.CURRENT].window
        assert (window.start, window.end) == (date(2025, 10, 21), date(2026, 4, 12))
        assert [picker.label for picker in opened.sidebar.date_input] == ["Dates"]

    def test_the_playoffs(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league", **{state.PHASE: "playoffs"})
        filters = opened.session_state[state.CURRENT]
        assert filters.season_type == "playoffs" and not filters.is_regular_season
        assert filters.scope == "2025-26 · Playoffs · Full season"
