"""The research store (A6): workspaces and what they keep, in a file of their own, versioned."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from front_office.domain.schema import validate_frame
from front_office.domain.tables.research import (
    RESEARCH_APPROVALS,
    RESEARCH_EXPERIMENTS,
    RESEARCH_FINDINGS,
    RESEARCH_PROPOSALS,
    RESEARCH_TURNS,
    RESEARCH_WORKSPACES,
)
from front_office.storage import (
    ResearchNotFound,
    ResearchStore,
    ResearchUnreadable,
    StorageError,
    research,
    set_aside,
)
from front_office.storage.research import MIGRATIONS, Migration


class Clock:
    """Strictly increasing moments, so ordering by time is deterministic."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 10, 12, 0, 0)

    def __call__(self) -> datetime:
        self.moment += timedelta(seconds=1)
        return self.moment


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "assistant" / "assistant.sqlite"


@pytest.fixture
def store(path: Path) -> Iterator[ResearchStore]:
    with ResearchStore(path, now=Clock()) as opened:
        yield opened


def turn(workspace_id: int, question: str, *, conversation: int = 1, at: datetime | None = None):  # type: ignore[no-untyped-def]
    return {
        "workspace_id": workspace_id,
        "conversation": conversation,
        "asked_at": at or datetime(2026, 10, 10, 13, 0, 0),
        "question": question,
        "mode": "quick",
        "season": "2025-26",
        "season_type": "regular",
        "team_id": None,
        "player_id": None,
        "roster_id": None,
        "asked_from": "AI Research",
        "about": None,
        "outcome": "supported",
        "answer_text": f"An answer to {question}",
        "error": None,
        "build_id": 16,
        "value_model": "r2",
        "model": "qwen3:8b",
        "policy": "2026-10-10.3",
        "seconds": 4.2,
        "payload": "{}",
    }


def proposal(fingerprint: str, label: str = "Option A") -> dict:
    return {
        "fingerprint": fingerprint,
        "label": label,
        "payroll_season": "2026-27",
        "payload": "{}",
        "created_at": datetime(2026, 10, 10, 13, 0, 0),
    }


class TestAFreshFile:
    def test_is_made_at_the_latest_version(self, store: ResearchStore, path: Path) -> None:
        assert path.exists() and store.version() == store.latest == MIGRATIONS[-1].version
        assert store.backup is None

    def test_opening_again_changes_nothing(self, path: Path) -> None:
        with ResearchStore(path) as first:
            first.create_workspace("Kept")
        with ResearchStore(path) as second:
            assert second.workspaces()["name"].tolist() == ["Kept"] and second.backup is None


class TestWorkspaces:
    def test_create_and_read(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace(
            "  2026   budget contender ", goal=" Find a cheap starter ", team_id=1610612752
        )
        row = store.workspace(workspace_id)
        assert row["name"] == "2026 budget contender" and row["goal"] == "Find a cheap starter"
        assert (row["team_id"], row["season"], row["conversation"], row["archived"]) == (
            1610612752,
            None,
            1,
            False,
        )
        listed = store.workspaces()
        assert validate_frame(listed, RESEARCH_WORKSPACES) == []

    @pytest.mark.parametrize("name", ["", "   ", "x" * 61])
    def test_a_bad_name_is_refused(self, store: ResearchStore, name: str) -> None:
        with pytest.raises(StorageError):
            store.create_workspace(name)

    def test_names_are_unique_whatever_the_case(self, store: ResearchStore) -> None:
        first = store.create_workspace("Knicks")
        with pytest.raises(StorageError, match="already exists"):
            store.create_workspace("knicks")
        second = store.create_workspace("Celtics")
        with pytest.raises(StorageError, match="already exists"):
            store.update_workspace(second, name="KNICKS")
        store.update_workspace(first, name="Knicks")  # its own name is no clash

    def test_a_focus_is_checked(self, store: ResearchStore) -> None:
        with pytest.raises(ValueError, match="not a season label"):
            store.create_workspace("Bad season", season="2025")
        with pytest.raises(StorageError, match="season_type"):
            store.create_workspace("Bad phase", season_type="preseason")
        with pytest.raises(StorageError, match="no editable field"):
            store.update_workspace(store.create_workspace("Fine"), colour="red")

    def test_archived_ones_are_listed_apart(self, store: ResearchStore) -> None:
        kept, put_away = store.create_workspace("Kept"), store.create_workspace("Put away")
        store.update_workspace(put_away, archived=True)
        assert store.workspaces()["workspace_id"].tolist() == [kept]
        assert store.workspaces(archived=True)["workspace_id"].tolist() == [put_away]
        assert len(store.workspaces(archived=None)) == 2

    def test_most_recently_changed_first(self, store: ResearchStore) -> None:
        older, newer = store.create_workspace("Older"), store.create_workspace("Newer")
        assert store.workspaces()["workspace_id"].tolist() == [newer, older]
        store.update_workspace(older, notes="touched")
        assert store.workspaces()["workspace_id"].tolist() == [older, newer]

    def test_a_missing_workspace_is_reported(self, store: ResearchStore) -> None:
        with pytest.raises(ResearchNotFound):
            store.workspace(99)
        with pytest.raises(ResearchNotFound):
            store.delete_workspace(99)
        with pytest.raises(ResearchNotFound):
            store.add_turn(turn(99, "Who?"))

    def test_deleting_a_workspace_deletes_what_it_holds(self, store: ResearchStore) -> None:
        gone, kept = store.create_workspace("Gone"), store.create_workspace("Kept")
        for workspace_id in (gone, kept):
            turn_id = store.add_turn(turn(workspace_id, "Q"), [proposal(f"fp{workspace_id}")])
            store.add_finding(
                {
                    "workspace_id": workspace_id,
                    "turn_id": turn_id,
                    "title": "F",
                    "question": "Q",
                    "asked_at": datetime(2026, 10, 10),
                }
            )
            store.record_approval(workspace_id, f"fp{workspace_id}", "declined")
        store.delete_workspace(gone)
        assert store.turns(gone).empty and store.findings(gone).empty
        assert store.proposals(gone).empty and store.approvals(gone).empty
        assert len(store.turns(kept)) == len(store.findings(kept)) == 1
        assert len(store.proposals(kept)) == len(store.approvals(kept)) == 1


class TestTurns:
    def test_a_turn_and_its_proposals_are_kept_together(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Rosters")
        turn_id = store.add_turn(
            turn(workspace_id, "Three rosters?"), [proposal("aaa"), proposal("bbb", "Option B")]
        )
        turns = store.turns(workspace_id)
        assert validate_frame(turns, RESEARCH_TURNS) == []
        assert turns["turn_id"].tolist() == [turn_id]
        held = store.proposals(workspace_id)
        assert validate_frame(held, RESEARCH_PROPOSALS) == []
        assert set(held["fingerprint"]) == {"aaa", "bbb"}
        assert set(held["status"]) == {"draft"} and set(held["turn_id"]) == {turn_id}

    def test_a_proposal_made_again_keeps_its_first_record(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Again")
        first = store.add_turn(turn(workspace_id, "Q1"), [proposal("same")])
        store.record_approval(workspace_id, "same", "declined")
        store.add_turn(turn(workspace_id, "Q2"), [proposal("same")])
        held = store.proposals(workspace_id)
        assert len(held) == 1
        assert (held.iloc[0]["turn_id"], held.iloc[0]["status"]) == (first, "declined")

    def test_order_conversations_and_the_last_few(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Order")
        start = datetime(2026, 10, 10, 13, 0, 0)
        for n in range(4):
            store.add_turn(turn(workspace_id, f"Q{n}", at=start + timedelta(minutes=n)))
        assert store.start_conversation(workspace_id) == 2
        store.add_turn(turn(workspace_id, "Q4", conversation=2, at=start + timedelta(minutes=9)))
        assert store.turns(workspace_id)["question"].tolist() == ["Q0", "Q1", "Q2", "Q3", "Q4"]
        assert store.turns(workspace_id, conversation=1, last=2)["question"].tolist() == [
            "Q2",
            "Q3",
        ]
        assert store.turns(workspace_id, conversation=2)["question"].tolist() == ["Q4"]

    def test_an_id_is_never_handed_out_twice(self, store: ResearchStore) -> None:
        """A finding names the turn it came from: after a cleared history, a new turn must
        not take that turn's id."""
        workspace_id = store.create_workspace("Ids")
        first = store.add_turn(turn(workspace_id, "Q1"))
        store.clear_turns(workspace_id)
        assert store.add_turn(turn(workspace_id, "Q2")) > first
        store.delete_workspace(workspace_id)
        assert store.create_workspace("Again") > workspace_id

    def test_clearing_history_keeps_findings_notes_and_proposals(
        self, store: ResearchStore
    ) -> None:
        workspace_id = store.create_workspace("Clear", goal="g")
        store.update_workspace(workspace_id, notes="mine")
        turn_id = store.add_turn(turn(workspace_id, "Q"), [proposal("p")])
        store.add_finding(
            {
                "workspace_id": workspace_id,
                "turn_id": turn_id,
                "title": "Worth keeping",
                "question": "Q",
                "asked_at": datetime(2026, 10, 10),
            }
        )
        assert store.clear_turns(workspace_id) == 1
        assert store.turns(workspace_id).empty
        assert len(store.findings(workspace_id)) == len(store.proposals(workspace_id)) == 1
        assert store.workspace(workspace_id)["notes"] == "mine"


class TestFindingsAndApprovals:
    def test_findings_can_be_renamed_and_deleted(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Findings")
        finding_id = store.add_finding(
            {
                "workspace_id": workspace_id,
                "turn_id": None,
                "title": " Defense ",
                "note": "  ",
                "question": "How good?",
                "asked_at": datetime(2026, 10, 10),
            }
        )
        found = store.findings(workspace_id)
        assert validate_frame(found, RESEARCH_FINDINGS) == []
        assert found.iloc[0]["title"] == "Defense" and pd.isna(found.iloc[0]["note"])
        store.update_finding(finding_id, title="Defence, kept", note="see r1")
        assert store.findings(workspace_id).iloc[0]["note"] == "see r1"
        store.delete_finding(finding_id)
        assert store.findings(workspace_id).empty
        with pytest.raises(ResearchNotFound):
            store.delete_finding(finding_id)

    def test_each_press_is_logged_and_settles_the_proposal(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Presses")
        store.add_turn(turn(workspace_id, "Q"), [proposal("a"), proposal("b"), proposal("c")])
        store.record_approval(workspace_id, "a", "refused", detail="The data was rebuilt.")
        store.record_approval(workspace_id, "a", "saved", roster_id=7)
        store.record_approval(workspace_id, "a", "already_saved", roster_id=7)
        store.record_approval(workspace_id, "b", "declined")
        log = store.approvals(workspace_id)
        assert validate_frame(log, RESEARCH_APPROVALS) == []
        assert log["action"].tolist() == ["refused", "saved", "already_saved", "declined"]
        status = store.proposals(workspace_id).set_index("fingerprint")
        assert (status.at["a", "status"], status.at["a", "roster_id"]) == ("saved", 7)
        assert status.at["b", "status"] == "declined" and status.at["c", "status"] == "draft"
        with pytest.raises(StorageError, match="an approval is one of"):
            store.record_approval(workspace_id, "c", "approved")


def experiment(fingerprint: str, workspace_id: int, *, model: str = "player_value") -> dict:
    return {
        "workspace_id": workspace_id,
        "turn_id": None,
        "fingerprint": fingerprint,
        "model": model,
        "title": "Rookies by draft place",
        "note": None,
        "payload": "{}",
    }


class TestExperiments:
    """A8: the experiment proposals a user keeps, beside findings."""

    def test_kept_listed_annotated_and_deleted(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Ideas")
        first, new = store.keep_experiment(experiment("a", workspace_id))
        second, _ = store.keep_experiment(experiment("b", workspace_id, model="postseason"))
        assert new
        kept = store.experiments(workspace_id)
        assert validate_frame(kept, RESEARCH_EXPERIMENTS) == []
        assert kept["fingerprint"].tolist() == ["b", "a"], "the newest first"
        store.annotate_experiment(first, "  try it after the season  ")
        notes = store.experiments(workspace_id).set_index("experiment_id")["note"]
        assert notes[first] == "try it after the season" and pd.isna(notes[second])
        store.delete_experiment(second)
        assert store.experiments(workspace_id)["fingerprint"].tolist() == ["a"]
        with pytest.raises(ResearchNotFound):
            store.delete_experiment(second)
        with pytest.raises(ResearchNotFound):
            store.annotate_experiment(second, "gone")

    def test_one_kept_twice_is_kept_once(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Twice")
        first, new = store.keep_experiment(experiment("a", workspace_id))
        again, new_again = store.keep_experiment(experiment("a", workspace_id))
        assert (first, new) == (again, True) and not new_again
        assert len(store.experiments(workspace_id)) == 1

    def test_only_a_tested_model_is_kept(self, store: ResearchStore) -> None:
        workspace_id = store.create_workspace("Rules")
        with pytest.raises(StorageError, match="an experiment proposal is for one of"):
            store.keep_experiment(experiment("a", workspace_id, model="archetypes"))

    def test_they_go_with_their_workspace_and_outlast_its_history(
        self, store: ResearchStore
    ) -> None:
        kept = store.create_workspace("Kept")
        gone = store.create_workspace("Gone")
        store.add_turn(turn(kept, "Suggest an experiment"))
        store.keep_experiment(experiment("a", kept))
        store.keep_experiment(experiment("b", gone))
        store.clear_turns(kept)
        store.delete_workspace(gone)
        assert store.experiments(kept)["fingerprint"].tolist() == ["a"]
        assert store.experiments(gone).empty


class TestVersions:
    def test_a_file_from_before_a8_gains_experiment_proposals(self, path: Path) -> None:
        """Version 2 (A8): a file made at version 1 is copied aside and brought forward, and
        then holds the table exactly as a new file does."""
        with ResearchStore(path) as first:
            kept = first.create_workspace("From A7")
        made_at_a7 = sqlite3.connect(path)
        try:
            made_at_a7.execute("DROP TABLE research_experiments")
            made_at_a7.execute("DELETE FROM research_schema WHERE version = 2")
            made_at_a7.commit()
        finally:
            made_at_a7.close()
        with ResearchStore(path) as upgraded:
            assert upgraded.version() == 2 and upgraded.backup is not None
            assert upgraded.workspace(kept)["name"] == "From A7"
            upgraded.keep_experiment(experiment("a", kept))
            assert len(upgraded.experiments(kept)) == 1
        fresh = path.parent / "fresh.sqlite"
        with ResearchStore(fresh):
            pass
        assert _schema(path, "research_experiments") == _schema(fresh, "research_experiments")

    def later(self, *, fails: bool = False) -> tuple[Migration, ...]:
        def add_index(connection) -> None:  # type: ignore[no-untyped-def]
            connection.execute(text("CREATE INDEX ix_turns_question ON research_turns (question)"))
            if fails:
                raise RuntimeError("the second step failed")

        return (*MIGRATIONS, Migration(MIGRATIONS[-1].version + 1, "An index.", add_index))

    def test_an_older_file_is_copied_aside_then_brought_forward(self, path: Path) -> None:
        with ResearchStore(path) as first:
            kept = first.create_workspace("Kept through the upgrade")
        with ResearchStore(path, migrations=self.later()) as upgraded:
            assert upgraded.version() == MIGRATIONS[-1].version + 1
            assert upgraded.workspace(kept)["name"] == "Kept through the upgrade"
            backup = upgraded.backup
        assert backup is not None and backup.parent == path.parent / "backups"
        copy = sqlite3.connect(backup)
        try:
            names = {row[0] for row in copy.execute("SELECT name FROM research_workspaces")}
            versions = [row[0] for row in copy.execute("SELECT version FROM research_schema")]
        finally:
            copy.close()
        assert names == {"Kept through the upgrade"}
        assert versions == [m.version for m in MIGRATIONS], "the copy is as it was before"

    def test_a_failed_step_leaves_the_file_as_it_was(self, path: Path) -> None:
        with ResearchStore(path) as first:
            first.create_workspace("Safe")
        with pytest.raises(RuntimeError, match="second step failed"):
            ResearchStore(path, migrations=self.later(fails=True))
        with ResearchStore(path) as again:
            assert again.version() == MIGRATIONS[-1].version
            assert again.workspaces()["name"].tolist() == ["Safe"]

    def test_a_file_from_a_later_lab_is_refused(self, path: Path) -> None:
        with ResearchStore(path, migrations=self.later()):
            pass
        with pytest.raises(ResearchUnreadable, match="later version of the lab"):
            ResearchStore(path)

    def test_a_file_that_is_not_the_store_is_refused(self, path: Path) -> None:
        path.parent.mkdir(parents=True)
        other = sqlite3.connect(path)
        try:
            other.execute("CREATE TABLE something_else (x INTEGER)")
            other.commit()
        finally:
            other.close()
        with pytest.raises(ResearchUnreadable, match="not the lab's research store"):
            ResearchStore(path)


NOISE = bytes(range(256)) * 16
"""Four kilobytes that are not a database."""


class TestDamage:
    """A9: a file the store cannot use is refused in words that say what to do, nothing is
    written to it, and on request it is set aside - kept - so that a new store starts."""

    @pytest.mark.parametrize("damage", ["noise", "cut in half"])
    def test_a_damaged_file_is_refused_and_left_as_it_is(self, path: Path, damage: str) -> None:
        with ResearchStore(path) as first:
            for number in range(40):
                first.create_workspace(f"Workspace {number}", goal="x" * 200)
        whole = path.read_bytes()
        broken = NOISE if damage == "noise" else whole[: len(whole) // 2]
        path.write_bytes(broken)
        with pytest.raises(ResearchUnreadable) as caught:
            ResearchStore(path)
        assert caught.value.path == path
        assert "Set it aside" in str(caught.value) and "backups" in str(caught.value)
        assert "[SQL:" not in caught.value.reason, "SQLite's words, not SQLAlchemy's"
        assert path.read_bytes() == broken, "nothing was written to it"

    def test_a_file_is_checked_again_only_once_it_has_changed(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A page opens the store a dozen times a run: an unchanged file is checked once."""
        checks: list[int] = []
        real = research._quick_check

        def counted(engine):  # type: ignore[no-untyped-def]
            checks.append(1)
            return real(engine)

        monkeypatch.setattr(research, "_quick_check", counted)
        with ResearchStore(path) as made:
            made.create_workspace("One")
        for _ in range(3):
            with ResearchStore(path):
                pass
        assert len(checks) == 1, "a new file is not checked; an unchanged one once"
        with ResearchStore(path) as store:
            store.create_workspace("Two")
        with ResearchStore(path):
            pass
        assert len(checks) == 2, "a write changes the file, and it is checked again"

    def test_a_locked_file_is_not_called_damaged(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Locked or out of reach is worth another try, and the file is fine: it is never
        offered to be set aside."""
        with ResearchStore(path):
            pass

        def locked(self: ResearchStore) -> None:
            raise OperationalError(
                "PRAGMA quick_check", {}, sqlite3.OperationalError("database is locked")
            )

        monkeypatch.setattr(ResearchStore, "_check_readable", locked)
        with pytest.raises(OperationalError, match="database is locked"):
            ResearchStore(path)

    def test_set_aside_keeps_the_file_and_its_log_and_a_new_store_starts(self, path: Path) -> None:
        path.parent.mkdir(parents=True)
        path.write_bytes(NOISE)
        log = path.with_name(path.name + "-wal")
        log.write_bytes(b"the log")
        moved = set_aside(path, datetime(2026, 10, 11, 9, 30, 0))
        assert moved == path.with_name("assistant-set-aside-20261011T093000.sqlite")
        assert moved.read_bytes() == NOISE and not path.exists()
        assert moved.with_name(moved.name + "-wal").read_bytes() == b"the log"
        assert not log.exists()
        with ResearchStore(path) as fresh:
            assert fresh.version() == MIGRATIONS[-1].version and fresh.workspaces().empty

    def test_two_set_aside_in_one_second_are_both_kept(self, path: Path) -> None:
        moment = datetime(2026, 10, 11, 9, 30, 0)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"first")
        first = set_aside(path, moment)
        path.write_bytes(b"second")
        second = set_aside(path, moment)
        assert first is not None and second is not None and first != second
        assert (first.read_bytes(), second.read_bytes()) == (b"first", b"second")
        assert set_aside(path, moment) is None, "nothing there, nothing moved"


def _schema(path: Path, table: str) -> tuple:
    """A table as SQLite made it: its statement and its indexes."""
    connection = sqlite3.connect(path)
    try:
        return tuple(
            connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE tbl_name = ? ORDER BY name",
                (table,),
            ).fetchall()
        )
    finally:
        connection.close()
