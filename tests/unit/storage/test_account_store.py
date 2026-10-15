"""The API's accounts file: two related tables, mapped with SQLAlchemy's ORM (decision 0019)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from front_office.domain.accounts import CitedSource
from front_office.domain.tables.accounts import API_QUESTIONS, API_USERS
from front_office.storage.accounts import (
    AccountNotFound,
    AccountStore,
    NameTaken,
    QuestionRow,
    UserRow,
)

SOURCE = CitedSource(1, "docs/ROADMAP.md", "Roadmap", "docs/ROADMAP.md#roadmap", 0.25)


class Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 15, 9, 0, 0)

    def __call__(self) -> datetime:
        self.moment += timedelta(seconds=1)
        return self.moment


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AccountStore]:
    with AccountStore(tmp_path / "api" / "accounts.sqlite", now=Clock()) as opened:
        yield opened


def _ask(store: AccountStore, user_id: int, question: str = "What is net rating?"):
    return store.add_question(
        user_id,
        question=question,
        answer="An answer [1].",
        sources=[SOURCE],
        model="m",
        seconds=2.5,
    )


def test_the_tables_are_made_from_their_contracts_and_related(store: AccountStore) -> None:
    with store.engine.connect() as connection:
        found = inspect(connection)
        for contract in (API_USERS, API_QUESTIONS):
            columns = [column["name"] for column in found.get_columns(contract.name)]
            assert columns == list(contract.column_names)
        (key,) = found.get_foreign_keys(API_QUESTIONS.name)
        unique = [index for index in found.get_indexes(API_USERS.name) if index["unique"]]
    assert key["referred_table"] == API_USERS.name
    assert key["constrained_columns"] == ["user_id"]
    assert key["options"]["ondelete"] == "CASCADE"
    assert [index["column_names"] for index in unique] == [["username"]]


def test_the_orm_relates_a_user_and_their_questions_both_ways() -> None:
    assert UserRow.questions.property.mapper.class_ is QuestionRow
    assert QuestionRow.user.property.mapper.class_ is UserRow
    assert UserRow.questions.property.back_populates == "user"


def test_a_user_is_created_and_read_back(store: AccountStore) -> None:
    made = store.create_user("analyst", "hash")
    assert made.user_id == 1
    assert made.created_at == datetime(2026, 10, 15, 9, 0, 1)
    assert store.user(1) == made
    assert store.sign_in_record("analyst") == (made, "hash")
    assert store.sign_in_record("nobody") is None
    assert store.count_users() == 1


def test_a_name_is_unique_in_the_database_itself(store: AccountStore) -> None:
    store.create_user("analyst", "hash")
    with pytest.raises(NameTaken, match="analyst"):
        store.create_user("analyst", "another hash")
    # Not only the store's check: the file refuses it too.
    with store.engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO api_users (username, password_hash, created_at) "
                "VALUES ('analyst', 'x', '2026-10-15')"
            )
        )
    assert store.count_users() == 1


def test_a_missing_user_is_not_found(store: AccountStore) -> None:
    with pytest.raises(AccountNotFound):
        store.user(7)
    with pytest.raises(AccountNotFound):
        store.delete_user(7)
    with pytest.raises(AccountNotFound):
        _ask(store, 7)
    with pytest.raises(AccountNotFound):
        store.questions(7)


def test_questions_are_kept_under_their_user_newest_first(store: AccountStore) -> None:
    first = store.create_user("first", "hash").user_id
    second = store.create_user("second", "hash").user_id
    older = _ask(store, first, "older")
    newer = _ask(store, first, "newer")
    theirs = _ask(store, second, "theirs")
    assert older.sources == (SOURCE,)
    assert older.seconds == 2.5
    assert [asked.question for asked in store.questions(first)] == ["newer", "older"]
    assert store.questions(first, limit=1) == (newer,)
    assert store.question(first, older.question_id) == older
    # Another user's question is not found, as if it did not exist.
    with pytest.raises(AccountNotFound):
        store.question(first, theirs.question_id)
    with pytest.raises(AccountNotFound):
        store.delete_question(first, theirs.question_id)
    store.delete_question(first, older.question_id)
    assert store.questions(first) == (newer,)


def test_deleting_a_user_deletes_their_questions_and_no_one_elses(store: AccountStore) -> None:
    gone = store.create_user("gone", "hash").user_id
    kept = store.create_user("kept", "hash").user_id
    _ask(store, gone)
    _ask(store, gone)
    _ask(store, kept)
    assert store.delete_user(gone) == 2
    with store.engine.connect() as connection:
        owners = connection.execute(text("SELECT user_id FROM api_questions")).scalars().all()
    assert owners == [kept]
    with pytest.raises(AccountNotFound):
        store.user(gone)


def test_the_foreign_key_refuses_a_question_without_its_user(store: AccountStore) -> None:
    with store.engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO api_questions (user_id, question, answer, sources, model, "
                "asked_at, seconds) VALUES (99, 'q', 'a', '[]', 'm', '2026-10-15', 1.0)"
            )
        )


def test_an_id_is_never_given_to_someone_else(store: AccountStore) -> None:
    # A token names its user by id: a deleted user's id reused would sign in the new user.
    old = store.create_user("old", "hash").user_id
    store.delete_user(old)
    new = store.create_user("new", "hash").user_id
    assert new != old


def test_the_file_is_released_when_the_store_closes(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    with AccountStore(path) as store:
        store.create_user("analyst", "hash")
    path.unlink()  # on Windows an open connection would keep the file locked
    assert not path.exists()
