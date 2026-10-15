"""The workbench as a whole: its frame, its filters, and what it says before data exists."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from front_office.services import Window
from tests.helpers import BOS, TATUM
from tests.ui.conftest import APP, figures, texts
from wb import state

GROUPS = ("League", "Explore", "Build", "Forecast", "Ask", "System")
PAGE_TITLES = (
    "League Overview",
    "Winning Benchmarks",
    "Player Explorer",
    "Player Value",
    "Team Explorer",
    "Contract Explorer",
    "Analytics Lab",
    "Team Builder",
    "Roster Fit",
    "Roster Optimizer",
    "Postseason Outlook",
    "Scenario Simulator",
    "AI Research",
    "Ask the Docs",
    "Data Health",
)
"""The navigation's pages in its order: the top bar's, and the sidebar's fold of them."""


def tile_rows(opened: AppTest) -> list[str]:
    """The keys of a page's rows of headline tiles, in order: a keyed container's id ends with
    its key ("$$ID-<hash>-<key>")."""
    found: list[str] = []

    def walk(node) -> None:  # type: ignore[no-untyped-def]
        for child in getattr(node, "children", {}).values():
            ident = getattr(getattr(child, "proto", None), "id", "") or ""
            if "-tiles-" in ident:
                found.append(ident.split("-", 2)[2])
            walk(child)

    walk(opened.main)
    return found


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
        """UI polish P2: a source that needs nothing done is its state in a word, with what
        lies behind it - the file's own description - on hover. A source that needs something
        done keeps its line under the badge (the test above)."""
        opened = app(contract_template)
        (badge,) = [
            element
            for element in opened.sidebar.markdown
            if "Contract file: supplied" in element.value
        ]
        assert "invented for tests" in badge.proto.help
        captions = "\n".join(caption.value for caption in opened.sidebar.caption)
        assert "invented for tests" not in captions, "said once, on hover"

    def test_the_data_status_links_to_data_health(self, app, plain_home: Path) -> None:
        opened = app(plain_home)
        links = [link.proto.label for link in opened.sidebar.get("page_link")]
        assert links[0] == "Data Health"

    def test_every_page_is_folded_at_the_foot_of_the_sidebar(self, app, plain_home: Path) -> None:
        """UI polish P8 (decision D13): Streamlit draws an open top-bar menu after everything
        on the page, so its pages came last in the keyboard's order. The sidebar folds every
        page, in the navigation's groups and order, under the data status."""
        opened = app(plain_home)
        assert "All pages" in [block.label for block in opened.sidebar.status]
        links = [link.proto.label for link in opened.sidebar.get("page_link")]
        assert links == ["Data Health", *PAGE_TITLES]
        groups = [caption.value for caption in opened.sidebar.caption][-len(GROUPS) :]
        assert groups == list(GROUPS)

    def test_a_page_names_its_rows_of_tiles_afresh_each_run(self, app, plain_home: Path) -> None:
        """UI polish P3: the frame starts each run's count, so a row of tiles keeps its name -
        which the grid in wb/style.css hooks - from one run to the next."""
        opened = app(plain_home)
        first = tile_rows(opened)
        assert first and first[0] == "tiles-0"
        opened.run()
        assert tile_rows(opened) == first

    def test_the_frame_holds_nothing_streamlit_would_draw_by_itself(self) -> None:
        """Streamlit draws a bare expression in the main script on the page ("magic"). At P3 a
        string written as a note under a constant in app.py appeared above every title."""
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        bodies = [tree.body, *(node.body for node in ast.walk(tree) if isinstance(node, scopes))]
        drawn = [
            statement.lineno
            for body in bodies
            for position, statement in enumerate(body)
            if isinstance(statement, ast.Expr)
            and not isinstance(statement.value, ast.Call | ast.Await | ast.Yield | ast.YieldFrom)
            and not (position == 0 and isinstance(statement.value, ast.Constant))
        ]
        assert drawn == []

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
