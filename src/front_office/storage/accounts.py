"""``data/api/accounts.sqlite``: the API's users and the questions each one asked
(decision 0019).

A file of its own, which no build touches. Its two tables are made from the contracts in
``domain/tables/accounts.py`` and mapped with SQLAlchemy's ORM: a user has questions, a
question has its user, and deleting a user deletes their questions - in the database by
the foreign key, and in a session by the relationship's cascade. A name is unique in the
database itself, so two people registering one name at the same moment cannot both have
it. Ids are never handed out twice: a token names its user by id, and a deleted user's id
given to someone new would sign that person in as them.

The file is not versioned yet: the first change to these contracts adds a version table, the
way the research store has one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from sqlalchemy import Engine, Index, MetaData, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship, sessionmaker

from front_office.domain.accounts import (
    AskedQuestion,
    CitedSource,
    User,
    sources_from_json,
    sources_to_json,
)
from front_office.domain.tables import ACCOUNT_TABLES
from front_office.domain.tables.accounts import API_QUESTIONS, API_USERS
from front_office.storage.database import (
    LOCK_TIMEOUT_SECONDS,
    StorageError,
    configure_connections,
)
from front_office.storage.schema import build_tables

METADATA = MetaData()
TABLES = build_tables(METADATA, ACCOUNT_TABLES, enforce_references=True, never_reuse_ids=True)
# A contract has no unique columns; the one this store needs is added here.
UNIQUE_NAME = Index(f"ux_{API_USERS.name}_username", TABLES[API_USERS.name].c.username, unique=True)


class AccountNotFound(StorageError):
    """No user with that id or name, or no question of theirs with that id."""


class NameTaken(StorageError):
    """Another user has that name already."""


class _Mapped(DeclarativeBase):
    metadata = METADATA


class UserRow(_Mapped):
    """A row of ``api_users``. The columns come from the table, so from its contract."""

    __table__ = TABLES[API_USERS.name]

    user_id: Mapped[int]
    username: Mapped[str]
    password_hash: Mapped[str]
    created_at: Mapped[datetime]
    questions: Mapped[list[QuestionRow]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        # The foreign key deletes them with the user; they need not be read first.
        passive_deletes=True,
        order_by=TABLES[API_QUESTIONS.name].c.question_id,
    )


class QuestionRow(_Mapped):
    """A row of ``api_questions``: one question, its answer, and the user who asked."""

    __table__ = TABLES[API_QUESTIONS.name]

    question_id: Mapped[int]
    user_id: Mapped[int]
    question: Mapped[str]
    answer: Mapped[str]
    sources: Mapped[str]
    model: Mapped[str]
    asked_at: Mapped[datetime]
    seconds: Mapped[float]
    user: Mapped[UserRow] = relationship(back_populates="questions")


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _user(row: UserRow) -> User:
    return User(user_id=row.user_id, username=row.username, created_at=row.created_at)


def _asked(row: QuestionRow) -> AskedQuestion:
    return AskedQuestion(
        question_id=row.question_id,
        user_id=row.user_id,
        question=row.question,
        answer=row.answer,
        sources=sources_from_json(row.sources),
        model=row.model,
        asked_at=row.asked_at,
        seconds=row.seconds,
    )


class AccountStore:
    """The accounts file. Open it in a ``with`` block: on Windows an open connection keeps
    the file locked."""

    def __init__(self, path: Path, *, now: Callable[[], datetime] = _utc_now) -> None:
        self.path = Path(path)
        self._now = now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path.as_posix()}", connect_args={"timeout": LOCK_TIMEOUT_SECONDS}
        )
        configure_connections(self.engine)
        # Rows are turned into the domain's records inside their session; nothing needs
        # reading again once it is committed.
        self._session = sessionmaker(self.engine, expire_on_commit=False)
        try:
            with self.engine.begin() as connection:
                METADATA.create_all(connection)
        except BaseException:
            self.engine.dispose()
            raise

    def __enter__(self) -> AccountStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.dispose()

    def dispose(self) -> None:
        self.engine.dispose()

    # --- users -----------------------------------------------------------------------------

    def create_user(self, username: str, password_hash: str) -> User:
        """Add a user. The name is kept as given: the caller has checked and normalised it."""
        row = UserRow(username=username, password_hash=password_hash, created_at=self._now())
        try:
            with self._session.begin() as session:
                session.add(row)
        except IntegrityError as error:
            # SQLite names the column: "UNIQUE constraint failed: api_users.username".
            if f"{API_USERS.name}.username" in str(error.orig):
                raise NameTaken(f"the name {username!r} is taken") from None
            raise StorageError(str(error.orig)) from error
        return _user(row)

    def user(self, user_id: int) -> User:
        with self._session() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise AccountNotFound(f"no user with id {user_id}")
            return _user(row)

    def sign_in_record(self, username: str) -> tuple[User, str] | None:
        """The user with this name and their password hash, to check a sign-in against; or
        ``None`` when nobody has the name."""
        with self._session() as session:
            row = session.scalars(select(UserRow).where(UserRow.username == username)).first()
            return None if row is None else (_user(row), row.password_hash)

    def count_users(self) -> int:
        with self._session() as session:
            return int(session.scalar(select(func.count()).select_from(UserRow)) or 0)

    def delete_user(self, user_id: int) -> int:
        """Delete a user and every question they asked. Returns how many questions went."""
        with self._session.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise AccountNotFound(f"no user with id {user_id}")
            asked = session.scalar(
                select(func.count()).select_from(QuestionRow).where(QuestionRow.user_id == user_id)
            )
            session.delete(row)
        return int(asked or 0)

    # --- questions -------------------------------------------------------------------------

    def add_question(
        self,
        user_id: int,
        *,
        question: str,
        answer: str,
        sources: Sequence[CitedSource],
        model: str,
        seconds: float,
    ) -> AskedQuestion:
        """Keep a question a user asked, with the answer it got, under that user."""
        with self._session.begin() as session:
            user = session.get(UserRow, user_id)
            if user is None:
                raise AccountNotFound(f"no user with id {user_id}")
            row = QuestionRow(
                user=user,
                question=question,
                answer=answer,
                sources=sources_to_json(sources),
                model=model,
                asked_at=self._now(),
                seconds=seconds,
            )
            session.add(row)
        return _asked(row)

    def questions(self, user_id: int, *, limit: int | None = None) -> tuple[AskedQuestion, ...]:
        """A user's questions, the newest first."""
        with self._session() as session:
            if session.get(UserRow, user_id) is None:
                raise AccountNotFound(f"no user with id {user_id}")
            statement = (
                select(QuestionRow)
                .where(QuestionRow.user_id == user_id)
                .order_by(QuestionRow.question_id.desc())
                .limit(limit)
            )
            return tuple(_asked(row) for row in session.scalars(statement))

    def question(self, user_id: int, question_id: int) -> AskedQuestion:
        """One of a user's questions. Another user's is not found, as if it did not exist."""
        with self._session() as session:
            row = session.get(QuestionRow, question_id)
            if row is None or row.user_id != user_id:
                raise AccountNotFound(f"no question {question_id} of user {user_id}")
            return _asked(row)

    def delete_question(self, user_id: int, question_id: int) -> None:
        """Delete one of a user's questions; another user's is not found."""
        with self._session.begin() as session:
            row = session.get(QuestionRow, question_id)
            if row is None or row.user_id != user_id:
                raise AccountNotFound(f"no question {question_id} of user {user_id}")
            session.delete(row)
