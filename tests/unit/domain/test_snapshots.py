from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from front_office.domain.snapshots import Snapshot, content_hash, partition_key
from tests.helpers import FETCHED_AT, snapshot


def test_partition_key_keeps_the_given_order() -> None:
    assert partition_key({"season": "2025-26", "season_type": "regular"}) == (
        "season=2025-26/season_type=regular"
    )
    assert partition_key({}) == "_all"


def test_equal_payloads_hash_equally_regardless_of_key_order() -> None:
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_hash_distinguishes_non_ascii_text() -> None:
    assert content_hash({"name": "Vučević"}) != content_hash({"name": "Vucevic"})


def test_snapshot_describes_itself() -> None:
    snap = snapshot("standings", {"resultSets": []}, {"season": "2025-26"})
    assert snap.describe() == "nba_stats/standings/season=2025-26"
    assert snap.partition_key == "season=2025-26"
    assert snap.content_hash == content_hash({"resultSets": []})


def test_fetch_time_is_normalised_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    snap = snapshot("standings", {}, fetched_at=datetime(2026, 10, 1, 8, 0, tzinfo=eastern))
    assert snap.fetched_at == FETCHED_AT
    assert snap.fetched_at.tzinfo is UTC


def test_fetch_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        snapshot("standings", {}, fetched_at=datetime(2026, 10, 1, 12, 0))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": "NBA Stats"},
        {"dataset": "team-logs"},
        {"partition": {"Season": "2025-26"}},
        {"partition": {"season": "../../etc"}},
        {"partition": {"season": "2025/26"}},
        {"partition": {"season": ""}},
        {"partition": {"team_id": 1610612738}},
    ],
)
def test_names_and_partition_values_must_be_path_safe(kwargs: dict) -> None:
    arguments = {
        "source": "nba_stats",
        "dataset": "standings",
        "partition": {},
        "fetched_at": FETCHED_AT,
        "payload": {},
    }
    arguments.update(kwargs)
    with pytest.raises(ValueError):
        Snapshot(**arguments)
