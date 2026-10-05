"""Reading and rebuilding the tables that are built from the raw store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from sqlalchemy import Connection, Table, func, inspect, select

from front_office.domain.schema import TableContract, conform_frame
from front_office.domain.tables import REBUILT_TABLES
from front_office.domain.tables import table as table_contract
from front_office.storage.database import Database, StorageError

INSERT_BATCH = 5_000


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as plain Python values, with every kind of missing value as ``None``.

    The database driver accepts neither NumPy scalars nor pandas' missing markers.
    """
    plain = frame.astype(object).where(frame.notna(), None)
    return plain.to_dict("records")


class Warehouse:
    """The league tables and the report of the build that produced them."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def replace(self, connection: Connection, frames: Mapping[str, pd.DataFrame]) -> int:
        """Drop every rebuilt table, recreate it from its contract, and load ``frames``.

        Runs inside the caller's transaction, so readers see either the old tables or
        the new ones, never a mixture. Returns the number of rows written.
        """
        expected = {contract.name for contract in REBUILT_TABLES}
        if set(frames) != expected:
            missing, extra = sorted(expected - set(frames)), sorted(set(frames) - expected)
            raise StorageError(
                f"a build must supply every rebuilt table; missing {missing}, extra {extra}"
            )

        conformed = {
            contract.name: conform_frame(frames[contract.name], contract)
            for contract in REBUILT_TABLES
        }
        self._database.rebuilt_metadata.drop_all(connection)
        self._database.rebuilt_metadata.create_all(connection)
        written = 0
        for contract in REBUILT_TABLES:
            rows = records(conformed[contract.name])
            sql_table = self._database.rebuilt[contract.name]
            for start in range(0, len(rows), INSERT_BATCH):
                connection.execute(sql_table.insert(), rows[start : start + INSERT_BATCH])
            written += len(rows)
        self._database.write_fingerprint(connection)
        return written

    def is_built(self) -> bool:
        """Whether a build has ever completed."""
        with self._database.connect() as connection:
            present = set(inspect(connection).get_table_names())
        return all(contract.name in present for contract in REBUILT_TABLES)

    def row_counts(self) -> dict[str, int]:
        """Rows in each rebuilt table; empty if nothing has been built."""
        if not self.is_built():
            return {}
        with self._database.connect() as connection:
            return {
                contract.name: connection.execute(
                    select(func.count()).select_from(self._database.rebuilt[contract.name])
                ).scalar_one()
                for contract in REBUILT_TABLES
            }

    def read(
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        *,
        order_by: Sequence[str] = (),
    ) -> pd.DataFrame:
        """Rows of one table as a frame satisfying its contract.

        ``where`` maps a column to the value it must equal, or to a list of values it
        may take. A null value in ``where`` matches nulls.
        """
        contract = table_contract(table)
        sql_table = self._database.table(table)
        if table in self._database.rebuilt and not self.is_built():
            raise StorageError("the database has not been built; run: fol build")
        statement = select(sql_table)
        for column, wanted in (where or {}).items():
            statement = statement.where(_condition(sql_table, column, wanted))
        for column in order_by:
            statement = statement.order_by(sql_table.c[column])
        with self._database.connect() as connection:
            result = connection.execute(statement)
            keys = list(result.keys())
            rows = result.fetchall()
        return frame_from_tuples(rows, keys, contract)

    def distinct(
        self, table: str, column: str, where: Mapping[str, Any] | None = None
    ) -> list[Any]:
        """The different non-null values of one column, ascending."""
        sql_table = self._database.table(table)
        if table in self._database.rebuilt and not self.is_built():
            raise StorageError("the database has not been built; run: fol build")
        if column not in sql_table.c:
            raise StorageError(f"table {table!r} has no column {column!r}")
        target = sql_table.c[column]
        statement = select(target).where(target.is_not(None)).distinct().order_by(target)
        for name, wanted in (where or {}).items():
            statement = statement.where(_condition(sql_table, name, wanted))
        with self._database.connect() as connection:
            return list(connection.execute(statement).scalars())


def _condition(sql_table: Table, column: str, wanted: Any) -> Any:
    if column not in sql_table.c:
        raise StorageError(f"table {sql_table.name!r} has no column {column!r}")
    target = sql_table.c[column]
    if isinstance(wanted, list | tuple | set | frozenset):
        return target.in_([_plain(value) for value in wanted])
    # SQLAlchemy renders a comparison with None as IS NULL.
    return target == _plain(wanted)


def _plain(value: Any) -> Any:
    """A NumPy or pandas scalar as the Python value the driver expects."""
    return value.item() if hasattr(value, "item") else value


def frame_from_tuples(
    rows: Sequence[Sequence[Any]], keys: Sequence[str], contract: TableContract
) -> pd.DataFrame:
    """Database rows, as the tuples a cursor returns with the column names it returns
    them under, as a frame with the contract's columns and canonical types. Several
    times faster than going through a mapping per row, which matters for the tables of
    games and player-seasons."""
    if not rows:
        return contract.empty_frame()
    frame = pd.DataFrame.from_records(list(rows), columns=list(keys))
    return conform_frame(frame, contract)


def frame_from_rows(rows: Sequence[Mapping[str, Any]], contract: TableContract) -> pd.DataFrame:
    """Database rows as a frame with the contract's columns and canonical types."""
    if not rows:
        return contract.empty_frame()
    frame = pd.DataFrame([dict(row) for row in rows], columns=list(contract.column_names))
    return conform_frame(frame, contract)
