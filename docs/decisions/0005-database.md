# 0005 - One SQLite database, rebuilt atomically from the raw store

Date: 2026-10-01. Status: accepted.

## Context

The lab needs persistent storage that preserves history, answers analytical queries
quickly, and gives every other layer a clean way in and out. It is a single-user tool on
one machine. Almost everything it stores can be recomputed from the raw store; the one
thing that cannot is what the user creates.

## Decision

**One SQLite file**, reached through SQLAlchemy Core. SQLite ships with Python, needs no
server, and at this size (about 175,000 rows, 32 MB) answers every query the workbench
makes in well under a second. SQLAlchemy keeps the door open to another engine without
other layers noticing.

**Tables are generated from the data contracts** (`storage/schema.py`). No table is
declared twice. A fingerprint of the contracts is stored with each build, so the lab can
tell when the tables were built by a different version of itself.

**Two groups of tables with different lifetimes:**

| Group | Tables | Lifetime |
| --- | --- | --- |
| Rebuilt | league data; the last build's issues, check results and snapshot inventory | Dropped and rewritten together by every build |
| Kept | the user's rosters; the history of fetches and builds | Created once, never dropped |

**A build is one transaction.** Every rebuilt table is dropped, recreated from its
contract and reloaded, and the build's row in the history is written, before anything is
committed. With write-ahead logging on, the workbench keeps reading the previous build
until the new one commits, and a build that fails leaves the previous one untouched.
SQLite's Python driver leaves `DROP` and `CREATE` outside transactions by default; the
database layer takes transaction control from the driver and issues `BEGIN` itself, as
SQLAlchemy documents, and a test proves a rolled-back build restores the old tables.

**A build with problems still loads**, with its problems recorded in `build_issues` and
`check_results` for the Data Health page. The exception: a build that would *empty* a
league table that currently has rows is refused unless forced, since that almost always
means the raw store is damaged, not that the league shrank.

**Foreign keys are enforced only between kept tables** (deleting a roster deletes its
players). References among rebuilt tables are verified by the quality checks instead: a
database constraint there would only obstruct dropping and reloading them, and a kept
table cannot hold a constraint on a table that is about to be dropped.

**Repositories are the only way in or out** (`Warehouse`, `RosterRepository`,
`OperationsLog`). They return frames that satisfy the table's contract, so data read
back has the same types as data written. No other layer imports SQLAlchemy; the
architecture tests enforce that.

## Consequences

- A change to a contract reaches the database at the next build, with no migration.
- Kept tables do need migrations when their shape changes. There is one version of them
  so far; a migration step must be added with the first change.
- Every build reloads everything, about twenty seconds. That is acceptable for a daily
  refresh and keeps the build a pure function of the raw store. Loading only what
  changed is possible later without changing any interface.
- A roster refers to players by id without a database constraint, so a roster can name a
  player who has since left the player table. Services must tolerate that.
