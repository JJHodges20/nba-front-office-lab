from __future__ import annotations

import gzip
import json
from datetime import timedelta
from pathlib import Path

import pytest

from front_office.rawstore import RawStore, RawStoreError
from tests.helpers import FETCHED_AT, snapshot, stats_payload

PARTITION = {"season": "2025-26", "season_type": "regular"}


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "raw")


def payload(value: int = 1) -> dict:
    return stats_payload(["TEAM_ID", "W"], [[1610612738, value]])


def test_save_writes_one_file_under_the_partition(store: RawStore) -> None:
    result = store.save(snapshot("team_game_logs", payload(), PARTITION))
    assert result.created
    expected_dir = (
        store.root / "nba_stats" / "team_game_logs" / "season=2025-26" / "season_type=regular"
    )
    assert result.stored.path.parent == expected_dir
    assert result.stored.path.name.startswith("20261001T120000000000Z_")
    assert result.stored.path.name.endswith(".json.gz")
    assert [path.name for path in expected_dir.iterdir()] == [result.stored.path.name]


def test_snapshots_saved_within_the_same_second_keep_their_order(store: RawStore) -> None:
    """Two imports a moment apart: the later one must be the newest, whatever its hash."""
    partition = {"season": "2025-26"}
    for microsecond in range(1, 13):
        moment = FETCHED_AT + timedelta(microseconds=microsecond)
        store.save(snapshot("standings", payload(microsecond), partition, fetched_at=moment))
    versions = store.versions("nba_stats", "standings", partition)
    assert [store.load(version).payload for version in versions] == [
        payload(value) for value in range(1, 13)
    ]
    assert store.latest("nba_stats", "standings", partition).payload == payload(12)
    assert store.latest_info("nba_stats", "standings", partition).fetched_at == (
        FETCHED_AT + timedelta(microseconds=12)
    )


def test_file_names_written_to_the_second_are_still_read_and_ordered(store: RawStore) -> None:
    """Stores written before microsecond names existed must keep working."""
    partition = {"season": "2025-26"}
    newest = store.save(
        snapshot("standings", payload(2), partition, fetched_at=FETCHED_AT + timedelta(seconds=45))
    ).stored
    older = store.save(snapshot("standings", payload(1), partition, fetched_at=FETCHED_AT)).stored
    # Rename both to the old to-the-second form.
    old_style = {}
    for stored, seconds in ((older, "00"), (newest, "45")):
        renamed = stored.path.with_name(f"20261001T1200{seconds}Z_{stored.hash_prefix}.json.gz")
        stored.path.rename(renamed)
        old_style[seconds] = renamed
    versions = store.versions("nba_stats", "standings", partition)
    assert [version.path for version in versions] == [old_style["00"], old_style["45"]]
    assert versions[1].fetched_at == FETCHED_AT + timedelta(seconds=45)
    assert store.latest("nba_stats", "standings", partition).payload == payload(2)

    # A new snapshot in the same second as an old-style one still sorts after it.
    later = FETCHED_AT + timedelta(seconds=45, microseconds=7)
    store.save(snapshot("standings", payload(3), partition, fetched_at=later))
    assert store.latest("nba_stats", "standings", partition).payload == payload(3)


def test_round_trip_preserves_the_snapshot_exactly(store: RawStore) -> None:
    original = snapshot("team_game_logs", {**payload(), "note": "Nikola Vučević"}, PARTITION)
    store.save(original)
    loaded = store.latest("nba_stats", "team_game_logs", PARTITION)
    assert loaded is not None
    assert loaded.payload == original.payload
    assert loaded.partition == original.partition
    assert loaded.fetched_at == original.fetched_at
    assert loaded.request == original.request
    assert loaded.content_hash == original.content_hash


def test_saving_identical_content_again_writes_nothing(store: RawStore) -> None:
    first = store.save(snapshot("standings", payload(), {"season": "2025-26"}))
    later = snapshot(
        "standings", payload(), {"season": "2025-26"}, fetched_at=FETCHED_AT + timedelta(hours=6)
    )
    second = store.save(later)
    assert not second.created
    assert second.stored.path == first.stored.path
    assert len(store.versions("nba_stats", "standings", {"season": "2025-26"})) == 1


def test_changed_content_adds_a_version_and_keeps_the_old_one(store: RawStore) -> None:
    partition = {"season": "2025-26"}
    first = store.save(snapshot("standings", payload(1), partition))
    second = store.save(
        snapshot("standings", payload(2), partition, fetched_at=FETCHED_AT + timedelta(days=1))
    )
    assert second.created
    versions = store.versions("nba_stats", "standings", partition)
    assert [version.path for version in versions] == [first.stored.path, second.stored.path]
    assert store.load(versions[0]).payload == payload(1)
    assert store.latest("nba_stats", "standings", partition).payload == payload(2)
    assert store.latest_info("nba_stats", "standings", partition).fetched_at == (
        FETCHED_AT + timedelta(days=1)
    )


def test_content_that_flips_back_is_stored_again(store: RawStore) -> None:
    partition = {"season": "2025-26"}
    for offset, value in enumerate([1, 2, 1]):
        store.save(
            snapshot(
                "standings",
                payload(value),
                partition,
                fetched_at=FETCHED_AT + timedelta(days=offset),
            )
        )
    assert len(store.versions("nba_stats", "standings", partition)) == 3


def test_stored_bytes_are_reproducible(tmp_path: Path) -> None:
    one, two = RawStore(tmp_path / "a"), RawStore(tmp_path / "b")
    first = one.save(snapshot("standings", payload(), {"season": "2025-26"}))
    second = two.save(snapshot("standings", payload(), {"season": "2025-26"}))
    assert first.stored.path.read_bytes() == second.stored.path.read_bytes()


def test_nothing_is_found_before_anything_is_saved(store: RawStore) -> None:
    assert store.latest("nba_stats", "standings", {"season": "2025-26"}) is None
    assert store.latest_info("nba_stats", "standings", {"season": "2025-26"}) is None
    assert store.versions("nba_stats", "standings", {"season": "2025-26"}) == []
    assert store.partitions("nba_stats", "standings") == []
    assert store.datasets() == []


def test_partitions_and_datasets_are_listed(store: RawStore) -> None:
    store.save(snapshot("team_years", payload()))
    store.save(snapshot("standings", payload(), {"season": "2024-25"}))
    store.save(snapshot("standings", payload(), {"season": "2025-26"}))
    store.save(snapshot("team_roster", payload(), {"season": "2025-26", "team_id": "1610612738"}))

    assert store.datasets() == [
        ("nba_stats", "standings"),
        ("nba_stats", "team_roster"),
        ("nba_stats", "team_years"),
    ]
    assert store.partitions("nba_stats", "standings") == [
        {"season": "2024-25"},
        {"season": "2025-26"},
    ]
    assert store.partitions("nba_stats", "team_years") == [{}]
    assert store.partitions("nba_stats", "team_roster") == [
        {"season": "2025-26", "team_id": "1610612738"}
    ]
    assert store.latest("nba_stats", "team_years", {}).partition == {}


def test_no_temporary_files_are_left_behind(store: RawStore) -> None:
    store.save(snapshot("standings", payload(), {"season": "2025-26"}))
    assert not list(store.root.rglob("*.part"))


def rewrite(path: Path, change) -> None:
    envelope = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    change(envelope)
    path.write_bytes(gzip.compress(json.dumps(envelope).encode("utf-8")))


def test_a_tampered_payload_is_detected(store: RawStore) -> None:
    stored = store.save(snapshot("standings", payload(), {"season": "2025-26"})).stored
    rewrite(stored.path, lambda envelope: envelope["payload"].update(resource="edited"))
    with pytest.raises(RawStoreError, match="does not match its recorded hash"):
        store.load(stored)


def test_a_misfiled_snapshot_is_detected(store: RawStore) -> None:
    stored = store.save(snapshot("standings", payload(), {"season": "2025-26"})).stored
    rewrite(stored.path, lambda envelope: envelope["partition"].update(season="2024-25"))
    with pytest.raises(RawStoreError, match="wrong partition"):
        store.load(stored)


def test_an_unreadable_file_is_reported(store: RawStore) -> None:
    stored = store.save(snapshot("standings", payload(), {"season": "2025-26"})).stored
    stored.path.write_bytes(b"not gzip")
    with pytest.raises(RawStoreError, match="cannot read snapshot"):
        store.load(stored)


def test_a_malformed_envelope_is_reported(store: RawStore) -> None:
    stored = store.save(snapshot("standings", payload(), {"season": "2025-26"})).stored
    rewrite(stored.path, lambda envelope: envelope.pop("fetched_at"))
    with pytest.raises(RawStoreError, match="malformed envelope"):
        store.load(stored)


def test_a_stray_file_name_is_reported(store: RawStore) -> None:
    stored = store.save(snapshot("standings", payload(), {"season": "2025-26"})).stored
    (stored.path.parent / "notes.json.gz").write_bytes(b"")
    with pytest.raises(RawStoreError, match="unrecognised snapshot file name"):
        store.versions("nba_stats", "standings", {"season": "2025-26"})
