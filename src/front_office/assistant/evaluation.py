"""The frozen evaluation cases, read and scored (docs/AI_EVALUATION.md).

``tests/assistant/fixtures/cases.yaml`` is read into typed cases; a case becomes the
context and conversation the model sees; a model's first move is scored against what the
case accepts. Scoring is plain code: the right tool or rightly none, the expected
argument values, arguments that validate, nothing forbidden, nothing cut off.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from front_office.assistant.routing import Call, FirstMove, check
from front_office.assistant.tools import BY_NAME
from front_office.config.settings import read_yaml
from front_office.domain.assistant import Context, Message, Mode, NameCandidate, Source

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
