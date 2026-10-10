"""The frozen evaluation cases, read and scored (docs/AI_EVALUATION.md).

``tests/assistant/fixtures/cases.yaml`` is read into typed cases; a case becomes the
context and conversation the model sees. Two things are scored, both by plain code:

- a model's **first move** (A1): the right tool or rightly none, the expected argument
  values, arguments that validate, nothing forbidden, nothing cut off;
- a whole **answer** (from A2): the outcome the case expects, the first call, nothing
  forbidden in what was called or said, the evidence the case asks to be cited, and how
  many of the case's frozen figures the answer states.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from front_office.assistant.checker import Figure, figures, supports
from front_office.assistant.routing import Call, FirstMove, check
from front_office.assistant.tools import BY_NAME, REGISTRY
from front_office.config.settings import read_yaml
from front_office.domain.assistant import (
    Answer,
    Context,
    EvidenceKind,
    Message,
    Mode,
    NameCandidate,
    Source,
)

Outcome = Literal["supported", "qualified", "insufficient", "clarify", "refuse"]
NONE = "none"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolTurn(_Strict):
    name: str
    content: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Turn(_Strict):
    user: str | None = None
    assistant: str | None = None
    tool: ToolTurn | None = None

    @model_validator(mode="after")
    def _one_speaker(self) -> Turn:
        if sum(value is not None for value in (self.user, self.assistant, self.tool)) != 1:
            raise ValueError("a turn is a user's, the assistant's or a tool's: exactly one")
        return self

    def message(self) -> Message:
        if self.user is not None:
            return Message(role="user", content=self.user)
        if self.assistant is not None:
            return Message(role="assistant", content=self.assistant)
        assert self.tool is not None
        return Message(
            role="tool",
            content=self.tool.content,
            tool_name=self.tool.name,
            arguments=dict(self.tool.arguments),
        )


class ExpectedCall(_Strict):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class Expect(_Strict):
    outcome: Outcome
    first_call: list[Literal["none"] | ExpectedCall] = Field(min_length=1)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    cite: list[str] = Field(default_factory=list)
    forbid: list[str] = Field(default_factory=list)
    forbid_calls: list[str] = Field(default_factory=list)
    forbid_args: list[str] = Field(default_factory=list)

    @property
    def none_is_right(self) -> bool:
        return NONE in self.first_call

    @property
    def calls(self) -> list[ExpectedCall]:
        return [option for option in self.first_call if isinstance(option, ExpectedCall)]


class CaseContext(_Strict):
    season: str
    season_type: str = "regular"
    team_id: int | None = None
    player_id: int | None = None
    resolved: list[NameCandidate] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class EvalCase(_Strict):
    id: str
    category: str
    mode: Mode
    database: str
    context: CaseContext
    turns: list[Turn] = Field(min_length=1)
    expect: Expect


class CaseFile(_Strict):
    version: int
    today: date
    calendar: str
    databases: dict[str, str]
    cases: list[EvalCase]

    @model_validator(mode="after")
    def _known_databases(self) -> CaseFile:
        unknown = sorted({case.database for case in self.cases} - set(self.databases))
        if unknown:
            raise ValueError(f"cases name databases the file does not describe: {unknown}")
        return self


def load_cases(path: Path) -> CaseFile:
    return CaseFile.model_validate(read_yaml(path))


def context_for(cases: CaseFile, case: EvalCase) -> Context:
    """What the workbench would hand the assistant with this case's question."""
    return Context(
        today=cases.today,
        calendar=cases.calendar,
        data=cases.databases[case.database],
        season=case.context.season,
        season_type=case.context.season_type,
        team_id=case.context.team_id,
        player_id=case.context.player_id,
        resolved=tuple(case.context.resolved),
        sources=tuple(case.context.sources),
        mode=case.mode,
    )


def messages_for(case: EvalCase) -> list[Message]:
    return [turn.message() for turn in case.turns]


@dataclass(frozen=True, slots=True)
class Score:
    """How one first move measured up to its case."""

    case_id: str
    category: str
    none_is_right: bool
    chosen: str | None
    """The tool of the first call, or ``None`` when the model called nothing."""
    choice_ok: bool
    """An acceptable tool, or rightly none."""
    args_ok: bool | None
    """The expected argument values are there (``None`` when no call was chosen or matched)."""
    valid: bool | None
    """The final first call validates (``None`` without a call)."""
    valid_first_try: bool | None
    repaired: bool
    forbidden: tuple[str, ...]
    cut_off: bool

    @property
    def passed(self) -> bool:
        return passes(self.choice_ok, self.args_ok, self.valid, self.forbidden, self.cut_off)


def passes(
    choice_ok: bool,
    args_ok: bool | None,
    valid: bool | None,
    forbidden: tuple[str, ...] | list[str],
    cut_off: bool,
) -> bool:
    """A first move passes when every part of it does: the right tool or rightly none, the
    expected values, arguments that validate, nothing forbidden, nothing cut off."""
    return (
        choice_ok and args_ok is not False and valid is not False and not forbidden and not cut_off
    )


def judge_choice(
    case: EvalCase, tool: str | None, arguments: Mapping[str, Any] | None
) -> tuple[bool, bool | None]:
    """``(choice_ok, args_ok)`` for a first call - or for none, when ``tool`` is ``None``.

    Kept apart from :func:`score` so that a recorded move can be judged again against a
    case file that has changed since, without asking the model again.
    """
    if tool is None:
        return case.expect.none_is_right, None
    options = [option for option in case.expect.calls if option.tool == tool]
    if not options:
        return False, None
    filled = _filled(Call(tool, arguments, None))
    return True, any(_matches(option.args, filled) for option in options)


def score(case: EvalCase, move: FirstMove) -> Score:
    expect = case.expect
    first = move.first
    chosen = None if first is None else first.tool
    choice_ok, args_ok = judge_choice(case, chosen, None if first is None else first.arguments)
    opening = move.replies[0].tool_calls
    first_try_valid = check(opening[0]).valid if opening else None
    return Score(
        case_id=case.id,
        category=case.category,
        none_is_right=expect.none_is_right,
        chosen=chosen,
        choice_ok=choice_ok,
        args_ok=args_ok,
        valid=None if first is None else first.valid,
        valid_first_try=first_try_valid,
        repaired=move.repaired,
        forbidden=_forbidden(expect, move),
        cut_off=move.cut_off,
    )


def _filled(call: Call) -> Mapping[str, Any]:
    """The call's arguments with the tool's defaults filled in, when they validate."""
    arguments = dict(call.arguments or {})
    spec = BY_NAME.get(call.tool)
    if spec is None:
        return arguments
    try:
        return spec.args.model_validate(arguments).model_dump(mode="json")
    except ValidationError:
        return arguments


def _matches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    return all(key in actual and _same(value, actual[key]) for key, value in expected.items())


def _same(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list):
        return isinstance(actual, list | tuple) and sorted(map(_plain, expected)) == sorted(
            map(_plain, actual)
        )
    return _plain(expected) == _plain(actual)


def _plain(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return str(value).lower()
    if isinstance(value, int | float):
        return repr(float(value))
    return str(value).strip().lower()


def _forbidden(expect: Expect, move: FirstMove) -> tuple[str, ...]:
    found = []
    for call in move.all_calls:
        if call.tool in expect.forbid_calls:
            found.append(f"call:{call.tool}")
        written = json.dumps(call.arguments or {}).lower()
        found.extend(f"argument:{text}" for text in expect.forbid_args if text.lower() in written)
    if move.first is None:
        said = move.text.lower()
        found.extend(f"text:{phrase}" for phrase in expect.forbid if phrase.lower() in said)
    return tuple(dict.fromkeys(found))


# --- whole answers (A2) ------------------------------------------------------------------

OUTCOME_NAMES = {"refuse": "declined"}
"""A case's expected outcome as the assistant names it."""


def built_tools(milestone: str) -> frozenset[str]:
    return frozenset(spec.name for spec in REGISTRY if spec.milestone <= milestone)


def runnable(case: EvalCase, built: frozenset[str]) -> bool:
    """Whether every tool the case accepts as a first call is built: only then can its
    answer be judged whole."""
    return all(option.tool in built for option in case.expect.calls)


def question_of(case: EvalCase) -> tuple[list[Message], str, list[ToolTurn]]:
    """The turns before the question, the question, and the tool turns after it - results
    the case already holds, which an end-to-end run has the tools return instead."""
    last = max(index for index, turn in enumerate(case.turns) if turn.user is not None)
    question = case.turns[last].user
    assert question is not None
    after = [turn.tool for turn in case.turns[last + 1 :] if turn.tool is not None]
    return [turn.message() for turn in case.turns[:last]], question, after


@dataclass(frozen=True, slots=True)
class AnswerScore:
    """How one whole answer measured up to its case."""

    case_id: str
    category: str
    expected: str
    outcome: str
    calls: tuple[str, ...]
    """The tools called, in order."""
    replayed: bool
    """Whether the calls began with those the case already holds (true when it holds none)."""
    first_ok: bool
    """The first call after those is acceptable, or rightly none."""
    args_ok: bool | None
    forbidden: tuple[str, ...]
    missing_cites: tuple[str, ...]
    facts_stated: int
    facts: int
    removed: int
    """Figures the checker took out."""

    @property
    def outcome_ok(self) -> bool:
        return self.outcome == OUTCOME_NAMES.get(self.expected, self.expected)

    @property
    def passed(self) -> bool:
        return (
            self.outcome_ok
            and self.replayed
            and self.first_ok
            and self.args_ok is not False
            and not self.forbidden
            and not self.missing_cites
        )


def score_answer(case: EvalCase, answer: Answer) -> AnswerScore:
    expect = case.expect
    _, _, held = question_of(case)
    made = [(result.tool, result.arguments) for result in answer.results]
    replayed = len(made) >= len(held) and all(
        _replays(turn, tool, arguments) for (tool, arguments), turn in zip(made, held, strict=False)
    )
    following = made[len(held)] if len(made) > len(held) else None
    choice_ok, args_ok = judge_choice(
        case,
        None if following is None else following[0],
        None if following is None else following[1],
    )
    forbidden = [f"call:{tool}" for tool, _ in made if tool in expect.forbid_calls]
    for _, arguments in made:
        written = json.dumps(arguments or {}).lower()
        forbidden += [f"argument:{text}" for text in expect.forbid_args if text.lower() in written]
    said = answer.text.lower()
    forbidden += [f"text:{phrase}" for phrase in expect.forbid if phrase.lower() in said]
    stated = [fact for fact in expect.facts if "value" in fact]
    return AnswerScore(
        case_id=case.id,
        category=case.category,
        expected=expect.outcome,
        outcome=answer.outcome.value,
        calls=tuple(tool for tool, _ in made),
        replayed=replayed,
        first_ok=choice_ok,
        args_ok=args_ok,
        forbidden=tuple(dict.fromkeys(forbidden)),
        missing_cites=tuple(need for need in expect.cite if not _cited(need, answer)),
        facts_stated=facts_stated(case, answer.text),
        facts=len(stated),
        removed=len(answer.removed),
    )


def _cited(need: str, answer: Answer) -> bool:
    """Whether the answer carries what the case asks it to cite: in its evidence, or for an
    interval in its words."""
    evidence = answer.evidence
    if need == "build":
        return any(item.kind is EvidenceKind.LAB and item.build_id is not None for item in evidence)
    if need == "nba":
        return any("NBA.com" in item.label for item in evidence)
    if need == "as_of":
        return any(item.kind is EvidenceKind.CONTRACTS and item.effective_at for item in evidence)
    if need == "source":
        return any(
            item.kind in (EvidenceKind.CURRENT, EvidenceKind.WEB) and item.location
            for item in evidence
        )
    if need == "model":
        return any(item.kind is EvidenceKind.MODEL for item in evidence)
    if need == "interval":
        return "interval" in answer.text.lower()
    raise ValueError(f"no citation called {need!r}")


def _replays(turn: ToolTurn, tool: str, arguments: Mapping[str, Any] | None) -> bool:
    """Whether a call is the one a held result came from: the same tool, and the same ids.
    A search's words are the model's own and need not be the case's."""
    ids = {key: value for key, value in turn.arguments.items() if key.endswith(("_id", "_ids"))}
    return tool == turn.name and _matches(ids, arguments or {})


def _stated(value: Any, text: str) -> bool:
    """Whether the answer states a frozen figure - at the precision it writes it - or a
    frozen name (``first_apron`` is written "first apron")."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value).replace("_", " ").lower() in text.lower()
    # A frozen figure is a value, which an answer may write as a number or as a place (a
    # rank of 4 is "4th"); a written zero holds no figure but zero: "0%" is not 27.8%.
    frozen = [Figure(str(value), float(value), 0.0, False, False, place) for place in (False, True)]
    return any(
        supports(given, written) and (written.value != 0 or float(value) == 0)
        for given in frozen
        for written in figures(text)
    )


def facts_stated(case: EvalCase, text: str) -> int:
    """How many of the case's frozen figures and names the answer states."""
    return sum(_stated(fact["value"], text) for fact in case.expect.facts if "value" in fact)
