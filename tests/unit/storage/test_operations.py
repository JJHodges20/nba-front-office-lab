from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from front_office.domain.schema import validate_frame
from front_office.domain.tables.operations import BUILDS, FETCH_LOG
from front_office.storage import Database, OperationsLog

START = datetime(2026, 10, 1, 12, 0, 0)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    with Database(tmp_path / "lab.sqlite") as opened:
        yield opened


@pytest.fixture
def log(database: Database) -> OperationsLog:
    return OperationsLog(database)


def attempt(dataset: str, partition: str, status: str, minute: int, **extra: object) -> dict:
    moment = START + timedelta(minutes=minute)
    row = {
        "source": "nba_stats",
        "dataset": dataset,
        "partition_key": partition,
        "season": partition.removeprefix("season=")[:7]
        if partition.startswith("season=")
        else None,
        "status": status,
        "rows": 30 if status != "failed" else None,
        "error": "timed out" if status == "failed" else None,
        "started_at": moment,
        "finished_at": moment + timedelta(seconds=2),
    }
    row.update(extra)
    return row


def build(status: str = "ok", **extra: object) -> dict:
    row = {
        "started_at": START,
        "finished_at": START + timedelta(seconds=20),
        "lab_version": "0.1.0",
        "schema_fingerprint": "abc123def456",
        "status": status,
        "rows_loaded": 1000,
        "build_errors": 0,
        "build_notes": 2,
        "check_errors": 0,
        "check_warnings": 1,
    }
    row.update(extra)
    return row


class TestFetches:
    def test_nothing_recorded_gives_an_empty_conforming_frame(self, log: OperationsLog) -> None:
        fetches = log.fetches()
        assert len(fetches) == 0
        assert tuple(fetches.columns) == FETCH_LOG.column_names
        assert len(log.latest_fetch_per_dataset()) == 0

    def test_recording_no_attempts_is_a_no_op(self, log: OperationsLog) -> None:
        log.record_fetches([])
        assert len(log.fetches()) == 0

    def test_attempts_are_listed_newest_first(self, log: OperationsLog) -> None:
        log.record_fetches(
            [
                attempt("standings", "season=2025-26", "stored", 0),
                attempt("team_years", "_all", "unchanged", 1),
                attempt("standings", "season=2026-27", "failed", 2),
            ]
        )
        fetches = log.fetches()
        assert validate_frame(fetches, FETCH_LOG) == []
        assert fetches["fetch_id"].tolist() == [3, 2, 1]
        assert fetches["status"].tolist() == ["failed", "unchanged", "stored"]
        assert fetches.iloc[0]["error"] == "timed out"
        assert fetches.iloc[2]["season"] == "2025-26"

    def test_filter_by_status_and_limit(self, log: OperationsLog) -> None:
        log.record_fetches(
            [attempt("standings", f"season=202{n}-2{n + 1}", "failed", n) for n in range(4)]
            + [attempt("team_years", "_all", "stored", 9)]
        )
        assert len(log.fetches(status="failed")) == 4
        assert log.fetches(status="failed", limit=2)["fetch_id"].tolist() == [4, 3]
        assert log.fetches(limit=1)["dataset"].tolist() == ["team_years"]

    def test_latest_attempt_per_dataset_slice(self, log: OperationsLog) -> None:
        log.record_fetches(
            [
                attempt("standings", "season=2026-27", "stored", 0),
                attempt("standings", "season=2026-27", "failed", 5),
                attempt("standings", "season=2025-26", "stored", 1),
                attempt("team_years", "_all", "failed", 2),
                attempt("team_years", "_all", "unchanged", 6),
            ]
        )
        latest = log.latest_fetch_per_dataset()
        outcome = {(row.dataset, row.partition_key): row.status for row in latest.itertuples()}
        assert outcome == {
            ("standings", "season=2025-26"): "stored",
            ("standings", "season=2026-27"): "failed",
            ("team_years", "_all"): "unchanged",
        }

    def test_the_log_is_append_only(self, log: OperationsLog) -> None:
        log.record_fetches([attempt("standings", "season=2025-26", "stored", 0)])
        log.record_fetches([attempt("standings", "season=2025-26", "unchanged", 1)])
        assert log.fetches()["fetch_id"].tolist() == [2, 1]


class TestBuilds:
    def test_no_builds(self, log: OperationsLog) -> None:
        assert log.latest_build() is None
        assert len(log.builds()) == 0

    def test_builds_are_numbered_and_listed_newest_first(
        self, database: Database, log: OperationsLog
    ) -> None:
        with database.begin() as connection:
            first = log.record_build(connection, build())
        with database.begin() as connection:
            second = log.record_build(connection, build("problems", check_errors=2))
        assert (first, second) == (1, 2)
        builds = log.builds()
        assert validate_frame(builds, BUILDS) == []
        assert builds["build_id"].tolist() == [2, 1]
        latest = log.latest_build()
        assert (latest["build_id"], latest["status"], latest["check_errors"]) == (2, "problems", 2)
        assert log.builds(limit=1)["build_id"].tolist() == [2]

    def test_a_build_rolled_back_is_not_recorded(
        self, database: Database, log: OperationsLog
    ) -> None:
        with pytest.raises(RuntimeError), database.begin() as connection:
            log.record_build(connection, build())
            raise RuntimeError("the load failed")
        assert log.latest_build() is None
