"""The AI research assistant's vocabulary: its settings, what it is told, what it reads.

Decision 0018. The assistant's language model runs on this machine; the settings refuse an
address that is not the loopback one and a model whose name says it runs in a cloud. The
context is what the workbench hands the assistant with a question: the sidebar's filters,
the names a deterministic pre-pass resolved, and sources the user supplied. Every figure
in it is the lab's or the user's, never the model's.

A tool's result carries the rows it rests on and the evidence for them - where they came
from and how fresh they are - and an answer carries every result it used, so that a page
can show the evidence and a test can check it.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, field_validator

LOCAL_NAMES = frozenset({"localhost"})


def is_loopback_url(url: str) -> bool:
    """Whether ``url`` is an http(s) address on this machine: ``localhost`` or a loopback IP."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises on a malformed port
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or not host:
        return False
    if host.lower() in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_cloud_model(name: str) -> bool:
    """Whether a model name is one of Ollama's cloud models: a ``cloud`` tag, or a name or
    tag ending in ``-cloud`` (``gpt-oss:120b-cloud``, ``gemma4:cloud``)."""
    base, _, tag = name.strip().lower().partition(":")
    return tag == "cloud" or tag.endswith("-cloud") or base.endswith("-cloud")


class Mode(StrEnum):
    """How much work one question may take (docs/AI_ASSISTANT_SPEC.md)."""

    QUICK = "quick"
    """One fact or one comparison: few tool calls, no thinking where the model allows."""
    DEEP = "deep"
    """Several sources or scenarios: more calls, thinking on, progress and a cancel button."""


class _Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OllamaConnection(_Settings):
    host: str = "http://127.0.0.1:11434"
    timeout_seconds: PositiveFloat = 180.0
    keep_alive: str = "10m"
    """How long Ollama keeps a model loaded after a request, in its own notation."""

    @field_validator("host")
    @classmethod
    def _on_this_machine(cls, value: str) -> str:
        if not is_loopback_url(value):
            raise ValueError(
                f"the model must run on this machine; {value!r} is not a loopback address"
            )
        return value.rstrip("/")


class ModeSettings(_Settings):
    context_tokens: int = Field(ge=2048, le=32768)
    """The context length sent with every request; never Ollama's own default."""
    think: bool
    """Whether to ask a model that can think to do so. Ignored by models that cannot."""
    max_output_tokens: int = Field(ge=128, le=8192)


class CurrentSettings(_Settings):
    """How old each kind of current information may get before a question fetches it
    again. Starting values, to be set from how often each source changes in season."""

    games_minutes: int = Field(60, ge=5)
    transactions_minutes: int = Field(180, ge=15)
    injuries_minutes: int = Field(30, ge=15)
    injury_slots: int = Field(4, ge=1, le=12)
    """Quarter hours back to look for the latest injury report."""

    def minutes(self, source: str) -> int:
        return {
            "games": self.games_minutes,
            "transactions": self.transactions_minutes,
            "injuries": self.injuries_minutes,
        }[source]


class AssistantSettings(_Settings):
    """``configs/assistant.yaml``: which local model answers, and within what limits.

    There is deliberately no field for a key or another address: an unknown key is an
    error, and the address must be the loopback one.
    """

    version: int = Field(ge=1)
    ollama: OllamaConnection = OllamaConnection()
    default_model: str = Field(min_length=1)
    fallback_model: str | None = None
    temperature: float = Field(0.0, ge=0.0, le=1.0)
    quick: ModeSettings
    deep: ModeSettings
    current: CurrentSettings = CurrentSettings()

    @field_validator("default_model", "fallback_model")
    @classmethod
    def _local_model(cls, value: str | None) -> str | None:
        if value is not None and is_cloud_model(value):
            raise ValueError(f"{value!r} is a cloud model; the lab uses local models only")
        return value

    def mode(self, mode: Mode) -> ModeSettings:
        return self.quick if mode is Mode.QUICK else self.deep


class NameCandidate(BaseModel):
    """One reading of a name in the question, as the pre-pass resolved it. Two candidates
    for the same text mean the name is ambiguous and the user is asked which."""

    model_config = ConfigDict(frozen=True)

    text: str
    kind: Literal["player", "team", "season"]
    id: int | str
    name: str


class Source(BaseModel):
    """A source the user supplied or a search returned, known to the assistant by its id.
    The model reads a source by id; it never composes an address."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z]{1,2}\d{1,4}$")
    url: str
    title: str = ""


class Context(BaseModel):
    """What the workbench hands the assistant with a question."""

    model_config = ConfigDict(frozen=True)

    today: date
    calendar: str = ""
    """Where the league year stands, in words: preseason, regular season, playoffs."""
    data: str = ""
    """What the lab holds and how fresh it is, in words, from the lab's own status."""
    season: str
    season_type: str = "regular"
    team_id: int | None = None
    player_id: int | None = None
    resolved: tuple[NameCandidate, ...] = ()
    sources: tuple[Source, ...] = ()
    mode: Mode = Mode.QUICK


class Message(BaseModel):
    """One turn of a conversation as the assistant records it."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant", "tool"]
    content: str
    tool_name: str | None = None
    """For a tool turn: the tool that produced the content."""
    arguments: dict | None = None
    """For a tool turn: the arguments the tool was called with."""


class EvidenceKind(StrEnum):
    """Where something an answer rests on came from."""

    LAB = "lab"
    """The lab's database: league statistics as the build holds them."""
    MODEL = "model"
    """A fitted model file, read by the services."""
    CONTRACTS = "contracts"
    """The contract file the user supplied."""
    CURRENT = "current"
    """Current information fetched from the league since the build: games, injuries, moves."""
    WEB = "web"
    """A page, a search result or a link the user pasted: reporting, not the lab's data."""
    DOCS = "docs"
    """The lab's own documentation and research: a file and the heading of a section."""


@dataclass(frozen=True, slots=True)
class Evidence:
    """One source behind a result, with its dates."""

    kind: EvidenceKind
    label: str
    """What it is, in words: "NBA.com statistics, data build 16 of 2026-10-06"."""
    location: str | None = None
    """Where: a table of the lab, a model file, or an address."""
    retrieved_at: datetime | None = None
    """When the lab fetched it (UTC)."""
    published_at: datetime | None = None
    """When the source says it was published, if it says."""
    effective_at: date | None = None
    """When what it reports took effect: a transaction's date, a report's game day."""
    build_id: int | None = None
    version: str | None = None
    """The model revision or the source's own version, where there is one."""


ChartKind = Literal["line", "bars", "intervals", "percentiles", "comparison"]


@dataclass(frozen=True, slots=True)
class Chart:
    """A chart a result is drawn as on the page: the tool chooses it for its own rows, and
    the workbench draws it with its own builders (decision 0018, A3). The model plays no
    part in it, and nothing in it is computed: ``frame`` holds the result's own figures,
    with ``text`` each figure as the lab writes it.

    - ``line``: ``y`` over the ordered ``x`` (a season, a date);
    - ``bars``: ``y`` for each ``x``, either side of zero, in the frame's order;
    - ``intervals``: ``y`` for each ``x`` with the interval from ``low`` to ``high``;
    - ``percentiles``: the percentile ``y`` of each metric ``x``;
    - ``comparison``: the percentile ``y`` of each metric ``x`` for each of ``who``.
    """

    kind: ChartKind
    title: str
    """What is drawn, for the page's caption and the exported file's name."""
    frame: pd.DataFrame
    x: str
    y: str
    text: str
    y_title: str = ""
    low: str | None = None
    high: str | None = None
    who: str | None = None
    metric: str | None = None
    """The catalog key of ``y`` when it is a metric: its axis is written as the metric is."""
    tickformat: str = ""
    """The axis format when ``y`` is no metric: a share, say."""
    y_range: tuple[float, float] | None = None
    """The value axis's span when it has natural ends: a share runs from 0 to 1."""
    reference: float | None = None
    reference_label: str = ""
    estimate: bool = False
    """Whether the figures are the lab's estimates (marked ≈ on the page)."""


class ResultStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    """The tool ran and found nothing: no such season, no such row."""
    UNAVAILABLE = "unavailable"
    """The tool cannot answer now: no contract file, no network, not built yet."""
    ERROR = "error"
    """The call was refused or failed; nothing it says is a fact."""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What one tool call returned: the text the model reads, the rows a page shows."""

    result_id: str
    """``r1``, ``r2``...: how an answer cites it."""
    tool: str
    arguments: dict[str, Any]
    status: ResultStatus
    title: str
    text: str
    """Exactly what the model was given: bounded, formatted as the lab displays."""
    table: pd.DataFrame | None = None
    """Every row the result rests on, for the page; the model may have seen fewer."""
    evidence: tuple[Evidence, ...] = ()
    warnings: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    """The kinds of number in it: measured, derived, estimate, modeled, assumption,
    reported."""
    limits: tuple[str, ...] = ()
    """What the result cannot tell, which an answer resting on it must say: a source
    checked and found holding nothing - no report published, no game played yet - is an
    answer, but a qualified one."""
    charts: tuple[Chart, ...] = ()
    """How the page draws the result, as its tool chose."""

    @property
    def usable(self) -> bool:
        return self.status is ResultStatus.OK


class Outcome(StrEnum):
    """What kind of answer the user got (docs/AI_ASSISTANT_SPEC.md)."""

    SUPPORTED = "supported"
    """Answered from tool results, every figure checked."""
    QUALIFIED = "qualified"
    """Part answered; what is missing, stale, estimated or removed is said."""
    INSUFFICIENT = "insufficient"
    """Nothing to answer from; what is missing is said and nothing is invented."""
    CLARIFY = "clarify"
    """A question back: which player, team or season is meant."""
    DECLINED = "declined"
    """Asked for something the assistant does not do: SQL, files, saving, refitting."""


@dataclass(frozen=True, slots=True)
class Step:
    """One thing the assistant did on the way to an answer."""

    kind: Literal["clarify", "model", "tool", "repair", "check"]
    detail: str
    seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class Answer:
    question: str
    text: str
    outcome: Outcome
    results: tuple[ToolResult, ...] = ()
    options: tuple[NameCandidate, ...] = ()
    """For a question back: the readings to choose from."""
    removed: tuple[str, ...] = ()
    """Figures taken out of the answer because no result supports them."""
    warnings: tuple[str, ...] = ()
    steps: tuple[Step, ...] = ()
    model: str | None = None
    policy: str | None = None
    seconds: float = 0.0

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        """Every source the answer used, once each, in the order first used - including
        what a result that found nothing looked in: "nothing for 1989-90" rests on a build."""
        seen: dict[tuple, Evidence] = {}
        for result in self.results:
            if result.status in (ResultStatus.OK, ResultStatus.EMPTY):
                for item in result.evidence:
                    seen.setdefault((item.kind, item.label, item.location), item)
        return tuple(seen.values())
