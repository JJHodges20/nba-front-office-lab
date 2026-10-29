"""Registering and signing in to the API: a password kept only as a bcrypt hash."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import bcrypt
import pytest

from front_office.config.api import load_api_settings
from front_office.config.settings import ENV_HOME
from front_office.domain.accounts import PASSWORD_BYTES, AccountRuleError, CitedSource
from front_office.services.accounts import (
    AccountNotFound,
    AccountService,
    NameTaken,
    project_accounts,
)

PASSWORD = "a long passphrase"
ROUNDS = 4  # bcrypt's least work, for speed; the API's own setting is in configs/api.yaml


@pytest.fixture
def accounts(tmp_path: Path) -> AccountService:
    return AccountService(tmp_path / "accounts.sqlite", rounds=ROUNDS)


def _stored_hash(accounts: AccountService, username: str) -> str:
    connection = sqlite3.connect(accounts.path)
    try:
        return connection.execute(
            "SELECT password_hash FROM api_users WHERE username = ?", (username,)
        ).fetchone()[0]
    finally:
        connection.close()


def test_a_password_is_kept_only_as_a_salted_hash(accounts: AccountService) -> None:
    accounts.register("first", PASSWORD)
    accounts.register("second", PASSWORD)
    first, second = _stored_hash(accounts, "first"), _stored_hash(accounts, "second")
    assert PASSWORD not in first
    assert first != second  # a salt of its own each
    assert first.startswith(f"$2b$0{ROUNDS}$")
    assert bcrypt.checkpw(PASSWORD.encode(), first.encode())


def test_register_keeps_the_name_in_lower_case(accounts: AccountService) -> None:
    user = accounts.register("  Analyst ", PASSWORD)
    assert user.username == "analyst"
    assert accounts.user(user.user_id) == user


def test_a_name_is_taken_whatever_its_case(accounts: AccountService) -> None:
    accounts.register("analyst", PASSWORD)
    with pytest.raises(NameTaken):
        accounts.register("ANALYST", "another passphrase")
    assert accounts.count() == 1


@pytest.mark.parametrize(("name", "password"), [("x", PASSWORD), ("analyst", "short")])
def test_the_rules_are_checked_before_anything_is_kept(
    accounts: AccountService, name: str, password: str
) -> None:
    with pytest.raises(AccountRuleError):
        accounts.register(name, password)
    assert accounts.count() == 0


def test_sign_in(accounts: AccountService) -> None:
    user = accounts.register("analyst", PASSWORD)
    assert accounts.authenticate("analyst", PASSWORD) == user
    assert accounts.authenticate("Analyst ", PASSWORD) == user
    assert accounts.authenticate("analyst", PASSWORD.upper()) is None
    assert accounts.authenticate("analyst", PASSWORD + " ") is None
    assert accounts.authenticate("nobody", PASSWORD) is None
    assert accounts.authenticate("analyst", "x" * (PASSWORD_BYTES + 1)) is None


def test_an_unknown_name_still_checks_a_hash(
    accounts: AccountService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So that how long a refusal takes says nothing about which names exist."""
    accounts.register("analyst", PASSWORD)
    checked: list[bytes] = []
    real = bcrypt.checkpw
    monkeypatch.setattr(
        bcrypt, "checkpw", lambda password, hashed: checked.append(hashed) or real(password, hashed)
    )
    assert accounts.authenticate("nobody", PASSWORD) is None
    assert accounts.authenticate("analyst", "wrong passphrase") is None
    assert len(checked) == 2
    assert checked[0].startswith(f"$2b$0{ROUNDS}$".encode())


def test_remove_deletes_the_user_and_their_questions(accounts: AccountService) -> None:
    user = accounts.register("analyst", PASSWORD)
    source = CitedSource(1, "docs/ROADMAP.md", "Roadmap", "docs/ROADMAP.md#roadmap", 0.3)
    asked = accounts.record_question(
        user.user_id, question="q", answer="a [1]", sources=[source], model="m", seconds=1.0
    )
    assert accounts.questions(user.user_id) == (asked,)
    assert accounts.question(user.user_id, asked.question_id) == asked
    assert accounts.remove(user.user_id) == 1
    with pytest.raises(AccountNotFound):
        accounts.user(user.user_id)
    assert accounts.authenticate("analyst", PASSWORD) is None


def test_the_workbench_signs_in_to_the_apis_own_accounts(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workbench's sign-in (decision 0020) reads the API's file and its settings, so one
    name and password serve both, and a sign-in lasts as long as a token."""
    monkeypatch.setenv(ENV_HOME, str(project))
    found = project_accounts()
    assert found.accounts.path == project / "data" / "api" / "accounts.sqlite"
    api = load_api_settings(project / "configs")
    assert found.sign_in_minutes == api.sign_in.token_minutes
    user = found.accounts.register("Analyst", "a long passphrase")
    assert found.accounts.authenticate("analyst", "a long passphrase") == user
