"""Signing in to the workbench (decision 0020): nothing is drawn without a sign-in.

These tests sign in for real, against the project's own accounts - the file the API keeps -
so they work on private copies of a built project (``scratch_home``): registering writes it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from front_office.config import load_settings
from front_office.server.app import create_app
from front_office.services.accounts import project_accounts
from tests.ui.conftest import APP, TIMEOUT
from tests.ui.test_docs_page import _through
from tests.unit.server.conftest import FAST, PASSWORD, SECRET
from wb import api_client, signin
from wb.views import docs

NAME = "analyst"


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(button for button in app.button if button.label == label)


def _register(app: AppTest, name: str = NAME, password: str = PASSWORD) -> AppTest:
    app.text_input(key="signin_register_name").input(name)
    app.text_input(key="signin_register_password").input(password)
    _button(app, "Register and sign in").click()
    return app.run()


def _sign_in(app: AppTest, name: str = NAME, password: str = PASSWORD) -> AppTest:
    app.text_input(key="signin_name").input(name)
    app.text_input(key="signin_password").input(password)
    _button(app, "Sign in").click()
    return app.run()


def _signed_out_page(app: AppTest) -> bool:
    return [title.value for title in app.title] == ["NBA Front Office Lab"] and [
        tab.label for tab in app.tabs
    ] == ["Sign in", "Register"]


def _account_line(app: AppTest) -> list[str]:
    return [caption.value for caption in app.sidebar.caption if "Signed in as" in caption.value]


class TestSignedOut:
    def test_only_the_sign_in_page_is_drawn(self, app, plain_home: Path) -> None:
        opened = app(plain_home, signed_in=False)
        assert _signed_out_page(opened)
        # No menus, no filters, no data status, no figures: nothing of the lab.
        assert not opened.get("page_link")
        assert not opened.sidebar.selectbox
        assert not opened.metric
        assert not _account_line(opened)
        # Drawing the page reads no account: nothing is written to the project.
        assert not (plain_home / "data" / "api" / "accounts.sqlite").exists()

    def test_a_session_with_no_account_is_signed_out(self, open_at, scratch_home: Path) -> None:
        open_at(scratch_home)
        opened = AppTest.from_file(str(APP), default_timeout=TIMEOUT)
        opened.session_state[signin.USER_ID] = 42
        opened.session_state[signin.SINCE] = datetime.now(UTC).replace(tzinfo=None)
        opened.run()
        assert _signed_out_page(opened)
        assert "That account no longer exists" in opened.info[0].value


class TestSigningIn:
    def test_registering_signs_in_and_opens_the_lab(self, app, scratch_home: Path) -> None:
        opened = _register(app(scratch_home, signed_in=False))
        assert [title.value for title in opened.title] == ["League Overview"]
        assert opened.session_state[signin.USER] == NAME
        assert _account_line(opened) == [f"Signed in as **{NAME}**"]
        assert (scratch_home / "data" / "api" / "accounts.sqlite").is_file()
        # The API was not answering (the tests reach none): Ask the Docs will ask on its page.
        assert docs.TOKEN not in opened.session_state

    def test_signing_out_and_in_again(self, app, scratch_home: Path) -> None:
        opened = _register(app(scratch_home, signed_in=False))
        opened.sidebar.button(key="signin_sign_out").click()
        opened.run()
        assert _signed_out_page(opened)
        assert opened.info[0].value == "You are signed out."
        assert signin.USER_ID not in opened.session_state
        opened = _sign_in(opened)
        assert [title.value for title in opened.title] == ["League Overview"]

    def test_a_wrong_password_is_refused(self, app, scratch_home: Path) -> None:
        opened = _register(app(scratch_home, signed_in=False))
        opened.sidebar.button(key="signin_sign_out").click()
        opened.run()
        opened = _sign_in(opened, password="not the passphrase")
        assert _signed_out_page(opened)
        assert opened.error[0].value == "That name and password do not sign anyone in."
        assert signin.USER_ID not in opened.session_state

    @pytest.mark.parametrize(
        ("name", "password", "said"),
        [
            ("ab", PASSWORD, "A name must be 3 to 32 letters"),
            (NAME, "short", "A password needs at least 8 characters."),
        ],
    )
    def test_the_rules_for_a_name_and_a_password(
        self, app, scratch_home: Path, name: str, password: str, said: str
    ) -> None:
        opened = _register(app(scratch_home, signed_in=False), name, password)
        assert _signed_out_page(opened)
        assert opened.error[0].value.startswith(said)

    def test_a_name_that_is_taken(self, app, scratch_home: Path) -> None:
        opened = _register(app(scratch_home, signed_in=False))
        opened.sidebar.button(key="signin_sign_out").click()
        opened.run()
        opened = _register(opened, NAME.upper())
        assert opened.error[0].value == "That name is taken: choose another, or sign in."

    def test_a_sign_in_that_has_run_out(self, app, scratch_home: Path) -> None:
        opened = _register(app(scratch_home, signed_in=False))
        opened.session_state[signin.SINCE] = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            minutes=61
        )
        opened.run()
        assert _signed_out_page(opened)
        assert opened.info[0].value == "Your sign-in ran out after 60 minutes. Sign in again."

    def test_a_deleted_account_signs_out_on_the_next_click(self, app, scratch_home: Path) -> None:
        opened = _register(app(scratch_home, signed_in=False))
        project_accounts().accounts.remove(opened.session_state[signin.USER_ID])
        opened.run()
        assert _signed_out_page(opened)
        assert "That account no longer exists" in opened.info[0].value


def test_the_api_is_signed_in_too_when_it_answers(
    app, scratch_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One name and password for both: Ask the Docs opens signed in."""
    client = TestClient(create_app(load_settings(scratch_home), api=FAST, secret=SECRET))
    monkeypatch.setattr(
        api_client, "connect", lambda: api_client.LabApi("http://testserver", send=_through(client))
    )
    opened = _register(app(scratch_home, signed_in=False))
    token = opened.session_state[docs.TOKEN]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == NAME
