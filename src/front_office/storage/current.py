"""``data/current.sqlite``: current information fetched since the build (decision 0018).

A file of its own, so that a refresh never touches what a build made and a build never
drops what a refresh fetched. A source's table is replaced whole by its refresh, inside one
transaction; the refresh log is only ever added to. Tables are made from the contracts in
``domain/tables/current.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

import pandas as pd
from sqlalchemy import Engine, MetaData, create_engine, delete, event, func, insert, select

from front_office.domain.schema import conform_frame
from front_office.domain.tables import CURRENT_TABLES
from front_office.domain.tables.current import CURRENT_REFRESHES
from front_office.storage.database import LOCK_TIMEOUT_SECONDS, StorageError
from front_office.storage.schema import build_tables
from front_office.storage.warehouse import frame_from_rows, records

_CONTRACTS = {contract.name: contract for contract in CURRENT_TABLES}
LOG = CURRENT_REFRESHES.name


class CurrentStore:
    """The current-information cache. Open it in a ``with`` block: on Windows an open
    connection keeps the file locked."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path.as_posix()}", connect_args={"timeout": LOCK_TIMEOUT_SECONDS}
        )

        @event.listens_for(self.engine, "connect")
        def _write_ahead(connection, _record) -> None:  # type: ignore[no-untyped-def]
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        self.metadata = MetaData()
        self.tables = build_tables(self.metadata, CURRENT_TABLES, enforce_references=False)
        with self.engine.begin() as connection:
            self.metadata.create_all(connection)

    def __enter__(self) -> CurrentStore:
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

    def replace(self, name: str, frame: pd.DataFrame) -> int:
        """Swap a table's rows for ``frame``, all at once. Returns the rows stored."""
        if name == LOG or name not in _CONTRACTS:
            raise StorageError(f"{name!r} is not a table a refresh replaces")
        rows = records(conform_frame(frame, _CONTRACTS[name]))
        table = self.tables[name]
        with self.engine.begin() as connection:
            connection.execute(delete(table))
            if rows:
                connection.execute(insert(table), rows)
        return len(rows)

    def read(self, name: str, where: Mapping[str, Any] | None = None) -> pd.DataFrame:
        if name not in _CONTRACTS:
            raise StorageError(f"no current table called {name!r}")
        table = self.tables[name]
        query = select(table)
        for column, value in (where or {}).items():
            query = query.where(table.c[column] == value)
        with self.engine.connect() as connection:
            rows = [dict(row._mapping) for row in connection.execute(query)]
        return frame_from_rows(rows, _CONTRACTS[name])

    def record(self, entry: Mapping[str, Any]) -> int:
        """Add one refresh attempt to the log; returns its id."""
        table = self.tables[LOG]
        with self.engine.begin() as connection:
            latest = connection.execute(select(func.max(table.c.refresh_id))).scalar()
            refresh_id = 0 if latest is None else int(latest) + 1
            row = {**{column: None for column in CURRENT_REFRESHES.column_names}, **entry}
            row["refresh_id"] = refresh_id
            frame = conform_frame(pd.DataFrame([row]), CURRENT_REFRESHES)
            connection.execute(insert(table), records(frame))
        return refresh_id

    def refreshes(self, source: str | None = None) -> pd.DataFrame:
        """Refresh attempts, newest first."""
        log = self.read(LOG, None if source is None else {"source": source})
        return log.sort_values("refresh_id", ascending=False).reset_index(drop=True)
