"""Rebuild the database from the raw store.

A build normalises the raw store, applies the fitted models, runs every quality check,
and then replaces the league tables, the modeled tables and the build's own report in a
single transaction. The workbench therefore
always sees one complete build: the previous one until the new one commits.

A build with problems still loads - current data with its problems on display is more
useful than stale data with none - with one exception: a build that would empty a table
that currently has rows is refused, because that is far more likely a broken raw store
than a league that lost its players.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from front_office import __version__
from front_office.config.archetypes import load_archetypes
from front_office.config.models import load_value_model
from front_office.config.season_rules import load_all_season_rules
from front_office.config.settings import Settings
from front_office.domain.datasets import NBA_STATS
from front_office.domain.schema import conform_frame
from front_office.domain.tables import LEAGUE_TABLES
from front_office.domain.tables.operations import BUILD_ISSUES, CHECK_RESULTS, RAW_SNAPSHOTS
from front_office.pipelines.check import DataReport, check_store
from front_office.pipelines.ingest import FetchOutcome, FetchStatus
from front_office.pipelines.normalize import BuildIssue
from front_office.quality import CheckResult
from front_office.rawstore import RawStore
from front_office.storage import Database, OperationsLog, Warehouse


def utc_now() -> datetime:
    """Now, as naive UTC: the form every stored datetime takes."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class BuildReport:
    data: DataReport
    loaded: bool
    build_id: int | None = None
    rows_loaded: int = 0
    refused_because: str | None = None

    @property
    def ok(self) -> bool:
        """Loaded, with every table built and no contradiction found."""
        return self.loaded and self.data.ok


def build_database(
    settings: Settings, *, force: bool = False, now: Callable[[], datetime] = utc_now
) -> BuildReport:
    """Normalise the raw store, check it, and load it into the database."""
    started = now()
    store = RawStore(settings.raw_dir)
    season_rules = list(load_all_season_rules(settings.season_rules_dir).values())
    data = check_store(
        store,
        season_rules,
        load_value_model(settings.config_dir),
        load_archetypes(settings.config_dir),
    )

    frames = dict(data.tables.frames)
    frames[BUILD_ISSUES.name] = issues_frame(data.tables.issues)
    frames[CHECK_RESULTS.name] = checks_frame(data.checks)
    frames[RAW_SNAPSHOTS.name] = snapshots_frame(store)

    with Database(settings.database_path) as database:
        warehouse = Warehouse(database)
        if not force:
            previous = warehouse.row_counts()
            emptied = [
                contract.name
                for contract in LEAGUE_TABLES
                if previous.get(contract.name, 0) > 0 and frames[contract.name].empty
            ]
            if emptied:
                reason = (
                    f"this build would empty {', '.join(emptied)}, which currently "
                    f"{'holds' if len(emptied) == 1 else 'hold'} data; the database was left "
                    "as it was (use --force to load anyway)"
                )
                return BuildReport(data, loaded=False, refused_because=reason)

        with database.begin() as connection:
            rows_loaded = warehouse.replace(connection, frames)
            build_id = OperationsLog(database).record_build(
                connection,
                {
                    "started_at": started,
                    "finished_at": now(),
                    "lab_version": __version__,
                    "schema_fingerprint": database.current_fingerprint,
                    "status": "ok" if data.ok else "problems",
                    "rows_loaded": rows_loaded,
                    "build_errors": len(data.tables.errors),
                    "build_notes": len(data.tables.notes),
                    "check_errors": len(data.check_errors),
                    "check_warnings": len(data.check_warnings),
                },
            )
    return BuildReport(data, loaded=True, build_id=build_id, rows_loaded=rows_loaded)


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    exists: bool
    is_current: bool = False
    """Whether the tables match the contracts in this version of the lab."""
    row_counts: dict[str, int] | None = None
    latest_build: dict | None = None


def database_status(settings: Settings) -> DatabaseStatus:
    """What the database holds and how its last build went. Creates nothing."""
    if not settings.database_path.is_file():
        return DatabaseStatus(exists=False)
    with Database(settings.database_path) as database:
        return DatabaseStatus(
            exists=True,
            is_current=database.is_current,
            row_counts=Warehouse(database).row_counts(),
            latest_build=OperationsLog(database).latest_build(),
        )


def issues_frame(issues: Sequence[BuildIssue]) -> pd.DataFrame:
    rows = [
        {
            "issue_number": number,
            "table_name": issue.table,
            "scope": issue.scope,
            "severity": issue.severity.value,
            "message": issue.message,
        }
        for number, issue in enumerate(issues, start=1)
    ]
    return conform_frame(pd.DataFrame(rows, columns=list(BUILD_ISSUES.column_names)), BUILD_ISSUES)


def checks_frame(checks: Sequence[CheckResult]) -> pd.DataFrame:
    rows = [
        {
            "check_name": check.check,
            "table_name": check.table,
            "description": check.description,
            "severity": check.severity.value,
            "examined": check.examined,
            "failures": check.failures,
            "passed": check.passed,
            "examples": "\n".join(check.examples) or None,
        }
        for check in checks
    ]
    return conform_frame(
        pd.DataFrame(rows, columns=list(CHECK_RESULTS.column_names)), CHECK_RESULTS
    )


def snapshots_frame(store: RawStore) -> pd.DataFrame:
    """The newest snapshot of every dataset slice in the raw store."""
    rows = []
    for source, dataset in store.datasets():
        for partition in store.partitions(source, dataset):
            versions = store.versions(source, dataset, partition)
            newest = versions[-1]
            rows.append(
                {
                    "source": source,
                    "dataset": dataset,
                    "partition_key": newest.partition_key,
                    "season": partition.get("season"),
                    "fetched_at": newest.fetched_at,
                    "versions": len(versions),
                }
            )
    return conform_frame(
        pd.DataFrame(rows, columns=list(RAW_SNAPSHOTS.column_names)), RAW_SNAPSHOTS
    )


def log_fetches(settings: Settings, outcomes: Sequence[FetchOutcome]) -> int:
    """Record the fetches that reached the source. Returns how many were recorded.

    A skipped request never left the machine, so it is not an attempt and is not logged.
    """
    attempts = [
        {
            "source": NBA_STATS,
            "dataset": outcome.request.dataset.value,
            "partition_key": outcome.request.partition_key,
            "season": outcome.request.season.label if outcome.request.season else None,
            "status": outcome.status.value,
            "rows": outcome.rows,
            "error": outcome.error,
            "started_at": outcome.started_at.astimezone(UTC).replace(tzinfo=None),
            "finished_at": outcome.finished_at.astimezone(UTC).replace(tzinfo=None),
        }
        for outcome in outcomes
        if outcome.status is not FetchStatus.SKIPPED
    ]
    if attempts:
        with Database(settings.database_path) as database:
            OperationsLog(database).record_fetches(attempts)
    return len(attempts)
