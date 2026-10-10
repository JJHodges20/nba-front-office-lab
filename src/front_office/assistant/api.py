"""What the workbench may call: the one module of the assistant it imports (decision 0018).

- ``status``: whether the assistant can answer, and if not, what to do; whether web search
  is set up.
- ``start``: a question answered in the background - a :class:`Job` whose steps can be
  read while it runs, which can be stopped, and whose answer arrives when it is done. A
  job opens its own connection to the lab, so the pages go on reading theirs.
- ``history``: the session's earlier turns, as the conversation the next question follows.
- ``refresh_current``: fetch what is due of the current sources, by hand.

Ollama not running, or the model not pulled, is a message on the page, never an error:
the rest of the lab works without the assistant. ``connect`` and ``tools_for`` are the two
places a test puts a scripted model and recorded tools in.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from front_office.assistant.orchestrator import Assistant
from front_office.assistant.toolbox import Toolbox
from front_office.config import ConfigError, load_assistant_settings, load_settings
from front_office.domain.assistant import (
    Answer,
    Context,
    Message,
    Mode,
    NameCandidate,
    Step,
)
from front_office.domain.seasons import Season
from front_office.pipelines.current import refresh_current as fetch_current
from front_office.providers.ollama import (
    ModelNotAvailable,
    NotLocal,
    OllamaError,
    OllamaProvider,
    OllamaUnavailable,
)
from front_office.providers.web import search_key
from front_office.services import Lab

STATUS_TIMEOUT_SECONDS = 5.0
HISTORY_TURNS = 3
"""Earlier exchanges the next question carries: enough to follow "and in 2012-13?", few
enough to leave the context room for results."""


def connect(host: str, timeout: float) -> OllamaProvider:
    """The local model's address as a provider. Tests put a scripted model here."""
    return OllamaProvider(host, timeout=timeout)


def tools_for(lab: Lab) -> Toolbox:
    """The tools a question may use: the lab's, current information and the web. Tests put
    the lab's alone, or a recorded world, here."""
    return Toolbox.for_lab(lab)


class AssistantState(StrEnum):
    READY = "ready"
    OFFLINE = "offline"
    """Ollama is not running or not answering."""
    NO_MODEL = "no_model"
    """Ollama runs, but neither configured model is on this machine and able to use tools."""
    MISCONFIGURED = "misconfigured"


@dataclass(frozen=True, slots=True)
class AssistantStatus:
    state: AssistantState
    message: str
    """What the reader is told: where things stand and what to do."""
    model: str | None = None
    """The model that will answer, when one can."""
    ollama_version: str | None = None
    web_search: bool = False
    """Whether a web search key is set up; its value is never read out."""

    @property
    def is_ready(self) -> bool:
        return self.state is AssistantState.READY


def status(
    project_root: Path | None = None, *, provider: OllamaProvider | None = None
) -> AssistantStatus:
    """Whether the assistant can answer, checked against the running Ollama."""
    try:
        lab_settings = load_settings(project_root)
        settings = load_assistant_settings(lab_settings.config_dir)
    except ConfigError as error:
        return AssistantStatus(AssistantState.MISCONFIGURED, f"The assistant's settings: {error}")
    web = search_key(lab_settings.project_root / ".env") is not None
    host = settings.ollama.host
    try:
        provider = provider or connect(host, STATUS_TIMEOUT_SECONDS)
        version = provider.version()
    except (OllamaUnavailable, NotLocal):
        return AssistantStatus(
            AssistantState.OFFLINE,
            f"Ollama is not running at {host}. Start the Ollama app (or run: ollama serve), "
            "then reload. Everything else in the lab works without it.",
            web_search=web,
        )
    except OllamaError as error:
        return AssistantStatus(
            AssistantState.OFFLINE, f"Ollama answered with an error: {error}", web_search=web
        )

    default, fallback = settings.default_model, settings.fallback_model
    for model in filter(None, (default, fallback)):
        try:
            provider.require_local(model)
            if not provider.details(model).can_call_tools:
                continue
        except (ModelNotAvailable, NotLocal):
            continue
        note = (
            "" if model == default else f" ({default} is not on this machine; using the fallback)"
        )
        return AssistantStatus(
            AssistantState.READY,
            f"Ready: {model} on Ollama {version}{note}.",
            model,
            version,
            web,
        )
    return AssistantStatus(
        AssistantState.NO_MODEL,
        f"Ollama {version} is running, but {default} is not on this machine. "
        f"Run: ollama pull {default}",
        None,
        version,
        web,
    )


# --- asking -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Question:
    """A question as the page asks it: the words, the mode, and the sidebar's filters."""

    text: str
    season: str
    season_type: str = "regular"
    team_id: int | None = None
    player_id: int | None = None
    mode: Mode = Mode.QUICK
    resolved: tuple[NameCandidate, ...] = ()
    """Readings the user has chosen: the answer to a question back."""


@dataclass(frozen=True, slots=True)
class Turn:
    """One question and what came of it, as the page keeps them for the session."""

    question: Question
    answer: Answer | None
    error: str | None = None
    """Why there is no answer: the model stopped answering, the lab is not built..."""
    steps: tuple[Step, ...] = ()
    seconds: float = 0.0


def history(turns: Sequence[Turn]) -> tuple[Message, ...]:
    """The last few answered turns as the conversation the next question follows."""
    messages: list[Message] = []
    for turn in [turn for turn in turns if turn.answer is not None][-HISTORY_TURNS:]:
        assert turn.answer is not None
        messages.append(Message(role="user", content=turn.question.text))
        messages.append(Message(role="assistant", content=turn.answer.text))
    return tuple(messages)


class Job:
    """One question answered in the background: steps readable as they come, a stop, and
    the answer - or why there is none - when it is done."""

    def __init__(
        self,
        question: Question,
        history: Sequence[Message] = (),
        *,
        project_root: Path | None = None,
        today: date | None = None,
    ) -> None:
        self.question = question
        self._history = tuple(history)
        self._root = project_root
        self._today = today or date.today()
        self._steps: list[Step] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.answer: Answer | None = None
        self.error: str | None = None
        self._started = time.monotonic()
        self._finished: float | None = None
        self._thread = threading.Thread(target=self._run, name="assistant-question", daemon=True)
        self._thread.start()

    @property
    def steps(self) -> tuple[Step, ...]:
        with self._lock:
            return tuple(self._steps)

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def seconds(self) -> float:
        return (self._finished or time.monotonic()) - self._started

    def stop(self) -> None:
        """Stop at the next step; what was gathered by then is kept."""
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        self._thread.join(timeout)
        return self.done

    def turn(self) -> Turn:
        """The finished question, as the page keeps it."""
        return Turn(self.question, self.answer, self.error, self.steps, self.seconds)

    def _record(self, step: Step) -> None:
        with self._lock:
            self._steps.append(step)

    def _run(self) -> None:
        try:
            ready = status(self._root)
            if not ready.is_ready:
                self.error = ready.message
                return
            with Lab.open(self._root) as lab:
                lab.require_built()
                settings = load_assistant_settings(lab.settings.config_dir)
                provider = connect(settings.ollama.host, settings.ollama.timeout_seconds)
                assistant = Assistant(
                    lab, settings, provider, model=ready.model, toolbox=tools_for(lab)
                )
                self.answer = assistant.ask(
                    self.question.text,
                    context_for(lab, self.question, self._today),
                    history=self._history,
                    on_step=self._record,
                    should_stop=self._stop.is_set,
                )
        except OllamaError as error:
            self.error = f"The model stopped answering: {error}"
        except Exception as error:  # a failure reaches the page as words, never a dead thread
            self.error = f"The assistant could not answer: {error}"
        finally:
            self._finished = time.monotonic()


def start(
    question: Question,
    turns: Sequence[Turn] = (),
    *,
    project_root: Path | None = None,
    today: date | None = None,
) -> Job:
    """Answer ``question`` in the background, after the session's earlier ``turns``."""
    return Job(question, history(turns), project_root=project_root, today=today)


def context_for(lab: Lab, question: Question, today: date) -> Context:
    """What the model is told about the day and the data, with the page's filters."""
    status = lab.status()
    league_year = Season.league_year_on(today).label
    games = lab.current.games()
    played = games.loc[games["season"] == league_year, "game_id"].nunique()
    calendar = (
        f"{league_year} league year; {played} of its games played, as last fetched."
        if played
        else f"{league_year} league year; none of its games played yet, as last fetched "
        "(the preseason is not in the lab's data)."
    )
    data = f"data build {status.build_id}"
    if status.built_at is not None:
        data += f" of {status.built_at:%Y-%m-%d}"
    if status.team_seasons:
        data += f"; team statistics {status.team_seasons[-1]} to {status.team_seasons[0]}"
    if status.player_seasons:
        data += f"; player statistics {status.player_seasons[-1]} to {status.player_seasons[0]}"
    upcoming = lab.value.status().upcoming if status.is_built else None
    if upcoming is not None:
        # "Next season" is the one the models look ahead to (A4).
        data += f"; the models project {upcoming}"
    data += (
        f"; contract file as of {status.contract_as_of:%Y-%m-%d}"
        if status.has_contracts and status.contract_as_of
        else "; no contract file"
    )
    return Context(
        today=today,
        calendar=calendar,
        data=data + ".",
        season=question.season,
        season_type=question.season_type,
        team_id=question.team_id,
        player_id=question.player_id,
        resolved=question.resolved,
        mode=question.mode,
    )


# --- current information -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Refreshed:
    """What a refresh did with one source: stored, unchanged, none, skipped or failed."""

    source: str
    status: str
    detail: str


def refresh_current(
    project_root: Path | None = None, *, force: bool = False
) -> tuple[Refreshed, ...]:
    """Fetch what is due of the season's games, the transactions and the injury report;
    with ``force``, fetch them all now."""
    report = fetch_current(load_settings(project_root), force=force)
    return tuple(Refreshed(r.source, r.status, r.detail) for r in report.results)
