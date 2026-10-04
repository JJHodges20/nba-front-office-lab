"""Choosing a team or a player by clicking a table row.

``AppTest`` cannot click a row, so a click is imitated the way a browser delivers it:
the table comes back with a row selected - but only under the key it had when the row
was clicked. That is the point of the design: once a click has been acted on the table
is drawn under a new key with nothing selected, so an old click cannot go on overruling
what is chosen in the sidebar afterwards. The same journey was clicked through in a real
browser at the milestone gate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from front_office.config import load_settings
from front_office.services import Lab
from tests.helpers import BOS, BROWN, BRUNSON, NYK, TATUM
from tests.ui.conftest import TIMEOUT, texts
from wb import state
from wb.views import players as players_view


@pytest.fixture
def click(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Select a row of a clickable table: ``click("standings_East", row=0)``."""

    drawn = st.dataframe

    def select(table: str, *, row: int = 0) -> None:
        def dataframe(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            event = drawn(*args, **kwargs)
            if kwargs.get("on_select") == "rerun" and kwargs.get("key") == f"{table}_0":
                return SimpleNamespace(selection=SimpleNamespace(rows=[row], columns=[]))
            return event

        monkeypatch.setattr(st, "dataframe", dataframe)

    return select


def chosen(opened: AppTest) -> state.Filters:
    return opened.session_state[state.CURRENT]


def table(opened: AppTest, key: str):  # type: ignore[no-untyped-def]
    """A table as it was last drawn, by the key it was drawn under."""
    return next(frame.value for frame in opened.dataframe if frame.key == key)


class TestChoosing:
    def test_a_choice_is_parked_applied_and_the_tables_get_new_keys(
        self, open_at, plain_home: Path
    ) -> None:
        def click_once() -> None:
            import streamlit as st

            from wb import data, state

            state.sidebar(data.status())
            st.session_state.setdefault("keys", []).append(state.table_key("standings_East"))
            if not st.session_state.get("clicked"):
                st.session_state["clicked"] = True
                state.choose(team_id=1610612738, player_id=1628369)

        open_at(plain_home)
        opened = AppTest.from_function(click_once, default_timeout=TIMEOUT)
        opened.run()
        assert not opened.exception
        assert (chosen(opened).team_id, chosen(opened).player_id) == (BOS, TATUM)
        assert opened.session_state["keys"] == ["standings_East_0", "standings_East_1"]
        assert state.PENDING not in opened.session_state

    def test_before_any_click_the_key_ends_in_zero(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "teams")
        assert opened.dataframe[0].key == "teams_table_Overview_0"


class TestClicks:
    def test_a_standings_row_makes_that_team_the_subject(
        self, page, click, plain_home: Path
    ) -> None:
        click("standings_East", row=1)
        opened = page(plain_home, "league")
        with Lab(load_settings(plain_home)) as lab:
            standings = lab.league.standings("2025-26")
        east = standings[standings["conference"] == "East"]
        assert chosen(opened).team_id == east["team_id"].iloc[1] == BOS
        # The table is back under a new key with nothing selected, so the click is spent.
        assert len(table(opened, "standings_East_1")) == 15

    def test_a_click_does_not_outlive_a_later_choice_in_the_sidebar(
        self, page, click, plain_home: Path
    ) -> None:
        click("standings_East", row=1)
        opened = page(plain_home, "league")
        assert chosen(opened).team_id == BOS
        opened.sidebar.selectbox[1].set_value(NYK).run()
        assert not opened.exception
        assert chosen(opened).team_id == NYK
        opened.sidebar.selectbox[1].set_value(None).run()
        assert chosen(opened).team_id is None

    def test_a_team_row_opens_that_team(self, page, click, plain_home: Path) -> None:
        click("teams_table_Overview", row=0)
        opened = page(plain_home, "teams")
        with Lab(load_settings(plain_home)) as lab:
            best = lab.teams.table("2025-26").teams["net_rating"].idxmax()
        assert chosen(opened).team_id == best
        assert "Oklahoma City Thunder" in [heading.value for heading in opened.subheader]

    def test_a_player_row_opens_that_players_profile(self, page, click, plain_home: Path) -> None:
        click("players_table_Overview", row=0)
        opened = page(plain_home, "players", players_qualified_only=False)
        listing = table(opened, "players_table_Overview_1")
        first = listing["player_name"].iloc[0]
        assert first in [heading.value for heading in opened.subheader]
        assert chosen(opened).player_id == BROWN and first == "Jaylen Brown"
        assert opened.session_state[players_view.TAB] == "Profile"

    def test_a_rotation_row_makes_that_player_the_subject(
        self, page, click, plain_home: Path
    ) -> None:
        click("team_rotation", row=0)
        opened = page(plain_home, "teams", **{state.TEAM: BOS})
        with Lab(load_settings(plain_home)) as lab:
            rotation = lab.teams.rotation(BOS, "2025-26")
        assert chosen(opened).player_id == rotation.index[0]
        assert chosen(opened).team_id == BOS

    def test_a_value_row_makes_that_player_the_subject(self, page, click, plain_home: Path) -> None:
        click("value_table", row=1)
        opened = page(plain_home, "value")
        with Lab(load_settings(plain_home)) as lab:
            season = lab.value.season("2025-26")
        assert chosen(opened).player_id == season.index[1]
        assert season["player_name"].iloc[1] in [heading.value for heading in opened.subheader]

    def test_a_row_of_a_role_makes_that_player_the_subject(
        self, page, click, plain_home: Path
    ) -> None:
        click("value_role_table_floor_spacer", row=0)
        opened = page(plain_home, "value", value_role="floor_spacer")
        with Lab(load_settings(plain_home)) as lab:
            players = lab.value.role_players("2025-26", "floor_spacer")
        assert chosen(opened).player_id == players.index[0]
        assert players["player_name"].iloc[0] == "Miles McBride"
        assert "Miles McBride" in [heading.value for heading in opened.subheader]

    def test_the_team_filter_does_not_shift_which_row_was_clicked(
        self, page, click, plain_home: Path
    ) -> None:
        click("value_role_table_floor_spacer", row=0)
        opened = page(plain_home, "value", value_role="floor_spacer", **{state.TEAM: BOS})
        with Lab(load_settings(plain_home)) as lab:
            players = lab.value.role_players("2025-26", "floor_spacer")
        first = players[players["team_id"] == BOS].index[0]
        assert chosen(opened).player_id == first != players.index[0]

    def test_a_fit_member_row_makes_that_player_the_subject(
        self, page, click, plain_home: Path
    ) -> None:
        click(f"fit_members_team_{BOS}", row=1)
        opened = page(plain_home, "fit", **{state.TEAM: BOS})
        with Lab(load_settings(plain_home)) as lab:
            members = lab.fit.team(BOS, "2025-26").members
        assert chosen(opened).player_id == members.index[1]
        assert chosen(opened).team_id == BOS

    def test_a_contract_row_makes_that_player_the_subject(
        self, page, click, contract_template: Path
    ) -> None:
        click("contracts_table", row=0)
        opened = page(contract_template, "contracts")
        listing = table(opened, "contracts_table_1")
        assert chosen(opened).player_id == BRUNSON
        assert listing["player_name"].iloc[0] == "Jalen Brunson"
        assert "make that player the subject of the Player Explorer" in texts(opened)


class TestTheProfileFollowsThePlayer:
    def test_without_a_player_the_listing_is_open(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "players")
        assert opened.session_state[players_view.TAB] == "Players"

    def test_arriving_with_a_player_opens_the_profile(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "players", **{state.PLAYER: TATUM})
        assert opened.session_state[players_view.TAB] == "Profile"

    def test_another_player_opens_the_profile_again(self, page, plain_home: Path) -> None:
        session = {state.PLAYER: TATUM, players_view.TAB: "Compare", players_view.SUBJECT: BRUNSON}
        opened = page(plain_home, "players", **session)
        assert opened.session_state[players_view.TAB] == "Profile"

    def test_the_same_player_leaves_the_tabs_alone(self, page, plain_home: Path) -> None:
        session = {state.PLAYER: TATUM, players_view.TAB: "Compare", players_view.SUBJECT: TATUM}
        opened = page(plain_home, "players", **session)
        assert opened.session_state[players_view.TAB] == "Compare"

    def test_clearing_the_player_returns_to_the_listing(self, page, plain_home: Path) -> None:
        session = {players_view.TAB: "Profile", players_view.SUBJECT: TATUM}
        opened = page(plain_home, "players", **session)
        assert opened.session_state[players_view.TAB] == "Players"

    def test_once_the_profile_has_opened_the_reader_can_leave_it(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "players", **{state.PLAYER: TATUM})
        assert opened.session_state[players_view.TAB] == "Profile"
        assert opened.session_state[players_view.SUBJECT] == TATUM
        # The reader opens another tab, and something else on the page makes it run again.
        for _ in range(2):
            opened.session_state[players_view.TAB] = "Compare"
            opened.run()
            assert not opened.exception
            assert opened.session_state[players_view.TAB] == "Compare"
