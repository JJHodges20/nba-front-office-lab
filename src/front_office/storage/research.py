"""``data/assistant/assistant.sqlite``: the user's research with the assistant (decision
0018, A6).

A file of its own, which no build touches: workspaces, the questions asked in them and the
answers they got, bookmarked findings, proposed rosters and every press of a save or
decline button, and the experiment proposals the user keeps (version 2, A8). Tables are made from the contracts in ``domain/tables/research.py``, and
deleting a workspace deletes what it holds through their foreign keys.

The file is versioned. A new file is made at the latest version. An older one is first
copied to ``backups/`` beside it with SQLite's own backup, then brought forward one version
at a time in a single transaction, so a failed step leaves it as it was. A file made by a
later lab is refused rather than guessed at, and so is a file that is not this store.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import pandas as pd
from sqlalchemy import Connection, Engine, MetaData, create_engine, delete, func, inspect, select
from sqlalchemy import insert as sql_insert
from sqlalchemy import update as sql_update

from front_office.domain.experiments import TESTED_MODELS
from front_office.domain.seasons import Season
from front_office.domain.tables import RESEARCH_TABLES
from front_office.domain.tables.research import (
    APPROVAL_ACTIONS,
    PROPOSAL_STATUSES,
    RESEARCH_APPROVALS,
    RESEARCH_EXPERIMENTS,
    RESEARCH_FINDINGS,
    RESEARCH_PROPOSALS,
    RESEARCH_SCHEMA,
    RESEARCH_TURNS,
    RESEARCH_WORKSPACES,
    SEASON_TYPES,
)
from front_office.storage.database import (
    LOCK_TIMEOUT_SECONDS,
    StorageError,
    configure_connections,
)
from front_office.storage.schema import build_tables
from front_office.storage.warehouse import frame_from_rows

MAX_NAME_LENGTH = 60
BACKUPS = "backups"
FOCUS = ("season", "season_type", "team_id", "player_id", "roster_id")
EDITABLE = ("name", "goal", "notes", "archived", *FOCUS)


class ResearchNotFound(StorageError):
    """No workspace, turn or finding with that id."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One version of the store: what it adds, and how a file at the version before is
    brought to it. Version 1 is the first; a new file is made at the latest directly."""

    version: int
    note: str
    apply: Callable[[Connection], None]


def _first(connection: Connection) -> None:
    raise StorageError("version 1 is where a store begins; nothing comes before it")


def _experiments(connection: Connection) -> None:
    """Version 2 (A8): the experiment proposals a user keeps. The table is made from its
    contract, as a new file makes it; a later change to the table needs a version of its
    own, and a test checks that a file brought forward matches a new one."""
    tables = build_tables(
        MetaData(), RESEARCH_TABLES, enforce_references=True, never_reuse_ids=True
    )
    tables[RESEARCH_EXPERIMENTS.name].create(connection)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "Workspaces, questions and answers, findings, proposals, approvals.", _first),
    Migration(2, "Experiment proposals kept in a workspace.", _experiments),
)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ResearchStore:
    """The research store. Open it in a ``with`` block: on Windows an open connection keeps
    the file locked."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] = _utc_now,
        migrations: Sequence[Migration] = MIGRATIONS,
    ) -> None:
        self.path = Path(path)
        self._now = now
        self._migrations = tuple(migrations)
        fresh = not self.path.exists() or self.path.stat().st_size == 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path.as_posix()}", connect_args={"timeout": LOCK_TIMEOUT_SECONDS}
        )
        configure_connections(self.engine)
        self.metadata = MetaData()
        self.tables = build_tables(
            self.metadata, RESEARCH_TABLES, enforce_references=True, never_reuse_ids=True
        )
        self.backup: Path | None = None
        """Where the file was copied before this opening migrated it, if it did."""
        try:
            self._bring_up_to_date(fresh)
        except BaseException:
            self.engine.dispose()
            raise

    def __enter__(self) -> ResearchStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.dispose()

    def dispose(self) -> None:
        self.engine.dispose()

    # --- versions --------------------------------------------------------------------------

    @property
    def latest(self) -> int:
        return self._migrations[-1].version

    def version(self) -> int:
        schema = self.tables[RESEARCH_SCHEMA.name]
        with self.engine.connect() as connection:
            found = connection.execute(select(func.max(schema.c.version))).scalar()
        return int(found or 0)

    def _bring_up_to_date(self, fresh: bool) -> None:
        schema = self.tables[RESEARCH_SCHEMA.name]
        with self.engine.connect() as connection:
            names = set(inspect(connection).get_table_names())
        if fresh or not names:
            moment = self._now()
            with self.engine.begin() as connection:
                self.metadata.create_all(connection)
                connection.execute(
                    sql_insert(schema),
                    [
                        {"version": step.version, "note": step.note, "applied_at": moment}
                        for step in self._migrations
                    ],
                )
            return
        if RESEARCH_SCHEMA.name not in names:
            raise StorageError(
                f"{self.path} is not the lab's research store: it has no version table. "
                "Move it aside and the lab will start a new one."
            )
        version = self.version()
        if version > self.latest:
            raise StorageError(
                f"{self.path} was made by a later version of the lab (version {version}; "
                f"this one knows up to {self.latest}). It is left as it is."
            )
        if version == self.latest:
            return
        self.backup = self._copy_aside(version)
        moment = self._now()
        with self.engine.begin() as connection:
            for step in self._migrations:
                if step.version <= version:
                    continue
                step.apply(connection)
                connection.execute(
                    sql_insert(schema).values(
                        version=step.version, note=step.note, applied_at=moment
                    )
                )

    def _copy_aside(self, version: int) -> Path:
        folder = self.path.parent / BACKUPS
        folder.mkdir(exist_ok=True)
        target = folder / f"{self.path.stem}-v{version}-{self._now():%Y%m%dT%H%M%S}.sqlite"
        source = sqlite3.connect(self.path)
        try:
            copy = sqlite3.connect(target)
            try:
                source.backup(copy)
            finally:
                copy.close()
        finally:
            source.close()
        return target

    # --- workspaces ------------------------------------------------------------------------

    def workspaces(self, *, archived: bool | None = False) -> pd.DataFrame:
        """Workspaces, the most recently changed first: the active ones, the archived ones
        (``archived=True``) or all (``None``)."""
        table = self.tables[RESEARCH_WORKSPACES.name]
        statement = select(table).order_by(table.c.updated_at.desc(), table.c.workspace_id.desc())
        if archived is not None:
            statement = statement.where(table.c.archived.is_(archived))
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return frame_from_rows(rows, RESEARCH_WORKSPACES)

    def workspace(self, workspace_id: int) -> dict[str, Any]:
        table = self.tables[RESEARCH_WORKSPACES.name]
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(table).where(table.c.workspace_id == workspace_id))
                .mappings()
                .first()
            )
        if row is None:
            raise ResearchNotFound(f"no workspace with id {workspace_id}")
        return dict(row)

    def create_workspace(self, name: str, *, goal: str | None = None, **focus: Any) -> int:
        table = self.tables[RESEARCH_WORKSPACES.name]
        clean = _clean_name(name)
        values = _checked_focus(focus)
        moment = self._now()
        with self.engine.begin() as connection:
            self._require_unique(connection, clean)
            result = connection.execute(
                sql_insert(table).values(
                    name=clean,
                    goal=_text(goal),
                    notes=None,
                    conversation=1,
                    archived=False,
                    created_at=moment,
                    updated_at=moment,
                    **{key: values.get(key) for key in FOCUS},
                )
            )
            return int(result.inserted_primary_key[0])

    def update_workspace(self, workspace_id: int, **changes: Any) -> None:
        """Change a workspace's name, goal, notes, focus or archived state; ``None`` clears
        a field that may be empty."""
        unknown = sorted(set(changes) - set(EDITABLE))
        if unknown:
            raise StorageError(f"a workspace has no editable field {unknown}")
        values: dict[str, Any] = {}
        if "name" in changes:
            values["name"] = _clean_name(changes["name"])
        for key in ("goal", "notes"):
            if key in changes:
                values[key] = _text(changes[key])
        if "archived" in changes:
            values["archived"] = bool(changes["archived"])
        values |= _checked_focus({key: changes[key] for key in FOCUS if key in changes})
        table = self.tables[RESEARCH_WORKSPACES.name]
        with self.engine.begin() as connection:
            self._require(connection, workspace_id)
            if "name" in values:
                self._require_unique(connection, values["name"], other_than=workspace_id)
            connection.execute(
                sql_update(table)
                .where(table.c.workspace_id == workspace_id)
                .values(**values, updated_at=self._now())
            )

    def delete_workspace(self, workspace_id: int) -> None:
        """Delete a workspace and everything it holds."""
        table = self.tables[RESEARCH_WORKSPACES.name]
        with self.engine.begin() as connection:
            self._require(connection, workspace_id)
            connection.execute(delete(table).where(table.c.workspace_id == workspace_id))

    def start_conversation(self, workspace_id: int) -> int:
        """Begin a new conversation in the workspace: a follow-up reads only the turns of
        the conversation under way. Returns its number."""
        table = self.tables[RESEARCH_WORKSPACES.name]
        with self.engine.begin() as connection:
            current = self._require(connection, workspace_id)["conversation"]
            connection.execute(
                sql_update(table)
                .where(table.c.workspace_id == workspace_id)
                .values(conversation=int(current) + 1, updated_at=self._now())
            )
        return int(current) + 1

    # --- turns -----------------------------------------------------------------------------

    def add_turn(self, turn: Mapping[str, Any], proposals: Sequence[Mapping[str, Any]] = ()) -> int:
        """Record a question and its answer, and the rosters it proposed, together. A
        proposal the workspace already holds keeps its first record and its decision."""
        turns = self.tables[RESEARCH_TURNS.name]
        held = self.tables[RESEARCH_PROPOSALS.name]
        workspaces = self.tables[RESEARCH_WORKSPACES.name]
        workspace_id = int(turn["workspace_id"])
        with self.engine.begin() as connection:
            self._require(connection, workspace_id)
            turn_id = int(
                connection.execute(sql_insert(turns).values(**turn)).inserted_primary_key[0]
            )
            for proposal in proposals:
                known = connection.execute(
                    select(held.c.fingerprint).where(
                        held.c.workspace_id == workspace_id,
                        held.c.fingerprint == proposal["fingerprint"],
                    )
                ).first()
                if known is None:
                    connection.execute(
                        sql_insert(held).values(
                            **proposal,
                            workspace_id=workspace_id,
                            turn_id=turn_id,
                            status="draft",
                            roster_id=None,
                            decided_at=None,
                        )
                    )
            connection.execute(
                sql_update(workspaces)
                .where(workspaces.c.workspace_id == workspace_id)
                .values(updated_at=self._now())
            )
        return turn_id

    def turns(
        self,
        workspace_id: int,
        *,
        conversation: int | None = None,
        last: int | None = None,
    ) -> pd.DataFrame:
        """A workspace's turns in the order asked: all, or one conversation's, or the last
        few of them."""
        table = self.tables[RESEARCH_TURNS.name]
        statement = select(table).where(table.c.workspace_id == workspace_id)
        if conversation is not None:
            statement = statement.where(table.c.conversation == conversation)
        statement = statement.order_by(table.c.asked_at.desc(), table.c.turn_id.desc())
        if last is not None:
            statement = statement.limit(last)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return frame_from_rows(list(reversed(rows)), RESEARCH_TURNS)

    def turn(self, turn_id: int) -> dict[str, Any]:
        table = self.tables[RESEARCH_TURNS.name]
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(table).where(table.c.turn_id == turn_id))
                .mappings()
                .first()
            )
        if row is None:
            raise ResearchNotFound(f"no turn with id {turn_id}")
        return dict(row)

    def clear_turns(self, workspace_id: int) -> int:
        """Forget a workspace's questions and answers; its findings, notes and proposals
        stay. Returns how many turns went."""
        table = self.tables[RESEARCH_TURNS.name]
        workspaces = self.tables[RESEARCH_WORKSPACES.name]
        with self.engine.begin() as connection:
            self._require(connection, workspace_id)
            result = connection.execute(delete(table).where(table.c.workspace_id == workspace_id))
            connection.execute(
                sql_update(workspaces)
                .where(workspaces.c.workspace_id == workspace_id)
                .values(updated_at=self._now())
            )
        return int(result.rowcount or 0)

    # --- findings --------------------------------------------------------------------------

    def add_finding(self, finding: Mapping[str, Any]) -> int:
        table = self.tables[RESEARCH_FINDINGS.name]
        values = dict(finding)
        values["title"] = _clean_name(values["title"])
        values["note"] = _text(values.get("note"))
        with self.engine.begin() as connection:
            self._require(connection, int(values["workspace_id"]))
            result = connection.execute(sql_insert(table).values(**values, created_at=self._now()))
            return int(result.inserted_primary_key[0])

    def findings(self, workspace_id: int) -> pd.DataFrame:
        """A workspace's findings, the newest first."""
        table = self.tables[RESEARCH_FINDINGS.name]
        statement = (
            select(table)
            .where(table.c.workspace_id == workspace_id)
            .order_by(table.c.created_at.desc(), table.c.finding_id.desc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return frame_from_rows(rows, RESEARCH_FINDINGS)

    def update_finding(self, finding_id: int, *, title: str, note: str | None) -> None:
        table = self.tables[RESEARCH_FINDINGS.name]
        with self.engine.begin() as connection:
            result = connection.execute(
                sql_update(table)
                .where(table.c.finding_id == finding_id)
                .values(title=_clean_name(title), note=_text(note))
            )
        if not result.rowcount:
            raise ResearchNotFound(f"no finding with id {finding_id}")

    def delete_finding(self, finding_id: int) -> None:
        table = self.tables[RESEARCH_FINDINGS.name]
        with self.engine.begin() as connection:
            result = connection.execute(delete(table).where(table.c.finding_id == finding_id))
        if not result.rowcount:
            raise ResearchNotFound(f"no finding with id {finding_id}")

    # --- proposals and approvals -----------------------------------------------------------

    def proposals(self, workspace_id: int) -> pd.DataFrame:
        """A workspace's proposals, the newest first."""
        table = self.tables[RESEARCH_PROPOSALS.name]
        statement = (
            select(table)
            .where(table.c.workspace_id == workspace_id)
            .order_by(table.c.created_at.desc(), table.c.label)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return frame_from_rows(rows, RESEARCH_PROPOSALS)

    def record_approval(
        self,
        workspace_id: int,
        fingerprint: str,
        action: str,
        *,
        roster_id: int | None = None,
        detail: str | None = None,
    ) -> int:
        """Log a press of a proposal's save or decline button, and settle the proposal's
        status where the press decided it: saved (or found saved) or declined."""
        if action not in APPROVAL_ACTIONS:
            raise StorageError(f"an approval is one of {list(APPROVAL_ACTIONS)}, not {action!r}")
        approvals = self.tables[RESEARCH_APPROVALS.name]
        held = self.tables[RESEARCH_PROPOSALS.name]
        moment = self._now()
        status = {"saved": "saved", "already_saved": "saved", "declined": "declined"}.get(action)
        with self.engine.begin() as connection:
            self._require(connection, workspace_id)
            result = connection.execute(
                sql_insert(approvals).values(
                    workspace_id=workspace_id,
                    fingerprint=fingerprint,
                    action=action,
                    roster_id=roster_id,
                    detail=_text(detail),
                    at=moment,
                )
            )
            if status is not None:
                assert status in PROPOSAL_STATUSES
                connection.execute(
                    sql_update(held)
                    .where(held.c.workspace_id == workspace_id, held.c.fingerprint == fingerprint)
                    .values(status=status, roster_id=roster_id, decided_at=moment)
                )
            return int(result.inserted_primary_key[0])

    def approvals(self, workspace_id: int) -> pd.DataFrame:
        """Every press of a save or decline button in a workspace, in order."""
        table = self.tables[RESEARCH_APPROVALS.name]
        statement = (
            select(table)
            .where(table.c.workspace_id == workspace_id)
            .order_by(table.c.at, table.c.approval_id)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return frame_from_rows(rows, RESEARCH_APPROVALS)

    # --- experiment proposals (A8) -----------------------------------------------------------

    def keep_experiment(self, experiment: Mapping[str, Any]) -> tuple[int, bool]:
        """Keep an experiment proposal in its workspace. One the workspace holds already, by
        its fingerprint, is not kept twice. Returns its id, and whether it was new."""
        table = self.tables[RESEARCH_EXPERIMENTS.name]
        values = dict(experiment)
        if values.get("model") not in TESTED_MODELS:
            raise StorageError(
                f"an experiment proposal is for one of {list(TESTED_MODELS)}, not "
                f"{values.get('model')!r}"
            )
        values["note"] = _text(values.get("note"))
        workspace_id = int(values["workspace_id"])
        with self.engine.begin() as connection:
            self._require(connection, workspace_id)
            known = connection.execute(
                select(table.c.experiment_id).where(
                    table.c.workspace_id == workspace_id,
                    table.c.fingerprint == values["fingerprint"],
                )
            ).first()
            if known is not None:
                return int(known[0]), False
            result = connection.execute(sql_insert(table).values(**values, created_at=self._now()))
            self._touch(connection, workspace_id)
            return int(result.inserted_primary_key[0]), True

    def experiments(self, workspace_id: int) -> pd.DataFrame:
        """A workspace's kept experiment proposals, the newest first."""
        table = self.tables[RESEARCH_EXPERIMENTS.name]
        statement = (
            select(table)
            .where(table.c.workspace_id == workspace_id)
            .order_by(table.c.created_at.desc(), table.c.experiment_id.desc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return frame_from_rows(rows, RESEARCH_EXPERIMENTS)

    def annotate_experiment(self, experiment_id: int, note: str | None) -> None:
        table = self.tables[RESEARCH_EXPERIMENTS.name]
        with self.engine.begin() as connection:
            result = connection.execute(
                sql_update(table)
                .where(table.c.experiment_id == experiment_id)
                .values(note=_text(note))
            )
        if not result.rowcount:
            raise ResearchNotFound(f"no experiment proposal with id {experiment_id}")

    def delete_experiment(self, experiment_id: int) -> None:
        table = self.tables[RESEARCH_EXPERIMENTS.name]
        with self.engine.begin() as connection:
            result = connection.execute(delete(table).where(table.c.experiment_id == experiment_id))
        if not result.rowcount:
            raise ResearchNotFound(f"no experiment proposal with id {experiment_id}")

    # --- checks ----------------------------------------------------------------------------

    def _touch(self, connection: Connection, workspace_id: int) -> None:
        """Mark the workspace changed, so it lists among the most recent."""
        table = self.tables[RESEARCH_WORKSPACES.name]
        connection.execute(
            sql_update(table)
            .where(table.c.workspace_id == workspace_id)
            .values(updated_at=self._now())
        )

    def _require(self, connection: Connection, workspace_id: int) -> dict[str, Any]:
        table = self.tables[RESEARCH_WORKSPACES.name]
        row = (
            connection.execute(select(table).where(table.c.workspace_id == workspace_id))
            .mappings()
            .first()
        )
        if row is None:
            raise ResearchNotFound(f"no workspace with id {workspace_id}")
        return dict(row)

    def _require_unique(
        self, connection: Connection, name: str, *, other_than: int | None = None
    ) -> None:
        table = self.tables[RESEARCH_WORKSPACES.name]
        statement = select(table.c.workspace_id).where(func.lower(table.c.name) == name.lower())
        if other_than is not None:
            statement = statement.where(table.c.workspace_id != other_than)
        if connection.execute(statement).first() is not None:
            raise StorageError(f"a workspace called {name!r} already exists")


def _clean_name(name: str) -> str:
    clean = " ".join(str(name or "").split())
    if not clean:
        raise StorageError("a name cannot be empty")
    if len(clean) > MAX_NAME_LENGTH:
        raise StorageError(f"a name can be at most {MAX_NAME_LENGTH} characters")
    return clean


def _text(value: object) -> str | None:
    """Free text as stored: stripped, and empty as null."""
    if value is None:
        return None
    clean = str(value).strip()
    return clean or None


def _checked_focus(focus: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(focus) - set(FOCUS))
    if unknown:
        raise StorageError(f"a focus has no field {unknown}")
    values: dict[str, Any] = {}
    if "season" in focus:
        values["season"] = None if focus["season"] is None else Season.parse(focus["season"]).label
    if "season_type" in focus:
        kind = focus["season_type"]
        if kind is not None and kind not in SEASON_TYPES:
            raise StorageError(f"season_type must be one of {list(SEASON_TYPES)}, not {kind!r}")
        values["season_type"] = kind
    for key in ("team_id", "player_id", "roster_id"):
        if key in focus:
            values[key] = None if focus[key] is None else int(focus[key])
    return values
