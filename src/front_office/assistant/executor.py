"""Running a checked tool call: its handler, the ids it names, its result.

The executor is where a model's request meets the lab (decision 0018). A call must name a
registered tool with arguments that validate (``routing.check``); every player, team and
saved roster it names must be one the lab holds - the A1 benchmark saw a model invent
``team_id: 1`` - and a tool whose handler is not built yet says so. A handler's failure becomes a result
that says what went wrong, never an exception in the conversation. The text the model reads
is bounded; the rows behind it are kept whole for the page.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from front_office.assistant.lab_tools import Found, lab_evidence
from front_office.assistant.routing import Call
from front_office.assistant.toolbox import LAB_HANDLERS
from front_office.assistant.tools import BY_NAME, REGISTRY, Permission, ToolArgs, ToolSpec
from front_office.domain.assistant import ResultStatus, ToolResult
from front_office.services import Lab, LabNotBuilt

MAX_CHARACTERS = 2400
"""Of one result's text, about 600 tokens: three fit an 8,192-token context beside the
rules and the tools."""
PLAYER_FIELDS = (
    "player_id",
    "player_ids",
    "add_player_ids",
    "remove_player_ids",
    "lock_player_ids",
    "exclude_player_ids",
)
TEAM_FIELDS = ("team_id",)
ROSTER = "roster"
READ = Permission.READ

Handler = Callable[[Lab, Any], Found]


class Executor:
    """Runs one conversation's tool calls, numbering their results ``r1``, ``r2``..."""

    def __init__(
        self,
        lab: Lab,
        *,
        handlers: Mapping[str, Handler] | None = None,
        max_characters: int = MAX_CHARACTERS,
    ) -> None:
        self._lab = lab
        self._handlers = dict(LAB_HANDLERS if handlers is None else handlers)
        self._max = max_characters
        self._count = 0
        self._players: set[int] | None = None
        self._teams: set[int] | None = None

    def available(self, specs: Sequence[ToolSpec] = REGISTRY) -> tuple[ToolSpec, ...]:
        """The tools this build can run; only these are offered to the model."""
        return tuple(spec for spec in specs if spec.name in self._handlers)

    def run(self, call: Call) -> ToolResult:
        self._count += 1
        result_id = f"r{self._count}"
        arguments = dict(call.arguments or {})
        spec = BY_NAME.get(call.tool)
        if spec is None or not call.valid:
            return self._refused(
                result_id, call.tool, arguments, call.error or "not a registered tool"
            )
        handler = self._handlers.get(call.tool)
        if handler is None:
            return ToolResult(
                result_id,
                call.tool,
                arguments,
                ResultStatus.UNAVAILABLE,
                spec.name,
                f"{spec.name} is not built yet (milestone {spec.milestone}); nothing was run.",
            )
        args = spec.args.model_validate(arguments)
        unknown = self._unknown_ids(args)
        if unknown:
            return self._refused(result_id, call.tool, arguments, unknown)
        try:
            found = handler(self._lab, args)
        except LabNotBuilt:
            found = Found(
                ResultStatus.UNAVAILABLE, spec.name, "No data has been built yet: run fol refresh."
            )
        except (LookupError, ValueError, TypeError) as error:
            found = Found(ResultStatus.ERROR, spec.name, f"The tool could not answer: {error}")
        if found.status is ResultStatus.EMPTY and not found.evidence and spec.permission is READ:
            # What the lab does not hold is said of a build, as what it holds is.
            found = replace(found, evidence=(lab_evidence(self._lab, "the lab's holdings"),))
        return ToolResult(
            result_id=result_id,
            tool=call.tool,
            arguments=arguments,
            status=found.status,
            title=found.title,
            text=self._bounded(found.text),
            table=found.table,
            evidence=found.evidence,
            warnings=found.warnings,
            kinds=found.kinds,
            limits=found.limits,
            charts=found.charts,
            proposals=found.proposals,
        )

    def _refused(
        self, result_id: str, tool: str, arguments: dict[str, Any], why: str
    ) -> ToolResult:
        return ToolResult(
            result_id,
            tool,
            arguments,
            ResultStatus.ERROR,
            tool,
            f"Rejected, nothing was run: {why}",
        )

    def _unknown_ids(self, args: ToolArgs) -> str | None:
        """What the call names that the lab does not hold, if anything."""
        players = [
            int(value) for name in PLAYER_FIELDS for value in _as_list(getattr(args, name, None))
        ]
        players += [int(item.player_id) for item in getattr(args, "player_assumptions", ())]
        teams = [
            int(value) for name in TEAM_FIELDS for value in _as_list(getattr(args, name, None))
        ]
        rosters = [int(value) for value in _as_list(getattr(args, "roster_id", None))]
        subject = getattr(args, "subject", None)
        if getattr(args, "subject_id", None) is not None:
            named = int(args.subject_id)  # type: ignore[attr-defined]
            (rosters if subject == ROSTER else teams).append(named)
        if rosters:
            saved = self._lab.rosters.list()
            known = {int(i) for i in saved["roster_id"]}
            strangers = sorted(set(rosters) - known)
            if strangers:
                listed = ", ".join(
                    f"{int(row['roster_id'])} ({row['name']})" for _, row in saved.iterrows()
                )
                return (
                    f"the lab holds no saved roster with id {', '.join(map(str, strangers))}. "
                    + (f"The saved rosters are {listed}." if listed else "No roster is saved.")
                )
        if players:
            if self._players is None:
                self._players = {int(i) for i in self._lab.entities.players().index}
            strangers = sorted(set(players) - self._players)
            if strangers:
                return self._not_held("player", strangers)
        if teams:
            if self._teams is None:
                self._teams = {int(i) for i in self._lab.team_labels().index}
            strangers = sorted(set(teams) - self._teams)
            if strangers:
                return self._not_held("team", strangers)
        return None

    def _not_held(self, kind: str, strangers: Sequence[int]) -> str:
        """Why ids are refused - and, where one is an id of the other kind, where it belongs:
        live at A7 a model gave the Knicks' team id for the player as well, and when told
        only that no player has it, gave up."""
        said = f"the lab holds no {kind} with id {', '.join(map(str, strangers))}."
        if kind == "player":
            other, field = "team", "team_id"
            named = {int(k): f"the {v}" for k, v in self._lab.team_labels()["full_name"].items()}
        else:
            other, field = "player", "player_id"
            named = {int(k): str(v) for k, v in self._lab.entities.players()["full_name"].items()}
        crossed = [
            f"{key} is the id of {named[key]}, a {other}" for key in strangers if key in named
        ]
        if crossed:
            return (
                f"{said} {'; '.join(crossed)}: give it as {field}, and leave the {kind} out "
                "unless the question names one."
            )
        return (
            f"{said} Use an id from the names in the question, or look the name up with "
            "resolve_entities."
        )

    def _bounded(self, text: str) -> str:
        if len(text) <= self._max:
            return text
        cut = text.rfind("\n", 0, self._max)
        return text[: cut if cut > 0 else self._max] + "\n(cut short; the page has the rest)"


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return list(value)
    return [value]
