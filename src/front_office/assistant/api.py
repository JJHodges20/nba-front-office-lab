"""What the workbench may call: the one module of the assistant it imports (decision 0018).

- ``status``: whether the assistant can answer, and if not, what to do; whether web search
  is set up.
- ``start``: a question answered in the background, in a workspace - a :class:`Job` whose
  steps can be read while it runs, which can be stopped, and whose turn is kept in the
  workspace when it is done. A job opens its own connection to the lab, so the pages go on
  reading theirs; a follow-up reads only its own workspace's conversation (A6).
- ``history``: kept turns as the conversation the next question follows.
- ``save_proposal`` and ``decline_proposal``: a roster the optimizer proposed, saved for the
  Team Builder or declined when the user presses the button under it - never by the model -
  and the press logged in the workspace.
- ``summarize``: the conversation under way, summarized into the workspace's notes by the
  local model, and a new conversation begun.
- ``refresh_current``: fetch what is due of the current sources, by hand.

The workspaces themselves - made, renamed, put away, exported - are the services' to keep
(``Lab.workspaces``), and the workbench reaches them as it reaches every other service.

Ollama not running, or the model not pulled, is a message on the page, never an error:
the rest of the lab works without the assistant. ``connect`` and ``tools_for`` are the two
places a test puts a scripted model and recorded tools in.
"""

from __future__ import annotations

import re
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
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
from front_office.domain.contract_review import ContractPreview
from front_office.domain.proposals import RosterProposal
from front_office.domain.research import RESEARCH_PAGE, Focus, SavedTurn
from front_office.domain.seasons import Season
from front_office.domain.tables.current import SOURCES
from front_office.pipelines.contract_review import ContractReviewError as _Unreadable
from front_office.pipelines.contract_review import preview_contract_file
from front_office.pipelines.current import refresh_current as fetch_current
from front_office.providers.ollama import (
    ModelNotAvailable,
    NotLocal,
    OllamaError,
    OllamaProvider,
    OllamaUnavailable,
)
from front_office.providers.web import search_key
from front_office.services import Lab, ProposalSaved, RosterNotFound

STATUS_TIMEOUT_SECONDS = 5.0


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
    """A question as a page asks it: the words, the mode, and what it is about when it names
    nothing - the sidebar's filters, the workspace's focus, or what the asking page shows."""

    text: str
    season: str
    season_type: str = "regular"
    team_id: int | None = None
    player_id: int | None = None
    roster_id: int | None = None
    mode: Mode = Mode.QUICK
    resolved: tuple[NameCandidate, ...] = ()
    """Readings the user has chosen: the answer to a question back."""
    asked_from: str = RESEARCH_PAGE
    """The page it is asked from."""
    about: str | None = None
    """What that page shows, in words, when it is not the AI Research page."""

    @property
    def focus(self) -> Focus:
        return Focus(
            season=self.season,
            season_type=self.season_type,
            team_id=self.team_id,
            player_id=self.player_id,
            roster_id=self.roster_id,
        )

    @classmethod
    def again(cls, turn: SavedTurn) -> Question:
        """A kept question asked again as it was asked: for an answer from the lab as it is
        now, beside the old one."""
        focus = turn.focus
        return cls(
            text=turn.question,
            season=focus.season or "",
            season_type=focus.season_type or "regular",
            team_id=focus.team_id,
            player_id=focus.player_id,
            roster_id=focus.roster_id,
            mode=turn.mode,
            resolved=turn.resolved,
            asked_from=turn.asked_from,
            about=turn.about,
        )


def history(turns: Sequence[SavedTurn]) -> tuple[Message, ...]:
    """Answered turns as the conversation the next question follows: each question, and the
    answer as it was shown."""
    messages: list[Message] = []
    for turn in turns:
        if turn.answer is None:
            continue
        messages.append(Message(role="user", content=turn.question))
        messages.append(Message(role="assistant", content=turn.answer.text))
    return tuple(messages)


class Job:
    """One question answered in the background, in a workspace: its steps readable as they
    come, a stop, and the turn - kept in the workspace, answered or not - when it is done."""

    def __init__(
        self,
        question: Question,
        workspace_id: int,
        *,
        project_root: Path | None = None,
        today: date | None = None,
    ) -> None:
        self.question = question
        self.workspace_id = int(workspace_id)
        self._root = project_root
        self._today = today or date.today()
        self._steps: list[Step] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.answer: Answer | None = None
        self.error: str | None = None
        self.saved: SavedTurn | None = None
        """The turn as the workspace keeps it, once it is kept."""
        self._asked_at = _utc_now()
        self._conversation: int | None = None
        self._stamp: tuple[int | None, str | None] = (None, None)
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

    def turn(self) -> SavedTurn:
        """The finished question, as its workspace keeps it."""
        if self.saved is not None:
            return self.saved
        return self._unsaved(self._conversation or 0)

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
                workspaces = lab.workspaces
                workspace = workspaces.get(self.workspace_id)
                self._conversation = workspace.conversation
                self._stamp = workspaces.stamp()
                settings = load_assistant_settings(lab.settings.config_dir)
                provider = connect(settings.ollama.host, settings.ollama.timeout_seconds)
                assistant = Assistant(
                    lab, settings, provider, model=ready.model, toolbox=tools_for(lab)
                )
                self.answer = assistant.ask(
                    self.question.text,
                    context_for(lab, self.question, self._today, notes=workspace.notes or ""),
                    history=history(workspaces.history(self.workspace_id)),
                    on_step=self._record,
                    should_stop=self._stop.is_set,
                )
        except OllamaError as error:
            self.error = f"The model stopped answering: {error}"
        except Exception as error:  # a failure reaches the page as words, never a dead thread
            self.error = f"The assistant could not answer: {error}"
        finally:
            self._finished = time.monotonic()
            self._keep()

    def _keep(self) -> None:
        """Keep the turn in its workspace, answered or not. A failure to keep it is said on
        the page, never raised."""
        try:
            with Lab.open(self._root) as lab:
                conversation = self._conversation
                if conversation is None:
                    conversation = lab.workspaces.get(self.workspace_id).conversation
                self.saved = lab.workspaces.record(self._unsaved(conversation))
        except Exception as error:
            note = f"The answer could not be kept in the workspace: {error}"
            self.error = note if self.error is None else f"{self.error} {note}"

    def _unsaved(self, conversation: int) -> SavedTurn:
        build, value = self._stamp
        return SavedTurn(
            workspace_id=self.workspace_id,
            conversation=max(conversation, 1),
            asked_at=self._asked_at,
            question=self.question.text,
            mode=self.question.mode,
            focus=self.question.focus,
            asked_from=self.question.asked_from,
            answer=self.answer,
            error=self.error,
            steps=self.steps,
            seconds=self.seconds,
            resolved=self.question.resolved,
            about=self.question.about,
            build_id=build,
            value_model=value,
        )


def start(
    question: Question,
    workspace_id: int,
    *,
    project_root: Path | None = None,
    today: date | None = None,
) -> Job:
    """Answer ``question`` in the background, in ``workspace_id``: following that
    workspace's conversation under way, and kept in it when done."""
    return Job(question, workspace_id, project_root=project_root, today=today)


def context_for(lab: Lab, question: Question, today: date, *, notes: str = "") -> Context:
    """What the model is told about the day and the data, what the question is about when it
    names nothing, and the workspace's notes - background, never evidence."""
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
    roster_name = None
    if question.roster_id is not None:
        try:
            roster_name = str(lab.rosters.get(question.roster_id)["name"])
        except RosterNotFound:
            roster_name = None
    return Context(
        today=today,
        calendar=calendar,
        data=data + ".",
        season=question.season,
        season_type=question.season_type,
        team_id=question.team_id,
        player_id=question.player_id,
        roster_id=question.roster_id,
        roster_name=roster_name,
        resolved=question.resolved,
        mode=question.mode,
        notes=notes,
    )


# --- roster proposals ----------------------------------------------------------------------


def save_proposal(
    proposal: RosterProposal,
    name: str,
    *,
    workspace_id: int,
    project_root: Path | None = None,
) -> ProposalSaved:
    """Save a roster proposal the user approved, as a Team Builder roster, in one
    transaction, and log the press in the workspace. Nothing is saved when the data, the
    value model, the contract file or a player's salary has changed since the proposal was
    made; a second press finds the roster the first one saved."""
    with Lab.open(project_root) as lab:
        return lab.workspaces.save_proposal(workspace_id, proposal, name)


def decline_proposal(
    fingerprint: str, *, workspace_id: int, project_root: Path | None = None
) -> None:
    """The user's press of *Decline* under a proposal: nothing is saved, and the workspace
    says the proposal was declined."""
    with Lab.open(project_root) as lab:
        lab.workspaces.decline_proposal(workspace_id, fingerprint)


# --- workspace notes -----------------------------------------------------------------------


class ContractReviewError(ValueError):
    """The file could not be read as a contract file; the message says why."""


def review_contract_file(
    content: bytes,
    file_name: str,
    *,
    source_label: str,
    as_of: date,
    project_root: Path | None = None,
) -> ContractPreview:
    """A contract file the user chose, against the one in use - the contract-update review
    (A7). Read exactly as ``fol contracts import`` reads a file, from a copy in a temporary
    folder that is gone when this returns; nothing is stored. The import the preview names
    is the file as the user has it, for them to run once the source is checked."""
    name = re.sub(r"[^\w.\- ]", "_", Path(file_name).name) or "contracts.csv"
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / name
        copy.write_bytes(content)
        try:
            preview = preview_contract_file(
                load_settings(project_root), copy, source_label=source_label, as_of=as_of
            )
        except (_Unreadable, ConfigError) as error:
            raise ContractReviewError(str(error)) from error
    return replace(
        preview,
        command=preview.command.replace(str(copy), file_name),
    )


class SummaryError(ValueError):
    """A summary cannot be written; the message says why, in plain words."""


SUMMARY_RULES = (
    "You write short notes for a basketball research workspace. Summarize the conversation "
    "below in at most six bullet points, in plain words: what the user wanted to know, what "
    "the answers found, and any choice the user made. Add no fact or figure that is not in "
    'the answers. Write "they" for a player.'
)
SUMMARY_ANSWER_CHARACTERS = 900
"""Of each answer, given to the summary: enough for its findings, few enough for a dozen."""


def summarize(
    workspace_id: int, *, project_root: Path | None = None, today: date | None = None
) -> str:
    """Summarize the conversation under way into the workspace's notes with the local model,
    then start a new conversation, which reads the notes instead of the turns. The summary is
    marked as the assistant's and as not evidence; the user can edit or delete it."""
    ready = status(project_root)
    if not ready.is_ready:
        raise SummaryError(ready.message)
    with Lab.open(project_root) as lab:
        service = lab.workspaces
        workspace = service.get(workspace_id)
        turns = [
            turn
            for turn in service.turns(workspace_id, conversation=workspace.conversation)
            if turn.answer is not None
        ]
        if not turns:
            raise SummaryError("There is nothing to summarize yet: no question has been answered.")
        transcript = "\n\n".join(
            f"Question: {turn.question}\nAnswer: {turn.answer.text[:SUMMARY_ANSWER_CHARACTERS]}"  # type: ignore[union-attr]
            for turn in turns
        )
        settings = load_assistant_settings(lab.settings.config_dir)
        provider = connect(settings.ollama.host, settings.ollama.timeout_seconds)
        model = ready.model or settings.default_model
        think = False if provider.details(model).can_think else None
        try:
            reply = provider.chat(
                model,
                [
                    {"role": "system", "content": SUMMARY_RULES},
                    {"role": "user", "content": transcript},
                ],
                context_tokens=settings.deep.context_tokens,
                think=think,
                max_output_tokens=settings.deep.max_output_tokens,
                temperature=settings.temperature,
                keep_alive=settings.ollama.keep_alive,
            )
        except OllamaError as error:
            raise SummaryError(f"The model stopped answering: {error}") from error
        summary = reply.content.strip()
        if not summary:
            raise SummaryError("The model wrote no summary. Nothing was changed.")
        written = (today or date.today()).isoformat()
        heading = (
            f"Summary of earlier questions, {written} (written by the assistant; not evidence):"
        )
        notes = "\n\n".join(part for part in (workspace.notes, f"{heading}\n{summary}") if part)
        service.update(workspace_id, notes=notes)
        service.new_conversation(workspace_id)
    return summary


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
    """Fetch what is due of the season's games, the transactions, the injury report and the
    news feeds; with ``force``, fetch them all now."""
    report = fetch_current(load_settings(project_root), sources=SOURCES, force=force)
    return tuple(Refreshed(r.source, r.status, r.detail) for r in report.results)
