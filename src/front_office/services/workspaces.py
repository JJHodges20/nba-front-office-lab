"""The user's research with the assistant: workspaces and what they keep (decision 0018, A6).

Reads and writes ``data/assistant/assistant.sqlite`` through ``storage.research``; the lab's
database is only read, for what an answer rests on now. A workspace is made the first time
one is needed. A turn is recorded as it came back, with the data build and the value model
it read, and the rosters it proposed wait in the workspace until the user saves or declines
each - the save goes through ``ProposalService``, and every press is logged. An
experiment proposal is kept only at the user's press, and keeping it changes nothing else
(A8). A follow-up reads only the conversation under way in its own workspace: that is how
one workspace's team or scenario never leaks into another's.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Any

import pandas as pd

from front_office.config.assistant import load_assistant_settings
from front_office.config.settings import ConfigError
from front_office.domain.assistant import EvidenceKind, Mode, ResultStatus
from front_office.domain.experiments import ExperimentProposal
from front_office.domain.proposals import RosterProposal
from front_office.domain.research import (
    Approval,
    ExperimentRecord,
    Finding,
    Focus,
    ProposalRecord,
    SavedTurn,
    Workspace,
    payload_parts,
    turn_payload,
)
from front_office.domain.tables.current import SOURCES
from front_office.services.lab import Lab
from front_office.services.proposals import ProposalSaved
from front_office.storage import ResearchStore, StorageError

DEFAULT_NAME = "My research"
HISTORY_TURNS = 3
"""Earlier answered turns a follow-up carries: enough to follow "and in 2012-13?", few
enough to leave the context room for results."""
EXPORT_VERSION = 2
"""2 (A8): the experiment proposals a workspace keeps, under ``experiments``."""
NEWS = (EvidenceKind.CURRENT, EvidenceKind.WEB)
"""What changes by the hour, not by the build: current information and the web."""


class WorkspaceError(ValueError):
    """What the user asked of a workspace cannot be done; the message says why."""


class WorkspaceService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @contextmanager
    def _store(self) -> Iterator[ResearchStore]:
        try:
            with ResearchStore(self._lab.settings.research_path) as store:
                yield store
        except StorageError as error:
            raise WorkspaceError(str(error)) from error

    # --- workspaces ------------------------------------------------------------------------

    def list(self, *, archived: bool | None = False) -> tuple[Workspace, ...]:
        """Workspaces, the most recently used first: the active ones, the archived ones, or
        all (``archived=None``)."""
        with self._store() as store:
            frame = store.workspaces(archived=archived)
        return tuple(_workspace(row) for row in frame.to_dict("records"))

    def get(self, workspace_id: int) -> Workspace:
        with self._store() as store:
            return _workspace(store.workspace(int(workspace_id)))

    def default(self) -> Workspace:
        """The workspace to open on: the most recently used active one, made if there is
        none - under a name no workspace has, archived ones included (the A6 sweep archived
        the only workspace, and a new "My research" clashed with it)."""
        found = self.list()
        if found:
            return found[0]
        taken = {workspace.name.casefold() for workspace in self.list(archived=None)}
        name, number = DEFAULT_NAME, 1
        while name.casefold() in taken:
            number += 1
            name = f"{DEFAULT_NAME} {number}"
        return self.create(name)

    def create(
        self, name: str, *, goal: str | None = None, focus: Focus | None = None
    ) -> Workspace:
        fields = _focus_fields(focus or Focus())
        with self._store() as store:
            workspace_id = store.create_workspace(name, goal=goal, **fields)
            return _workspace(store.workspace(workspace_id))

    def update(self, workspace_id: int, *, focus: Focus | None = None, **changes: Any) -> Workspace:
        """Change a workspace's name, goal, notes or archived state, or its focus whole."""
        if focus is not None:
            changes |= _focus_fields(focus)
        with self._store() as store:
            store.update_workspace(int(workspace_id), **changes)
            return _workspace(store.workspace(int(workspace_id)))

    def delete(self, workspace_id: int) -> None:
        """Delete a workspace and everything it holds. Rosters saved from its proposals stay
        in the Team Builder."""
        with self._store() as store:
            store.delete_workspace(int(workspace_id))

    def new_conversation(self, workspace_id: int) -> int:
        """Start afresh: the next question follows no earlier one. Earlier turns stay in the
        workspace's history."""
        with self._store() as store:
            return store.start_conversation(int(workspace_id))

    def clear_history(self, workspace_id: int) -> int:
        """Forget the workspace's questions and answers; its notes, findings and proposals
        stay. Returns how many went."""
        with self._store() as store:
            cleared = store.clear_turns(int(workspace_id))
            store.start_conversation(int(workspace_id))
        return cleared

    # --- turns -----------------------------------------------------------------------------

    def stamp(self) -> tuple[int | None, str | None]:
        """What an answer made now rests on: the data build and the value model revision."""
        status = self._lab.status()
        if not status.is_built:
            return None, None
        return status.build_id, self._lab.value.status().applied_revision

    def record(self, turn: SavedTurn) -> SavedTurn:
        """Keep a question and what came of it, with the rosters it proposed."""
        answer = turn.answer
        row = {
            "workspace_id": turn.workspace_id,
            "conversation": turn.conversation,
            "asked_at": turn.asked_at,
            "question": turn.question,
            "mode": turn.mode.value,
            **_focus_fields(turn.focus),
            "asked_from": turn.asked_from,
            "about": turn.about,
            "outcome": None if answer is None else answer.outcome.value,
            "answer_text": None if answer is None else answer.text,
            "error": turn.error,
            "build_id": turn.build_id,
            "value_model": turn.value_model,
            "model": None if answer is None else answer.model,
            "policy": None if answer is None else answer.policy,
            "seconds": turn.seconds,
            "payload": turn_payload(turn),
        }
        proposals = [
            {
                "fingerprint": proposal.fingerprint,
                "label": proposal.label,
                "payroll_season": proposal.payroll_season,
                "payload": proposal.model_dump_json(),
                "created_at": turn.asked_at,
            }
            for proposal in _proposals(turn)
        ]
        with self._store() as store:
            turn_id = store.add_turn(row, proposals)
        return replace(turn, turn_id=turn_id)

    def turns(
        self, workspace_id: int, *, conversation: int | None = None, last: int | None = None
    ) -> tuple[SavedTurn, ...]:
        """A workspace's turns in the order asked."""
        with self._store() as store:
            frame = store.turns(int(workspace_id), conversation=conversation, last=last)
        return tuple(_turn(row) for row in frame.to_dict("records"))

    def history(self, workspace_id: int) -> tuple[SavedTurn, ...]:
        """What a follow-up in the workspace carries: the last few answered turns of the
        conversation under way, and nothing from any other workspace or conversation."""
        workspace = self.get(workspace_id)
        turns = self.turns(workspace_id, conversation=workspace.conversation)
        answered = [turn for turn in turns if turn.answer is not None]
        return tuple(answered[-HISTORY_TURNS:])

    def changed_since(
        self,
        turn: SavedTurn,
        *,
        stamp: tuple[int | None, str | None] | None = None,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """What has changed since the turn was answered, in plain sentences: nothing when
        asking again would read the same data and model. ``stamp`` is :meth:`stamp`, when a
        page checking many turns has read it once. Current information and the web change
        without a build: an answer that read them says when, once the lab would fetch the
        soonest of the current sources again (``configs/assistant.yaml``)."""
        build, value = self.stamp() if stamp is None else stamp
        said = []
        if turn.build_id is not None and build != turn.build_id:
            said.append(
                f"The lab's data has been rebuilt since (build {turn.build_id} then, {build} now)."
            )
        if turn.value_model is not None and value != turn.value_model:
            said.append(
                f"The player value model has changed since ({turn.value_model} then, {value} now)."
            )
        news = turn.answer is not None and any(e.kind in NEWS for e in turn.answer.evidence)
        soonest = self._soonest_refetch
        if news and soonest is not None and (now or _now()) - turn.asked_at >= soonest:
            said.append(
                f"It read current information or the web as of {turn.asked_at:%Y-%m-%d %H:%M} "
                "UTC, which may have changed since."
            )
        return tuple(said)

    @cached_property
    def _soonest_refetch(self) -> timedelta | None:
        """How soon a question fetches any current source again; ``None`` when the
        assistant's settings cannot be read (the page says so on its own)."""
        try:
            current = load_assistant_settings(self._lab.settings.config_dir).current
        except (ConfigError, OSError):
            return None
        return timedelta(minutes=min(current.minutes(source) for source in SOURCES))

    # --- findings --------------------------------------------------------------------------

    def save_finding(self, turn: SavedTurn, title: str, note: str | None = None) -> Finding:
        """Bookmark an answer: a copy of what it said and rested on, which outlasts the
        workspace's history."""
        answer = turn.answer
        evidence = None
        if answer is not None and answer.evidence:
            evidence = "\n".join(_evidence_line(item) for item in answer.evidence)
        with self._store() as store:
            finding_id = store.add_finding(
                {
                    "workspace_id": turn.workspace_id,
                    "turn_id": turn.turn_id,
                    "title": title,
                    "note": note,
                    "question": turn.question,
                    "answer_text": None if answer is None else answer.text,
                    "evidence": evidence,
                    "asked_at": turn.asked_at,
                    "build_id": turn.build_id,
                }
            )
            frame = store.findings(turn.workspace_id)
        row = frame[frame["finding_id"] == finding_id].iloc[0].to_dict()
        return _finding(row)

    def findings(self, workspace_id: int) -> tuple[Finding, ...]:
        with self._store() as store:
            frame = store.findings(int(workspace_id))
        return tuple(_finding(row) for row in frame.to_dict("records"))

    def update_finding(self, finding_id: int, *, title: str, note: str | None) -> None:
        with self._store() as store:
            store.update_finding(int(finding_id), title=title, note=note)

    def delete_finding(self, finding_id: int) -> None:
        with self._store() as store:
            store.delete_finding(int(finding_id))

    # --- proposals -------------------------------------------------------------------------

    def proposals(self, workspace_id: int) -> tuple[ProposalRecord, ...]:
        """The rosters proposed in the workspace, the newest first, with what the user did."""
        with self._store() as store:
            frame = store.proposals(int(workspace_id))
        return tuple(_proposal(row) for row in frame.to_dict("records"))

    def save_proposal(
        self, workspace_id: int, proposal: RosterProposal, name: str
    ) -> ProposalSaved:
        """The user's press of *Save approved roster*: saved through ``ProposalService`` -
        checked, in one transaction, never twice - and logged in the workspace."""
        saved = self._lab.proposals.save(proposal, name)
        action = "saved" if saved.created else "already_saved" if saved.saved else "refused"
        with self._store() as store:
            store.record_approval(
                int(workspace_id),
                proposal.fingerprint,
                action,
                roster_id=saved.roster_id,
                detail=" ".join(saved.refused) or None,
            )
        return saved

    def decline_proposal(self, workspace_id: int, fingerprint: str) -> None:
        """The user's press of *Decline*: nothing is saved, and the proposal says so."""
        with self._store() as store:
            store.record_approval(int(workspace_id), fingerprint, "declined")

    # --- experiment proposals (A8) ----------------------------------------------------------

    def keep_experiment(
        self,
        workspace_id: int,
        proposal: ExperimentProposal,
        *,
        turn_id: int | None = None,
        note: str | None = None,
    ) -> ExperimentRecord:
        """The user's press of *Keep in the workspace*: the proposal as drafted, kept for
        review. Kept twice, it is kept once. Nothing in the lab applies it: a change to a
        model is a milestone of its own."""
        with self._store() as store:
            experiment_id, _ = store.keep_experiment(
                {
                    "workspace_id": int(workspace_id),
                    "turn_id": turn_id,
                    "fingerprint": proposal.fingerprint,
                    "model": proposal.model,
                    "title": proposal.title,
                    "note": note,
                    "payload": proposal.model_dump_json(),
                }
            )
            frame = store.experiments(int(workspace_id))
        row = frame[frame["experiment_id"] == experiment_id].iloc[0].to_dict()
        return _experiment(row)

    def experiments(self, workspace_id: int) -> tuple[ExperimentRecord, ...]:
        """The experiment proposals kept in the workspace, the newest first."""
        with self._store() as store:
            frame = store.experiments(int(workspace_id))
        return tuple(_experiment(row) for row in frame.to_dict("records"))

    def annotate_experiment(self, experiment_id: int, note: str | None) -> None:
        with self._store() as store:
            store.annotate_experiment(int(experiment_id), note)

    def delete_experiment(self, experiment_id: int) -> None:
        with self._store() as store:
            store.delete_experiment(int(experiment_id))

    def approvals(self, workspace_id: int) -> tuple[Approval, ...]:
        with self._store() as store:
            frame = store.approvals(int(workspace_id))
        return tuple(
            Approval(
                fingerprint=row["fingerprint"],
                action=row["action"],
                roster_id=_maybe_int(row["roster_id"]),
                detail=_maybe_text(row["detail"]),
                at=row["at"],
            )
            for row in frame.to_dict("records")
        )

    # --- export ----------------------------------------------------------------------------

    def export_json(self, workspace_id: int) -> str:
        """Everything the workspace holds, as JSON: the workspace, its turns with their
        answers, findings, proposals and approvals, and the experiment proposals kept."""
        workspace = self.get(workspace_id)
        with self._store() as store:
            turns = store.turns(int(workspace_id))
            findings = store.findings(int(workspace_id))
            proposals = store.proposals(int(workspace_id))
            approvals = store.approvals(int(workspace_id))
            experiments = store.experiments(int(workspace_id))
        document = {
            "format": "NBA Front Office Lab research workspace",
            "version": EXPORT_VERSION,
            "exported_at": _now().isoformat(timespec="seconds"),
            "workspace": {
                "name": workspace.name,
                "goal": workspace.goal,
                "notes": workspace.notes,
                "focus": _focus_fields(workspace.focus),
                "archived": workspace.archived,
                "created_at": workspace.created_at.isoformat(),
                "updated_at": workspace.updated_at.isoformat(),
            },
            "turns": [
                {**_plain_row(row, drop=("payload",)), **json.loads(row["payload"])}
                for row in turns.to_dict("records")
            ],
            "findings": [_plain_row(row) for row in findings.to_dict("records")],
            "proposals": [
                {**_plain_row(row, drop=("payload",)), "proposal": json.loads(row["payload"])}
                for row in proposals.to_dict("records")
            ],
            "approvals": [_plain_row(row) for row in approvals.to_dict("records")],
            "experiments": [
                {**_plain_row(row, drop=("payload",)), "proposal": json.loads(row["payload"])}
                for row in experiments.to_dict("records")
            ],
        }
        return json.dumps(document, indent=2, ensure_ascii=False, default=str)

    def export_markdown(self, workspace_id: int) -> str:
        """The workspace as a document to read: notes, each question and answer with what it
        rested on, findings, proposals and what was done with them, and the experiment
        proposals kept."""
        workspace = self.get(workspace_id)
        turns = self.turns(workspace_id)
        findings = self.findings(workspace_id)
        proposals = self.proposals(workspace_id)
        experiments = self.experiments(workspace_id)
        lines = [f"# {workspace.name}", ""]
        if workspace.goal:
            lines += [f"*{workspace.goal}*", ""]
        lines += [
            f"Exported from NBA Front Office Lab on {_now():%Y-%m-%d %H:%M} UTC. Figures are "
            "the lab's as they stood when each question was asked; the data build and model "
            "are given with each answer.",
            "",
        ]
        if workspace.notes:
            lines += [
                "## Notes",
                "",
                "Your notes and summaries - not evidence.",
                "",
                workspace.notes,
                "",
            ]
        lines += ["## Questions and answers", ""]
        if not turns:
            lines += ["No questions are kept.", ""]
        for turn in turns:
            lines += [f"### {turn.question}", "", _turn_line(turn), ""]
            if turn.answer is None:
                lines += [f"No answer: {turn.error or 'nothing came back.'}", ""]
                continue
            lines += [turn.answer.text, ""]
            if turn.answer.warnings:
                lines += [*(f"> {note}" for note in turn.answer.warnings), ""]
            if turn.answer.evidence:
                lines += [
                    "Rests on:",
                    *(f"- {_evidence_line(item)}" for item in turn.answer.evidence),
                    "",
                ]
        lines += ["## Findings", ""]
        if not findings:
            lines += ["None saved.", ""]
        for finding in findings:
            lines += [f"### {finding.title}", "", f"Asked: {finding.question}", ""]
            if finding.note:
                lines += [f"Note: {finding.note}", ""]
            if finding.answer_text:
                lines += [finding.answer_text, ""]
            if finding.evidence:
                lines += ["Rests on:", *(f"- {line}" for line in finding.evidence.splitlines()), ""]
        lines += ["## Proposed rosters", ""]
        if not proposals:
            lines += ["None proposed.", ""]
        for record in proposals:
            proposal = record.proposal
            state = {
                "draft": "waiting for your decision",
                "saved": f"saved (roster {record.roster_id})",
                "declined": "declined",
            }[record.status]
            lines += [
                f"### {proposal.label}, {proposal.payroll_season} - {state}",
                "",
                f"Payroll ${proposal.payroll:,} under the {proposal.budget_label.lower()} of "
                f"${proposal.budget:,}; projected net rating {proposal.rating:+.1f}.",
                "",
                "Players: "
                + ", ".join(
                    f"{player.player_name} (${player.salary:,})" for player in proposal.players
                ),
                "",
            ]
        lines += ["## Experiment proposals", ""]
        if not experiments:
            lines += ["None kept.", ""]
        for record in experiments:
            lines += [record.proposal.document(level=3).rstrip(), ""]
            lines += [f"*Kept {record.created_at:%Y-%m-%d %H:%M} UTC.*", ""]
            if record.note:
                lines += [f"Note: {record.note}", ""]
        return "\n".join(lines).rstrip() + "\n"


# --- rows to objects ---------------------------------------------------------------------------


def _workspace(row: dict[str, Any]) -> Workspace:
    return Workspace(
        workspace_id=int(row["workspace_id"]),
        name=str(row["name"]),
        goal=_maybe_text(row.get("goal")),
        notes=_maybe_text(row.get("notes")),
        focus=_focus(row),
        conversation=int(row["conversation"]),
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _turn(row: dict[str, Any]) -> SavedTurn:
    answer, steps, resolved = payload_parts(row["payload"])
    return SavedTurn(
        workspace_id=int(row["workspace_id"]),
        conversation=int(row["conversation"]),
        asked_at=row["asked_at"],
        question=str(row["question"]),
        mode=Mode(row["mode"]),
        focus=_focus(row),
        asked_from=str(row["asked_from"]),
        answer=answer,
        error=_maybe_text(row.get("error")),
        steps=steps,
        seconds=float(row["seconds"]) if not _missing(row.get("seconds")) else 0.0,
        resolved=resolved,
        about=_maybe_text(row.get("about")),
        build_id=_maybe_int(row.get("build_id")),
        value_model=_maybe_text(row.get("value_model")),
        turn_id=int(row["turn_id"]),
    )


def _finding(row: dict[str, Any]) -> Finding:
    return Finding(
        finding_id=int(row["finding_id"]),
        workspace_id=int(row["workspace_id"]),
        turn_id=_maybe_int(row.get("turn_id")),
        title=str(row["title"]),
        note=_maybe_text(row.get("note")),
        question=str(row["question"]),
        answer_text=_maybe_text(row.get("answer_text")),
        evidence=_maybe_text(row.get("evidence")),
        asked_at=row["asked_at"],
        build_id=_maybe_int(row.get("build_id")),
        created_at=row["created_at"],
    )


def _proposal(row: dict[str, Any]) -> ProposalRecord:
    decided = row.get("decided_at")
    return ProposalRecord(
        workspace_id=int(row["workspace_id"]),
        proposal=RosterProposal.model_validate_json(row["payload"]),
        status=str(row["status"]),
        roster_id=_maybe_int(row.get("roster_id")),
        turn_id=_maybe_int(row.get("turn_id")),
        created_at=row["created_at"],
        decided_at=None if _missing(decided) else decided,
    )


def _experiment(row: dict[str, Any]) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=int(row["experiment_id"]),
        workspace_id=int(row["workspace_id"]),
        proposal=ExperimentProposal.model_validate_json(row["payload"]),
        note=_maybe_text(row.get("note")),
        turn_id=_maybe_int(row.get("turn_id")),
        created_at=row["created_at"],
    )


def _focus(row: dict[str, Any]) -> Focus:
    return Focus(
        season=_maybe_text(row.get("season")),
        season_type=_maybe_text(row.get("season_type")),
        team_id=_maybe_int(row.get("team_id")),
        player_id=_maybe_int(row.get("player_id")),
        roster_id=_maybe_int(row.get("roster_id")),
    )


def _focus_fields(focus: Focus) -> dict[str, Any]:
    return {
        "season": focus.season,
        "season_type": focus.season_type,
        "team_id": focus.team_id,
        "player_id": focus.player_id,
        "roster_id": focus.roster_id,
    }


def _proposals(turn: SavedTurn) -> list[RosterProposal]:
    if turn.answer is None:
        return []
    return [
        proposal
        for result in turn.answer.results
        if result.status is ResultStatus.OK
        for proposal in result.proposals
    ]


def _turn_line(turn: SavedTurn) -> str:
    parts = [f"Asked {turn.asked_at:%Y-%m-%d %H:%M} UTC on {turn.asked_from}"]
    if turn.about:
        parts[-1] += f" about {turn.about}"
    parts.append(f"{turn.mode.value} mode")
    if turn.build_id is not None:
        parts.append(f"data build {turn.build_id}")
    if turn.value_model:
        parts.append(f"value model {turn.value_model}")
    if turn.answer is not None and turn.answer.model:
        parts.append(f"answered by {turn.answer.model}, {turn.answer.outcome.value}")
    return "*" + "; ".join(parts) + ".*"


def _evidence_line(item: Any) -> str:
    kind = {
        EvidenceKind.LAB: "The lab's data",
        EvidenceKind.MODEL: "A fitted model",
        EvidenceKind.CONTRACTS: "Your contract file",
        EvidenceKind.CURRENT: "Current information",
        EvidenceKind.WEB: "The web",
        EvidenceKind.DOCS: "The lab's documents",
    }.get(item.kind, str(item.kind))
    line = f"{kind}: {item.label}"
    if item.location:
        line += f" ({item.location})"
    if item.retrieved_at is not None:
        line += f", fetched {item.retrieved_at:%Y-%m-%d %H:%M} UTC"
    return line


def _plain_row(row: dict[str, Any], *, drop: tuple[str, ...] = ()) -> dict[str, Any]:
    plain: dict[str, Any] = {}
    for key, value in row.items():
        if key in drop:
            continue
        if _missing(value):
            plain[key] = None
        elif isinstance(value, pd.Timestamp | datetime):
            plain[key] = value.isoformat()
        elif hasattr(value, "item"):
            plain[key] = value.item()
        else:
            plain[key] = value
    return plain


def _missing(value: object) -> bool:
    try:
        return value is None or bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _maybe_int(value: object) -> int | None:
    return None if _missing(value) else int(value)  # type: ignore[arg-type]


def _maybe_text(value: object) -> str | None:
    return None if _missing(value) else str(value)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
