"""The user's research with the assistant, as a workspace keeps it (decision 0018, A6).

A workspace is a named piece of research: what the user is working on, their notes, and the
season, team, player or roster it looks at when a question names none. It keeps every
question asked in it and the answer that came back, as it came back - the data build and
the value model it read are recorded, and nothing rewrites it; a newer answer comes from
asking again. Findings are answers the user bookmarked, each a copy so that it outlasts the
history it came from. Proposals are the rosters the assistant proposed, waiting until the
user saves or declines each; approvals are every press of those buttons. Experiments are
the experiment proposals for the lab's models the user chose to keep (A8).

The codec turns an answer - its results, their rows and charts, its evidence and proposals
- into plain JSON and back, so that the page can draw an old answer exactly as it was.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from front_office.domain.assistant import (
    Answer,
    Chart,
    Evidence,
    EvidenceKind,
    Mode,
    NameCandidate,
    Outcome,
    ResultStatus,
    Step,
    ToolResult,
)
from front_office.domain.experiments import ExperimentProposal
from front_office.domain.proposals import RosterProposal

RESEARCH_PAGE = "AI Research"
"""Where a question asked on the AI Research page is recorded as asked from."""


@dataclass(frozen=True, slots=True)
class Focus:
    """What a question is about, or a workspace looks at, when the question names nothing:
    the sidebar's choices, a page's, or a workspace's own."""

    season: str | None = None
    season_type: str | None = None
    team_id: int | None = None
    player_id: int | None = None
    roster_id: int | None = None

    @property
    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (
                self.season,
                self.season_type,
                self.team_id,
                self.player_id,
                self.roster_id,
            )
        )

    def over(self, other: Focus) -> Focus:
        """This focus, with ``other`` filling what it leaves open."""
        return Focus(
            season=self.season if self.season is not None else other.season,
            season_type=self.season_type if self.season_type is not None else other.season_type,
            team_id=self.team_id if self.team_id is not None else other.team_id,
            player_id=self.player_id if self.player_id is not None else other.player_id,
            roster_id=self.roster_id if self.roster_id is not None else other.roster_id,
        )


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: int
    name: str
    goal: str | None
    notes: str | None
    """The user's notes, and summaries of earlier questions the assistant wrote when asked:
    prior choices and summaries, never evidence."""
    focus: Focus
    conversation: int
    """The conversation under way: a follow-up reads its earlier turns, and only those."""
    archived: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SavedTurn:
    """One question asked in a workspace and what came of it."""

    workspace_id: int
    conversation: int
    asked_at: datetime
    question: str
    mode: Mode
    focus: Focus
    """What the question was asked about when it named nothing."""
    asked_from: str
    """The page it was asked from."""
    answer: Answer | None
    error: str | None = None
    """Why no answer came back."""
    steps: tuple[Step, ...] = ()
    seconds: float = 0.0
    resolved: tuple[NameCandidate, ...] = ()
    """Readings the user chose for names in the question."""
    about: str | None = None
    """What the page was showing, in words, when asked from another page."""
    build_id: int | None = None
    value_model: str | None = None
    turn_id: int | None = None
    """Set once the workspace holds it."""


@dataclass(frozen=True, slots=True)
class Finding:
    """An answer the user bookmarked, kept as a copy."""

    finding_id: int
    workspace_id: int
    turn_id: int | None
    title: str
    note: str | None
    question: str
    answer_text: str | None
    evidence: str | None
    asked_at: datetime
    build_id: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    """A roster the assistant proposed in a workspace, and what the user did with it."""

    workspace_id: int
    proposal: RosterProposal
    status: str
    """``draft`` (waiting), ``saved`` or ``declined``."""
    roster_id: int | None
    turn_id: int | None
    created_at: datetime
    decided_at: datetime | None

    @property
    def fingerprint(self) -> str:
        return self.proposal.fingerprint


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """An experiment proposal the user kept in a workspace (A8): kept for review, never
    applied."""

    experiment_id: int
    workspace_id: int
    proposal: ExperimentProposal
    note: str | None
    """The user's note on it."""
    turn_id: int | None
    created_at: datetime

    @property
    def fingerprint(self) -> str:
        return self.proposal.fingerprint


@dataclass(frozen=True, slots=True)
class Approval:
    """One press of a proposal's save or decline button."""

    fingerprint: str
    action: str
    """``saved``, ``already_saved``, ``refused`` or ``declined``."""
    roster_id: int | None
    detail: str | None
    at: datetime


# --- the codec -------------------------------------------------------------------------------


def turn_payload(turn: SavedTurn) -> str:
    """What the page draws of a turn, as JSON text: the answer, the steps, the readings."""
    return json.dumps(
        {
            "answer": None if turn.answer is None else answer_to_dict(turn.answer),
            "steps": [_step(step) for step in turn.steps],
            "resolved": [item.model_dump(mode="json") for item in turn.resolved],
        },
        default=_plain,
        ensure_ascii=False,
    )


def payload_parts(
    payload: str,
) -> tuple[Answer | None, tuple[Step, ...], tuple[NameCandidate, ...]]:
    data = json.loads(payload)
    answer = None if data.get("answer") is None else answer_from_dict(data["answer"])
    steps = tuple(_step_from(item) for item in data.get("steps", ()))
    resolved = tuple(NameCandidate.model_validate(item) for item in data.get("resolved", ()))
    return answer, steps, resolved


def answer_to_dict(answer: Answer) -> dict[str, Any]:
    return {
        "question": answer.question,
        "text": answer.text,
        "outcome": answer.outcome.value,
        "results": [_result(result) for result in answer.results],
        "options": [item.model_dump(mode="json") for item in answer.options],
        "removed": list(answer.removed),
        "warnings": list(answer.warnings),
        "steps": [_step(step) for step in answer.steps],
        "model": answer.model,
        "policy": answer.policy,
        "seconds": answer.seconds,
    }


def answer_from_dict(data: dict[str, Any]) -> Answer:
    return Answer(
        question=data["question"],
        text=data["text"],
        outcome=Outcome(data["outcome"]),
        results=tuple(_result_from(item) for item in data.get("results", ())),
        options=tuple(NameCandidate.model_validate(item) for item in data.get("options", ())),
        removed=tuple(data.get("removed", ())),
        warnings=tuple(data.get("warnings", ())),
        steps=tuple(_step_from(item) for item in data.get("steps", ())),
        model=data.get("model"),
        policy=data.get("policy"),
        seconds=float(data.get("seconds") or 0.0),
    )


def _result(result: ToolResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "tool": result.tool,
        "arguments": result.arguments,
        "status": result.status.value,
        "title": result.title,
        "text": result.text,
        "table": frame_to_dict(result.table),
        "evidence": [_evidence(item) for item in result.evidence],
        "warnings": list(result.warnings),
        "kinds": list(result.kinds),
        "limits": list(result.limits),
        "charts": [_chart(chart) for chart in result.charts],
        "proposals": [proposal.model_dump(mode="json") for proposal in result.proposals],
        "experiments": [proposal.model_dump(mode="json") for proposal in result.experiments],
    }


def _result_from(data: dict[str, Any]) -> ToolResult:
    return ToolResult(
        result_id=data["result_id"],
        tool=data["tool"],
        arguments=dict(data.get("arguments") or {}),
        status=ResultStatus(data["status"]),
        title=data["title"],
        text=data["text"],
        table=frame_from_dict(data.get("table")),
        evidence=tuple(_evidence_from(item) for item in data.get("evidence", ())),
        warnings=tuple(data.get("warnings", ())),
        kinds=tuple(data.get("kinds", ())),
        limits=tuple(data.get("limits", ())),
        charts=tuple(_chart_from(item) for item in data.get("charts", ())),
        proposals=tuple(RosterProposal.model_validate(item) for item in data.get("proposals", ())),
        experiments=tuple(
            ExperimentProposal.model_validate(item) for item in data.get("experiments", ())
        ),
    )


def _evidence(item: Evidence) -> dict[str, Any]:
    return {
        "kind": item.kind.value,
        "label": item.label,
        "location": item.location,
        "retrieved_at": _moment(item.retrieved_at),
        "published_at": _moment(item.published_at),
        "effective_at": None if item.effective_at is None else item.effective_at.isoformat(),
        "build_id": item.build_id,
        "version": item.version,
    }


def _evidence_from(data: dict[str, Any]) -> Evidence:
    effective = data.get("effective_at")
    return Evidence(
        kind=EvidenceKind(data["kind"]),
        label=data["label"],
        location=data.get("location"),
        retrieved_at=_moment_from(data.get("retrieved_at")),
        published_at=_moment_from(data.get("published_at")),
        effective_at=None if effective is None else date.fromisoformat(effective),
        build_id=data.get("build_id"),
        version=data.get("version"),
    )


def _chart(chart: Chart) -> dict[str, Any]:
    return {
        "kind": chart.kind,
        "title": chart.title,
        "frame": frame_to_dict(chart.frame),
        "x": chart.x,
        "y": chart.y,
        "text": chart.text,
        "y_title": chart.y_title,
        "low": chart.low,
        "high": chart.high,
        "who": chart.who,
        "metric": chart.metric,
        "tickformat": chart.tickformat,
        "y_range": None if chart.y_range is None else list(chart.y_range),
        "reference": chart.reference,
        "reference_label": chart.reference_label,
        "estimate": chart.estimate,
    }


def _chart_from(data: dict[str, Any]) -> Chart:
    span = data.get("y_range")
    frame = frame_from_dict(data["frame"])
    assert frame is not None
    return Chart(
        kind=data["kind"],
        title=data["title"],
        frame=frame,
        x=data["x"],
        y=data["y"],
        text=data["text"],
        y_title=data.get("y_title", ""),
        low=data.get("low"),
        high=data.get("high"),
        who=data.get("who"),
        metric=data.get("metric"),
        tickformat=data.get("tickformat", ""),
        y_range=None if span is None else (float(span[0]), float(span[1])),
        reference=data.get("reference"),
        reference_label=data.get("reference_label", ""),
        estimate=bool(data.get("estimate", False)),
    )


def _step(step: Step) -> dict[str, Any]:
    return {"kind": step.kind, "detail": step.detail, "seconds": step.seconds}


def _step_from(data: dict[str, Any]) -> Step:
    return Step(kind=data["kind"], detail=data["detail"], seconds=float(data.get("seconds") or 0))


def frame_to_dict(frame: pd.DataFrame | None) -> dict[str, Any] | None:
    """A frame as plain JSON values. A named index becomes a column; a plain one is
    dropped, as the page never shows it."""
    if frame is None:
        return None
    named = any(name is not None for name in frame.index.names)
    data = frame.reset_index() if named else frame.reset_index(drop=True)
    return {
        "columns": [str(column) for column in data.columns],
        "data": [[_plain(value) for value in row] for row in data.itertuples(index=False)],
    }


def frame_from_dict(data: dict[str, Any] | None) -> pd.DataFrame | None:
    if data is None:
        return None
    return pd.DataFrame(data["data"], columns=data["columns"])


def _plain(value: object) -> object:
    """A value JSON can hold: NumPy's as Python's, a moment as ISO text, missing as null."""
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and value != value:  # NaN
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _moment(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _moment_from(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)
