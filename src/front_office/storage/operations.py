"""The history of fetches and builds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from sqlalchemy import Connection, select

from front_office.domain.tables.operations import BUILDS, FETCH_LOG
from front_office.storage.database import Database
from front_office.storage.warehouse import frame_from_rows


class OperationsLog:
    """Append-only record of what the lab did to its data, and when."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._fetches = database.kept[FETCH_LOG.name]
        self._builds = database.kept[BUILDS.name]

    def record_fetches(self, attempts: Sequence[Mapping[str, Any]]) -> None:
        """Append fetch attempts. Each mapping holds every ``fetch_log`` column but the id."""
        if not attempts:
            return
        with self._database.begin() as connection:
            connection.execute(self._fetches.insert(), [dict(attempt) for attempt in attempts])

    def record_build(self, connection: Connection, build: Mapping[str, Any]) -> int:
        """Append a build, inside the transaction that wrote its tables. Returns its id."""
        result = connection.execute(self._builds.insert().values(**build))
        return int(result.inserted_primary_key[0])

    def builds(self, limit: int | None = None) -> pd.DataFrame:
        """Builds, newest first."""
        statement = select(self._builds).order_by(self._builds.c.build_id.desc())
        if limit is not None:
            statement = statement.limit(limit)
        with self._database.connect() as connection:
            return frame_from_rows(connection.execute(statement).mappings().all(), BUILDS)

    def latest_build(self) -> dict[str, Any] | None:
        builds = self.builds(limit=1)
        return None if builds.empty else builds.iloc[0].to_dict()

    def fetches(self, *, status: str | None = None, limit: int | None = None) -> pd.DataFrame:
        """Fetch attempts, newest first, optionally only those with one status."""
        statement = select(self._fetches).order_by(self._fetches.c.fetch_id.desc())
        if status is not None:
            statement = statement.where(self._fetches.c.status == status)
        if limit is not None:
            statement = statement.limit(limit)
        with self._database.connect() as connection:
            return frame_from_rows(connection.execute(statement).mappings().all(), FETCH_LOG)

    def latest_fetch_per_dataset(self) -> pd.DataFrame:
        """The most recent attempt at each slice of each dataset."""
        fetches = self.fetches()
        if fetches.empty:
            return fetches
        newest = fetches.groupby(["source", "dataset", "partition_key"])["fetch_id"].idxmax()
        return (
            fetches.loc[newest]
            .sort_values(["source", "dataset", "partition_key"])
            .reset_index(drop=True)
        )
