"""The lab reads fresh, and remembers within one answer when asked to."""

from __future__ import annotations

import pytest

from front_office.config.settings import Settings
from front_office.services import Lab
from tests.helpers import BOS


@pytest.fixture
def counted(built_lab: Settings, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """An open lab whose warehouse reads are counted."""
    with Lab(built_lab) as lab:
        reads: list[tuple] = []
        original = lab.warehouse.read

        def counting(table, where=None, **kwargs):  # type: ignore[no-untyped-def]
            reads.append((table, where))
            return original(table, where, **kwargs)

        monkeypatch.setattr(lab.warehouse, "read", counting)
        yield lab, reads


class TestRemembering:
    def test_outside_a_block_every_read_is_fresh(self, counted) -> None:  # type: ignore[no-untyped-def]
        lab, reads = counted
        lab.read("teams")
        lab.read("teams")
        assert len(reads) == 2

    def test_within_a_block_a_table_is_read_once(self, counted) -> None:  # type: ignore[no-untyped-def]
        lab, reads = counted
        with lab.remembering():
            first = lab.read("teams")
            again = lab.read("teams")
            narrowed = lab.read("teams", {"team_id": [BOS]})
            lab.read("teams", {"team_id": [BOS]})
        lab.read("teams")
        assert [table for table, _ in reads] == ["teams", "teams", "teams"]
        assert first.equals(again) and first is not again
        assert narrowed["team_id"].tolist() == [BOS]

    def test_what_a_caller_changes_stays_its_own(self, counted) -> None:  # type: ignore[no-untyped-def]
        lab, _ = counted
        with lab.remembering():
            first = lab.read("teams")
            first["full_name"] = "changed"
            assert (lab.read("teams")["full_name"] != "changed").all()

    def test_blocks_nest_and_the_memory_ends_with_the_outer_one(self, counted) -> None:  # type: ignore[no-untyped-def]
        lab, reads = counted
        with lab.remembering():
            lab.read("teams")
            with lab.remembering():
                lab.read("teams")
            lab.read("teams")
        assert len(reads) == 1
        lab.read("teams")
        assert len(reads) == 2
