"""data/current.sqlite: tables replaced whole, a log only added to."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from front_office.processing.current import transactions_frame
from front_office.storage import StorageError
from front_office.storage.current import CurrentStore
from tests.current_fakes import FETCHED, move, movement


def test_a_table_is_replaced_whole(tmp_path: Path) -> None:
    with CurrentStore(tmp_path / "current.sqlite") as store:
        two = transactions_frame(movement(move(), move(TRANSACTION_DATE="2026-10-03")), FETCHED)
        assert store.replace("transactions", two) == 2
        one = transactions_frame(movement(move(TRANSACTION_DATE="2026-10-04")), FETCHED)
        assert store.replace("transactions", one) == 1
        held = store.read("transactions")
    assert held["transaction_date"].dt.day.tolist() == [4]


def test_the_log_is_only_added_to(tmp_path: Path) -> None:
    with CurrentStore(tmp_path / "current.sqlite") as store:
        for minute, status in ((0, "stored"), (5, "failed")):
            store.record(
                {
                    "source": "injuries",
                    "attempted_at": datetime(2026, 10, 9, 12, minute),
                    "status": status,
                }
            )
        store.record(
            {"source": "games", "attempted_at": datetime(2026, 10, 9, 12, 7), "status": "none"}
        )
        with pytest.raises(StorageError, match="not a table a refresh replaces"):
            store.replace("current_refreshes", store.refreshes())
        injuries = store.refreshes("injuries")
        everything = store.refreshes()
    assert injuries["status"].tolist() == ["failed", "stored"]
    assert everything["refresh_id"].tolist() == [2, 1, 0]


def test_an_unknown_table_is_refused(tmp_path: Path) -> None:
    with CurrentStore(tmp_path / "current.sqlite") as store, pytest.raises(StorageError):
        store.read("team_seasons")
