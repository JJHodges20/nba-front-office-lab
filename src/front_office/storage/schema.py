"""Database tables generated from the data contracts.

A table's columns, types, keys and indexes come from its :class:`TableContract`, so the
database can never disagree with what processing produces and the dictionary documents.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
)

from front_office.domain.schema import DType, TableContract

_SQL_TYPES = {
    DType.INTEGER: Integer,
    DType.FLOAT: Float,
    DType.STRING: Text,
    DType.BOOLEAN: Boolean,
    DType.DATE: Date,
    DType.DATETIME: DateTime,
}


def build_tables(
    metadata: MetaData, contracts: Sequence[TableContract], *, enforce_references: bool
) -> dict[str, Table]:
    """Add one table per contract to ``metadata``.

    With ``enforce_references``, a declared reference to another table *in the same
    call* becomes a foreign key that deletes dependent rows with their parent. That is
    used for the tables the user owns. The league tables are rebuilt wholesale and their
    references are verified by the quality checks instead: a database-level constraint
    there would only get in the way of dropping and reloading them.
    """
    names = {contract.name for contract in contracts}
    tables = {}
    for contract in contracts:
        single_integer_key = (
            len(contract.primary_key) == 1
            and contract.field(contract.primary_key[0]).dtype is DType.INTEGER
        )
        columns = []
        for field in contract.fields:
            arguments = []
            target = field.references.split(".")[0] if field.references else None
            if enforce_references and target in names and target != contract.name:
                arguments.append(ForeignKey(field.references, ondelete="CASCADE"))
            is_key = field.name in contract.primary_key
            columns.append(
                Column(
                    field.name,
                    _SQL_TYPES[field.dtype],
                    *arguments,
                    primary_key=is_key,
                    nullable=field.nullable,
                    # A lone integer key is assigned by the database when omitted.
                    autoincrement=is_key and single_integer_key,
                    comment=field.description,
                )
            )
        table = Table(contract.name, metadata, *columns, comment=contract.description)
        for index_columns in contract.indexes:
            Index(
                f"ix_{contract.name}_{'_'.join(index_columns)}",
                *(table.c[c] for c in index_columns),
            )
        tables[contract.name] = table
    return tables


def schema_fingerprint(contracts: Sequence[TableContract]) -> str:
    """A short hash of everything about the contracts that shapes the database."""
    shape = [
        {
            "table": contract.name,
            "columns": [[f.name, f.dtype.value, f.nullable] for f in contract.fields],
            "key": list(contract.primary_key),
            "indexes": [list(index) for index in contract.indexes],
        }
        for contract in contracts
    ]
    canonical = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
