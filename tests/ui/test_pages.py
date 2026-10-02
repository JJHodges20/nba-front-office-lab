"""Each page, drawn for real data: what it shows must be what the services return.

The projects are built from the fixture store: every team's 1996-97, 2012-13 and
2025-26 seasons, and player detail for Boston and New York in 2025-26.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from front_office.config import load_settings
from front_office.services import DEFAULT_QUALIFICATION, Lab, relationship
from tests.helpers import ABDELNABY, BOS, BROWN, NYK, PRITCHARD, TATUM, WHITE
from tests.ui.conftest import TIMEOUT, figures, texts
from wb import state
from wb.views import builder as builder_view

PAGES = ("league", "players", "teams", "contracts", "lab", "builder", "health")
STATES = {
    "default": {},
    "team": {state.TEAM: BOS},
    "player": {state.PLAYER: TATUM},
    "team and player": {state.TEAM: NYK, state.PLAYER: TATUM},
    "last ten games": {state.SPAN: "Last 10 games", state.TEAM: BOS, state.PLAYER: TATUM},
    "date range": {state.SPAN: state.DATE_RANGE, state.TEAM: BOS},
    "playoffs": {state.PHASE: "playoffs", state.TEAM: BOS, state.PLAYER: TATUM},
    "old season": {state.SEASON: "1996-97", state.TEAM: BOS},
    "old playoffs": {state.SEASON: "2012-13", state.PHASE: "playoffs"},
}


@pytest.mark.parametrize("name", PAGES)
@pytest.mark.parametrize("session", STATES.values(), ids=STATES.keys())
def test_every_page_draws_for_every_kind_of_filter(
    page, contract_template: Path, name: str, session: dict
) -> None:
    opened = page(contract_template, name, **session)
    assert len(opened.title) == 1
    assert not opened.error


@pytest.mark.parametrize("name", PAGES)
def test_every_page_draws_without_contract_data(page, plain_home: Path, name: str) -> None:
    opened = page(plain_home, name, **{state.TEAM: BOS, state.PLAYER: TATUM})
    assert len(opened.title) == 1 and not opened.error


def form(opened: AppTest):  # type: ignore[no-untyped-def]
    """The table under a form chart: one row for each span of games drawn."""
    return next(
        frame.value
        for frame in opened.dataframe
        if list(frame.value.columns[:2]) == ["game_date", "games_played"]
    )


class TestLeague:
    def test_headlines_are_the_league_averages_with_the_change_from_the_season_before(
        self, page, plain_home: Path
    ) -> None:
        shown = figures(page(plain_home, "league"))
        with Lab(load_settings(plain_home)) as lab:
            averages, changes = lab.league.averages(), lab.league.changes()
        assert shown["Offensive rating"] == (
            f"{averages.at['2025-26', 'off_rating']:.1f}",
            f"{changes.at['2025-26', 'off_rating']:+.1f} vs 2012-13",
        )
        assert shown["Offensive rating"][0] == "114.8"
        assert shown["3-point attempt rate"] == ("41.5%", "+17.2 pp vs 2012-13")
        assert list(shown) == [
            "Offensive rating",
            "Pace",
            "3-point attempt rate",
            "Effective FG%",
            "Points per game",
        ]

    def test_the_first_season_on_record_has_nothing_to_compare_with(
        self, page, plain_home: Path
    ) -> None:
        shown = figures(page(plain_home, "league", **{state.SEASON: "1996-97"}))
        assert shown["Pace"] == ("91.6", None)

    def test_a_full_season_shows_no_estimates(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league")
        badges = texts(opened)
        assert "Measured" in badges and "Derived" in badges
        assert "Estimate" not in badges
        assert [tab.label for tab in opened.tabs] == [
            "Standings",
            "Team efficiency",
            "League trends",
            "Postseason",
        ]

    def test_a_span_of_games_is_flagged_as_estimated(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "league", **{state.SPAN: "Last 10 games"})
        said = texts(opened)
        assert "Estimate" in said
        assert "estimates from box scores, not the league's published figures" in said
        assert "Standings always cover the full regular season." in said

    def test_the_postseason_tab_lists_the_bracket_and_the_champions(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "league")
        assert "2025-26 playoffs" in [heading.value for heading in opened.subheader]
        frames = [frame.value for frame in opened.dataframe]
        bracket = next(frame for frame in frames if "Home court" in frame.columns)
        assert len(bracket) == 15
        assert bracket["Result"].iloc[-1] == "New York Knicks won 4-1"
        assert bracket["Home court"].iloc[-1] == "San Antonio Spurs (2)"


class TestPlayers:
    def test_the_listing_says_who_percentiles_are_measured_against(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "players")
        with Lab(load_settings(plain_home)) as lab:
            table = lab.players.table("2025-26")
        assert (
            "Percentiles compare players with 20+ games and 300+ minutes: "
            f"{table.qualified_count} of 41 players." in texts(opened)
        )
        assert f"{table.qualified_count} players. Select a row" in texts(opened)

    def test_the_team_filter_narrows_the_listing(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "players", **{state.TEAM: BOS})
        listing = opened.dataframe[0].value
        assert set(listing["team"]) == {"BOS"}

    def test_a_profile_shows_the_players_own_numbers(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "players", **{state.PLAYER: TATUM})
        assert "Jayson Tatum" in [heading.value for heading in opened.subheader]
        shown = figures(opened)
        assert shown["Points per game"] == ("21.8", "Not ranked")
        assert shown["True shooting"] == ("54.1%", "Not ranked")
        assert "below the minimum games and minutes" in texts(opened)

    def test_over_a_span_the_thresholds_start_low_enough_to_rank(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "players", **{state.PLAYER: TATUM, state.SPAN: "Last 10 games"})
        assert "players with 3+ games and 30+ minutes" in texts(opened)
        value, context = figures(opened)["Points per game"]
        assert context.endswith("percentile")
        # A span has box-score metrics only: usage is the league's and is absent.
        assert "Usage" not in figures(opened)

    def test_form_is_drawn_from_full_spans_only(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "players", **{state.PLAYER: TATUM})
        spans = form(opened)
        assert len(spans) == 7 and set(spans["games_played"]) == {10}  # sixteen games played
        assert "Each point covers the 10 games ending on that date." in texts(opened)
        assert "Not enough games" not in texts(opened)

    def test_too_few_games_for_a_span_says_so_instead(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "players", **{state.PLAYER: TATUM, "player_trend_games": 20})
        said = texts(opened)
        assert "Not enough games" in said
        assert "Form over 20 games needs 20 games played in this season and phase." in said
        assert "Each point covers" not in said

    def test_a_season_without_player_detail_says_so(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "players", **{state.SEASON: "2012-13"})
        assert "No player statistics for 2012-13" in texts(opened)
        assert len(opened.dataframe) == 0

    def test_two_players_are_compared_side_by_side(self, page, plain_home: Path) -> None:
        session = {
            "compare_players_2025-26": [BROWN, PRITCHARD],
            "min_games_season": 0,
            "min_minutes_season": 0,
        }
        opened = page(plain_home, "players", **session)
        assert "Choose two or three players" not in texts(opened)
        assert "Nobody is ranked" not in texts(opened)

    def test_with_contracts_the_listing_carries_salaries(
        self, page, contract_template: Path
    ) -> None:
        opened = page(contract_template, "players", **{"players_qualified_only": False})
        listing = opened.dataframe[0].value
        assert {"salary", "salary_cap_pct", "years_remaining"} <= set(listing.columns)
        assert listing.set_index("player_name").at["Jayson Tatum", "salary"] == 40_000_000


class TestTeams:
    def test_without_a_team_every_team_is_listed(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "teams")
        assert len(opened.dataframe[0].value) == 30
        assert "Select a row, or pick a team in the sidebar" in texts(opened)

    def test_a_teams_headline_figures_and_ranks(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "teams", **{state.TEAM: BOS})
        assert "Boston Celtics" in [heading.value for heading in opened.subheader]
        assert figures(opened) == {
            "Record": ("56-26", "68.3% of games won"),
            "Net rating": ("+8.3", "4th of 30"),
            "Offensive rating": ("120.0", "2nd of 30"),
            "Defensive rating": ("111.7", "4th of 30"),
            "Pace": ("95.6", "30th of 30"),
        }
        assert "Finished 2nd in the East · Lost First Round" in texts(opened)

    def test_over_a_span_the_ratings_are_marked_as_estimates(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "teams", **{state.TEAM: BOS, state.SPAN: "Last 10 games"})
        shown = figures(opened)
        assert shown["Record"] == ("8-2", "80.0% of games won")
        assert shown["≈ Net rating"][0] == "+11.6"
        assert "Net rating" not in shown
        assert "They are marked ≈." in texts(opened)

    def test_the_playoffs_are_a_span_among_the_teams_that_played(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "teams", **{state.TEAM: BOS, state.PHASE: "playoffs"})
        shown = figures(opened)
        assert shown["Record"] == ("3-4", "42.9% of games won")
        assert shown["≈ Net rating"][1].endswith("of 16")

    def test_a_team_with_no_games_in_the_span_still_shows_its_history(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "teams", **{state.TEAM: BOS, state.PHASE: "playoffs"})
        assert "No games in this span" not in texts(opened)
        missed = page(plain_home, "teams", **{state.TEAM: 1610612764, state.PHASE: "playoffs"})
        said = texts(missed)
        assert "No games in this span" in said
        assert "Washington Wizards did not play in 2025-26 · Playoffs" in said
        assert "Every season on record" in said

    def test_form_is_drawn_from_full_spans_only(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "teams", **{state.TEAM: BOS})
        spans = form(opened)
        assert len(spans) == 73 and set(spans["games_played"]) == {10}
        assert "Each point covers the 10 games ending on that date." in texts(opened)
        # Boston played seven playoff games: no span of ten, three spans of five.
        playoffs = {state.TEAM: BOS, state.PHASE: "playoffs"}
        short = page(plain_home, "teams", **playoffs)
        assert "Form over 10 games needs 10 games played in this season and phase." in texts(short)
        five = page(plain_home, "teams", **playoffs, team_form_games=5)
        assert len(form(five)) == 3

    def test_payroll_needs_contracts(self, page, plain_home: Path, contract_template) -> None:
        without = page(plain_home, "teams", **{state.TEAM: BOS})
        assert "No contract data" in texts(without)
        with_contracts = page(contract_template, "teams", **{state.TEAM: BOS})
        assert "Payroll in 2026-27" in texts(with_contracts)
        assert "No contract data" not in texts(with_contracts)


class TestContracts:
    def test_without_a_contract_file_the_page_says_how_to_add_one(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "contracts")
        assert "No contract data yet" in texts(opened)
        assert any("fol contracts import" in code.value for code in opened.code)
        # The cap rules need no contract file, and are shown regardless.
        assert "Cap rules" in [heading.value for heading in opened.subheader]
        assert not figures(opened)

    def test_what_the_file_adds_up_to(self, page, contract_template: Path) -> None:
        opened = page(contract_template, "contracts")
        assert figures(opened) == {
            "Contracts": ("11", "10 players"),
            "Teams covered": ("2 of 30", "The rest: payroll unknown"),
            "Salaries owed": ("$301.6M", "All contracts"),
            "Dead money": ("$7.0M", "Owed to waived players"),
        }

    def test_the_source_is_stated_wherever_salaries_are(
        self, page, contract_template: Path
    ) -> None:
        said = texts(page(contract_template, "contracts"))
        assert "Source as stated at import: invented for tests, current as of Oct 01, 2026" in said
        assert "1 salary row(s) in the file name no team" in said

    def test_the_team_filter_narrows_the_contract_list(self, page, contract_template: Path) -> None:
        opened = page(contract_template, "contracts", **{state.TEAM: BOS})
        listing = next(
            frame.value for frame in opened.dataframe if "years_remaining" in frame.value.columns
        )
        assert set(listing["team"]) == {"BOS"} and len(listing) == 4


class TestLab:
    def test_the_correlation_shown_is_the_labs(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "lab")
        with Lab(load_settings(plain_home)) as lab:
            table = lab.players.table("2025-26", qualification=DEFAULT_QUALIFICATION)
            qualified = table.players[table.players["is_qualified"]]
            expected = relationship(qualified, "usage_pct", "ts_pct")
        shown = figures(opened)
        assert shown["Players"][0] == str(expected.sample)
        assert shown["Linear correlation"][0] == f"{expected.pearson:+.2f}"
        assert shown["Rank correlation"][0] == f"{expected.spearman:+.2f}"
        assert "does not show that one thing causes the other" in texts(opened)

    def test_teams_can_be_studied_instead(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "lab", lab_subject="Teams")
        assert figures(opened)["Teams"][0] == "30"

    def test_a_season_without_players_studies_teams(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "lab", **{state.SEASON: "1996-97"})
        assert figures(opened)["Teams"][0] == "29"

    def test_history_makes_no_prediction(self, page, plain_home: Path) -> None:
        said = texts(page(plain_home, "lab"))
        assert "**3 champions** in colour against **86 other team-seasons** in gray." in said
        assert "nothing here predicts a title" in said

    def test_the_glossary_lists_every_metric(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "lab")
        glossary = next(
            frame.value for frame in opened.dataframe if "Definition" in frame.value.columns
        )
        assert len(glossary) == 90
        assert set(glossary["Group"]) == {"Player metrics", "Team metrics", "Roster indicators"}
        assert "90 metrics." in texts(opened)

    def test_the_glossary_can_be_searched(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "lab", lab_glossary_search="true shooting")
        glossary = next(
            frame.value for frame in opened.dataframe if "Definition" in frame.value.columns
        )
        assert 0 < len(glossary) < 10
        assert all("true shooting" in name.lower() for name in glossary["Name"])

    def test_a_search_of_several_words_needs_every_one_of_them(
        self, page, plain_home: Path
    ) -> None:
        def found(search: str):  # type: ignore[no-untyped-def]
            opened = page(plain_home, "lab", lab_glossary_search=search)
            return next(
                frame.value for frame in opened.dataframe if "Definition" in frame.value.columns
            )

        both, offensive, rebound = found("offensive rebound"), found("offensive"), found("rebound")
        assert 0 < len(both) < min(len(offensive), len(rebound))
        entries = (both["Metric"] + " " + both["Name"] + " " + both["Definition"]).str.lower()
        assert entries.str.contains("offensive").all() and entries.str.contains("rebound").all()


@pytest.fixture
def roster(scratch_home: Path) -> int:
    """Pritchard, Brown and Tatum start; White is on the bench on an assumed 28M."""
    with Lab(load_settings(scratch_home)) as lab:
        roster_id = lab.builder.create("Test roster")
        lab.builder.add_player(roster_id, TATUM, slot="SF")
        lab.builder.add_player(roster_id, BROWN, slot="SG")
        lab.builder.add_player(roster_id, PRITCHARD, slot="PG")
        lab.builder.add_player(roster_id, WHITE, assumed_salary=28_000_000)
    return roster_id


def stored(home: Path, roster_id: int):  # type: ignore[no-untyped-def]
    with Lab(load_settings(home)) as lab:
        return lab.builder.summary(roster_id)


class TestBuilder:
    def test_with_no_rosters_it_offers_to_create_one(self, page, scratch_home: Path) -> None:
        opened = page(scratch_home, "builder")
        assert "No rosters yet" in texts(opened)
        assert [button.label for button in opened.button] == ["Create roster"]

    def test_creating_a_roster_from_the_form(self, page, scratch_home: Path) -> None:
        opened = page(scratch_home, "builder")
        opened.text_input[0].set_value("Plan A")
        opened.button[0].click().run()
        assert not opened.exception
        with Lab(load_settings(scratch_home)) as lab:
            rosters = lab.builder.rosters()
        assert rosters["name"].tolist() == ["Plan A"]
        assert (rosters["stats_season"][0], rosters["payroll_season"][0]) == ("2025-26", "2026-27")
        assert figures(opened)["Players"] == ("0", "Teams carry 14 to 15")

    def test_another_roster_can_be_created_beside_the_first_and_is_opened(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        opened = page(scratch_home, "builder")
        opened.text_input[0].set_value("Plan B")
        create = next(button for button in opened.button if button.label == "Create roster")
        create.click().run()
        assert not opened.exception, [error.value for error in opened.exception]
        with Lab(load_settings(scratch_home)) as lab:
            rosters = lab.builder.rosters().set_index("name")
        assert set(rosters.index) == {"Test roster", "Plan B"}
        assert opened.session_state[builder_view.SELECTED] == rosters.at["Plan B", "roster_id"]
        assert builder_view.CREATED not in opened.session_state
        assert figures(opened)["Players"] == ("0", "Teams carry 14 to 15")

    def test_deleting_a_roster_needs_a_tick_and_falls_back_to_another(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        with Lab(load_settings(scratch_home)) as lab:
            other = lab.builder.create("Plan B")
        opened = page(scratch_home, "builder", **{builder_view.SELECTED: other})
        delete = next(button for button in opened.button if button.label == "Delete roster")
        assert delete.disabled
        confirm = next(box for box in opened.checkbox if box.label.startswith("I want to delete"))
        confirm.check().run()
        delete = next(button for button in opened.button if button.label == "Delete roster")
        assert not delete.disabled
        delete.click().run()
        assert not opened.exception, [error.value for error in opened.exception]
        with Lab(load_settings(scratch_home)) as lab:
            assert lab.builder.rosters()["name"].tolist() == ["Test roster"]
        assert opened.session_state[builder_view.SELECTED] == roster
        assert figures(opened)["Players"][0] == "4"

    def test_a_roster_without_a_name_is_refused_and_says_why(
        self, page, scratch_home: Path
    ) -> None:
        opened = page(scratch_home, "builder")
        opened.button[0].click().run()
        assert [error.value for error in opened.error] == ["a roster needs a name"]
        with Lab(load_settings(scratch_home)) as lab:
            assert lab.builder.rosters().empty

    def test_what_a_roster_costs(self, page, scratch_home: Path, roster: int) -> None:
        opened = page(scratch_home, "builder")
        assert figures(opened) == {
            "Players": ("4", "Teams carry 14 to 15"),
            "Payroll": ("$105.0M", "1 assumed"),
            "Share of cap": ("63.7%", "of $165.0M"),
            "Cap room": ("$60.0M", "Under the cap"),
            "Tax room": ("$95.4M", "Under the tax"),
            "Line crossed": ("None", "Below the floor"),
        }

    def test_the_roster_is_measured_against_the_roster_rules(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        said = texts(page(scratch_home, "builder"))
        assert "4 players: 10 short of the 14 a team must generally carry in season." in said
        assert "No starter at PF, C." in said
        assert "Every player has a salary." in said
        assert "it does not rank or recommend players" in said

    def test_every_row_says_where_its_salary_comes_from(
        self, scratch_home: Path, roster: int
    ) -> None:
        with Lab(load_settings(scratch_home)) as lab:
            lab.builder.add_player(roster, ABDELNABY)
            summary = lab.builder.summary(roster)
            table = builder_view.roster_table(summary.players, lab.players.metrics)
        assert table["salary_source"].to_dict() == {
            PRITCHARD: "Contract file",
            BROWN: "Contract file",
            TATUM: "Contract file",
            WHITE: "Your assumption",
            ABDELNABY: "No salary",
        }
        assert table.loc[WHITE, "salary"] == "$28,000,000"
        assert table.loc[WHITE, "assumed_salary"] == 28_000_000
        assert table.loc[ABDELNABY, "salary"] == "—"
        assert table.loc[TATUM, "pts_per_game"] == "21.8"
        assert not table["remove"].any()
        assert set(builder_view.EDITABLE) < set(table.columns)

    def test_a_payroll_over_the_lines_says_which(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        with Lab(load_settings(scratch_home)) as lab:
            lab.builder.assume_salary(roster, TATUM, 100_000_000)
            lab.builder.assume_salary(roster, BROWN, 100_000_000)
        shown = figures(page(scratch_home, "builder"))
        assert shown["Payroll"] == ("$235.0M", "3 assumed")
        assert shown["Cap room"] == ("Over by $70.0M", "Over it")
        assert shown["Line crossed"] == ("2nd apron", "Above the floor")

    def test_adding_a_player_from_the_form(self, page, scratch_home: Path, roster: int) -> None:
        opened = page(scratch_home, "builder")
        adder = next(box for box in opened.selectbox if box.label == "Add a player")
        adder.select(1628973)  # Jalen Brunson
        add = next(button for button in opened.button if button.label == "Add")
        add.click().run()
        assert not opened.exception and not opened.error
        summary = stored(scratch_home, roster)
        assert 1628973 in summary.players.index
        assert summary.players.loc[1628973, "slot"] == "BENCH"
        assert figures(opened)["Players"][0] == "5"

    def test_adding_without_choosing_a_player_is_refused(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        opened = page(scratch_home, "builder")
        next(button for button in opened.button if button.label == "Add").click().run()
        assert [error.value for error in opened.error] == ["Choose a player first."]
        assert len(stored(scratch_home, roster).players) == 4

    def test_indicators_set_the_roster_beside_the_league(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        opened = page(scratch_home, "builder")
        indicators = next(
            frame.value for frame in opened.dataframe if "Indicator" in frame.value.columns
        )
        summary = stored(scratch_home, roster)
        rows = indicators.set_index("Indicator")
        spec = summary.metrics["ts_pct"]
        assert rows.at[spec.name, "Roster"] == spec.format_value(summary.indicators["ts_pct"])
        assert rows.at[spec.name, "League"] == spec.format_value(summary.league["ts_pct"])
        assert rows.at["Players", "Roster"] == "4" and rows.at["Players", "League"] == "—"
        assert "It is not a projection of how they would play together" in texts(opened)

    def test_a_deleted_roster_does_not_strand_the_page(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        opened = page(scratch_home, "builder", **{builder_view.SELECTED: 999})
        assert opened.session_state[builder_view.SELECTED] == roster


def apply_edits(roster_id: int, before, after) -> None:  # type: ignore[no-untyped-def]
    """Save one round of table edits, as the roster table does when a cell changes."""
    import streamlit as st

    from wb import data, state
    from wb.views import builder

    state.sidebar(data.status())
    # Saving restarts the run; without this the restarted run would save again.
    if not st.session_state.get("saved"):
        st.session_state["saved"] = True
        builder._save_edits(roster_id, before, after)


@pytest.fixture
def save(open_at, scratch_home: Path):  # type: ignore[no-untyped-def]
    """Apply edits to the roster table of the scratch project."""

    def run(roster_id: int, before, after) -> None:  # type: ignore[no-untyped-def]
        open_at(scratch_home)
        kwargs = {"roster_id": roster_id, "before": before, "after": after}
        app = AppTest.from_function(apply_edits, kwargs=kwargs, default_timeout=TIMEOUT)
        app.run()
        assert not app.exception, [error.value for error in app.exception]

    return run


def table_state(home: Path, roster_id: int):  # type: ignore[no-untyped-def]
    """The editable columns of the roster table, twice: as shown, and to be edited."""
    players = stored(home, roster_id).players
    before = players[["slot", "assumed_salary"]].assign(remove=False)
    before["assumed_salary"] = before["assumed_salary"].astype("Float64")
    return before, before.copy()


class TestRosterEdits:
    """What typing into the roster table does, without a browser to type in."""

    def test_nothing_changed_means_nothing_written(self, save, scratch_home, roster) -> None:
        before, after = table_state(scratch_home, roster)
        updated = stored(scratch_home, roster).roster["updated_at"]
        save(roster, before, after)
        assert stored(scratch_home, roster).roster["updated_at"] == updated

    def test_a_new_slot_moves_the_player(self, save, scratch_home, roster) -> None:
        before, after = table_state(scratch_home, roster)
        after.loc[WHITE, "slot"] = "C"
        save(roster, before, after)
        white = stored(scratch_home, roster).players.loc[WHITE]
        assert (white["slot"], white["salary"]) == ("C", 28_000_000)

    def test_a_typed_salary_becomes_the_users_assumption(self, save, scratch_home, roster) -> None:
        before, after = table_state(scratch_home, roster)
        after.loc[TATUM, "assumed_salary"] = 45_000_000.0
        save(roster, before, after)
        tatum = stored(scratch_home, roster).players.loc[TATUM]
        assert (tatum["salary"], tatum["salary_source"], tatum["slot"]) == (
            45_000_000,
            "assumed",
            "SF",
        )

    def test_clearing_a_salary_returns_to_the_contract_file(
        self, save, scratch_home, roster
    ) -> None:
        before, after = table_state(scratch_home, roster)
        after.loc[WHITE, "assumed_salary"] = None
        save(roster, before, after)
        white = stored(scratch_home, roster).players.loc[WHITE]
        assert (white["salary"], white["salary_source"]) == (600_000, "contract")

    def test_a_ticked_row_is_removed_whatever_else_changed(
        self, save, scratch_home, roster
    ) -> None:
        before, after = table_state(scratch_home, roster)
        after.loc[BROWN, "remove"] = True
        after.loc[BROWN, "slot"] = "C"
        save(roster, before, after)
        assert BROWN not in stored(scratch_home, roster).players.index
        assert len(stored(scratch_home, roster).players) == 3

    def test_several_edits_are_saved_together(self, save, scratch_home, roster) -> None:
        before, after = table_state(scratch_home, roster)
        after.loc[WHITE, "slot"] = "PF"
        after.loc[PRITCHARD, "assumed_salary"] = 9_000_000.0
        after.loc[BROWN, "remove"] = True
        save(roster, before, after)
        players = stored(scratch_home, roster).players
        assert players.index.tolist() == [PRITCHARD, TATUM, WHITE]
        assert players.loc[WHITE, "slot"] == "PF"
        assert players.loc[PRITCHARD, "salary"] == 9_000_000


class TestHealth:
    def test_headlines_come_from_the_last_build(self, page, plain_home: Path) -> None:
        shown = figures(page(plain_home, "health"))
        with Lab(load_settings(plain_home)) as lab:
            build = lab.operations.latest_build()
        assert shown["Last build"] == ("#1", "Oct 01, 2026 12:00 UTC")
        assert shown["Rows loaded"] == (f"{build['rows_loaded']:,}", "in 9 seconds")
        assert shown["Check errors"] == (
            str(build["check_errors"]),
            f"{build['check_warnings']} warnings",
        )
        assert shown["Parts not built"] == ("0", "3 source notes")
        assert shown["Fetches failing"] == ("0", "Slices failing now")

    def test_each_source_has_a_state_in_words(self, page, plain_home: Path) -> None:
        said = texts(page(plain_home, "health"))
        assert "**stats.nba.com**" in said and "**Contract file**" in said
        assert "Not supplied" in said
        assert "No contract file has been imported" in said

    def test_an_imported_contract_file_is_supplied(self, page, contract_template: Path) -> None:
        said = texts(page(contract_template, "health"))
        assert "Supplied" in said
        assert "11 contracts for 10 players, current as of 2026-10-01" in said

    def test_what_is_missing_is_spelled_out(self, page, plain_home: Path) -> None:
        said = texts(page(plain_home, "health"))
        assert "Needs attention" in said and "Known limit" in said
        assert "**Contracts.** No contract data." in said
        assert "**Team statistics.** No team statistics for 27 seasons" in said
        assert "**Player statistics.** Player statistics cover 2025-26 to 2025-26" in said

    def test_each_gap_is_tagged_with_its_own_severity(self, page, plain_home: Path) -> None:
        said = texts(page(plain_home, "health"))
        with Lab(load_settings(plain_home)) as lab:
            gaps = lab.health.gaps()
        words = {"warning": "Needs attention", "info": "Known limit"}
        assert {gap.severity for gap in gaps} == set(words)
        for gap in gaps:
            assert f"{words[gap.severity]}] **{gap.area}.** {gap.message}" in said, gap.area

    def test_every_check_and_table_is_listed(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "health")
        frames = [frame.value for frame in opened.dataframe]
        checks = next(frame for frame in frames if "Requires" in frame.columns)
        tables = next(frame for frame in frames if "Domain" in frame.columns)
        assert len(checks) == 44 and set(checks["Result"]) == {"Passed", "Warning", "Error"}
        assert checks["Result"].iloc[0] != "Passed"
        assert len(tables) == 19
        assert tables.set_index("Table").at["team_seasons", "Rows"] == 89
        assert "No dataset slice is failing" in texts(opened)
