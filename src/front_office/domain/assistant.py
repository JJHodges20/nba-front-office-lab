"""The AI research assistant's vocabulary: its settings, what it is told, what it reads.

Decision 0018. The assistant's language model runs on this machine; the settings refuse an
address that is not the loopback one and a model whose name says it runs in a cloud. The
context is what the workbench hands the assistant with a question: the sidebar's filters,
the names a deterministic pre-pass resolved, and sources the user supplied. Every figure
in it is the lab's or the user's, never the model's.
"""

from __future__ import annotations

import ipaddress
from datetime import date
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

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
