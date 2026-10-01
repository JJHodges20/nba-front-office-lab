"""The SQLite database: connection handling and the tables that are never rebuilt."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

from sqlalchemy import (
    Column,
    Connection,
    Engine,
    MetaData,
    Table,
    Text,
    create_engine,
    event,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from front_office.domain.tables import KEPT_TABLES, REBUILT_TABLES
from front_office.storage.schema import build_tables, schema_fingerprint

LOCK_TIMEOUT_SECONDS = 30
META_TABLE = "lab_meta"
META_FINGERPRINT = "rebuilt_schema_fingerprint"


class StorageError(RuntimeError):
    """The database cannot be used as asked."""


class Database:
    """One SQLite file holding every table of the lab.

    Tables fall in two groups. The *rebuilt* tables - league data and the report of the
    last build - are dropped and rewritten together by every build. The *kept* tables -
    the user's rosters and the history of fetches and builds - are created once and
    never dropped.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path.as_posix()}", connect_args={"timeout": LOCK_TIMEOUT_SECONDS}
        )
        self._configure(self.engine)

        self.kept_metadata = MetaData()
        self.kept = build_tables(self.kept_metadata, KEPT_TABLES, enforce_references=True)
        self.meta = Table(
            META_TABLE,
            self.kept_metadata,
            Column("key", Text, primary_key=True),
            Column("value", Text, nullable=False),
        )
        self.rebuilt_metadata = MetaData()
        self.rebuilt = build_tables(self.rebuilt_metadata, REBUILT_TABLES, enforce_references=False)
        with self.begin() as connection:
            self.kept_metadata.create_all(connection)

    @staticmethod
    def _configure(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _on_connect(connection, _record) -> None:  # type: ignore[no-untyped-def]
            # Left to itself the sqlite3 module starts a transaction only before a data
            # change, so DROP and CREATE would run outside one and a failed rebuild could
            # not be undone. SQLAlchemy's documented remedy has two halves: take
            # transaction control away from the driver here, and issue BEGIN ourselves
            # in the "begin" hook below. The second half is what makes DDL transactional.
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # Write-ahead logging lets the workbench keep reading during a rebuild.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _on_begin(connection) -> None:  # type: ignore[no-untyped-def]
            connection.exec_driver_sql("BEGIN")

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        """A transaction: committed on success, rolled back on any error."""
        with self.engine.begin() as connection:
            yield connection

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        """A connection for reading; nothing is committed."""
        with self.engine.connect() as connection:
            yield connection

    def table(self, name: str) -> Table:
        # Looked up with "in": a SQLAlchemy table has no truth value to test with "or".
        if name in self.rebuilt:
            return self.rebuilt[name]
        if name in self.kept:
            return self.kept[name]
        raise StorageError(f"no table named {name!r}")

    def stored_fingerprint(self) -> str | None:
        """Fingerprint of the contracts the rebuilt tables were last created from."""
        with self.connect() as connection:
            return connection.execute(
                select(self.meta.c.value).where(self.meta.c.key == META_FINGERPRINT)
            ).scalar()

    def write_fingerprint(self, connection: Connection) -> None:
        statement = sqlite_insert(self.meta).values(
            key=META_FINGERPRINT, value=self.current_fingerprint
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[self.meta.c.key], set_={"value": statement.excluded.value}
            )
        )

    @property
    def current_fingerprint(self) -> str:
        return schema_fingerprint(REBUILT_TABLES)

    @property
    def is_current(self) -> bool:
        """Whether the rebuilt tables exist and match the contracts in this code."""
        return self.stored_fingerprint() == self.current_fingerprint

    def dispose(self) -> None:
        """Close every connection. Required on Windows before the file can be removed."""
        self.engine.dispose()

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.dispose()
