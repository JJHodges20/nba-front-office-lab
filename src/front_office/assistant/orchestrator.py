"""The assistant answering a question: names, tools, a checked answer (decision 0018).

1. Names in the question are resolved by code (``names``); an ambiguous one is asked about
   and the model is not called at all.
2. The model calls tools - only those this build can run - within its mode's limits: the
   number of calls, the time, and the room left in its context; on the web, the searches
   and pages its mode allows. A link pasted into the question becomes a source it may read
   by id. Each call is checked and run by the executor; each result goes back to the model
   quoted as data.
3. Its answer is checked (``checker``): a figure that nothing the model was given holds is
   sent back once to be rewritten, then cut out with its sentence.
4. The outcome says what kind of answer it is, and the answer carries every result, with
   the evidence behind each.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from typing import Any

from front_office.assistant import checker
from front_office.assistant.executor import Executor
from front_office.assistant.names import clarification, find_mentions
from front_office.assistant.policy import POLICY_VERSION, render_context
from front_office.assistant.routing import check, conversation, quoted
from front_office.assistant.toolbox import Toolbox
from front_office.assistant.tools import tool_schemas
from front_office.assistant.web_tools import links_in
from front_office.domain.assistant import (
    Answer,
    AssistantSettings,
    Context,
    Message,
    Mode,
    NameCandidate,
    Outcome,
    Step,
    ToolResult,
)
from front_office.providers.ollama import ChatReply, OllamaProvider
from front_office.services import Lab

LIMITS: dict[Mode, tuple[int, float]] = {Mode.QUICK: (3, 90.0), Mode.DEEP: (12, 300.0)}
"""Tool calls and seconds for one answer, by mode (docs/AI_ASSISTANT_SPEC.md)."""
CONTEXT_SHARE = 0.75
"""Once a request's prompt fills this share of the context, no more tools are offered."""
NO_MORE_TOOLS = "No more tools can be called for this question. Answer now from the results above."
DECLINING = re.compile(
    r"\b(?:can(?:not|'t|’t)|unable|not able|won(?:'t|’t)|will not|do(?:n't|’t| not) have access|"
    r"not (?:allowed|permitted|supported)|outside what"
    r"|do(?:es)?(?:n't|’t| not) (?:support|allow|permit|fetch|run|open|save|delete|access))\b",
    re.IGNORECASE,
)
"""Saying no: with nothing called, the answer is a refusal; beside results, part of the
question went unanswered."""
MISSING = re.compile(
    r"\bnot (?:directly )?(?:provided|available|included|given|held|recorded)\b"
    r"|\b(?:does|did|do)(?:n't|’t| not) (?:include|provide|contain|cover|track)\b"
    r"|\b(?:no|none of the) (?:data|information|figures?|results?) (?:on|for|about|in|shows?)\b",
    re.IGNORECASE,
)
"""Saying what the results lack: beside results, the answer is at most qualified."""
PROMISE = re.compile(
    r"\b(?:let me|i(?:'ll|’ll| will| am going to|'m going to|’m going to))\s+"
    r"(?:now\s+)?(?:check|look|find|fetch|get|search|pull|see|retrieve|call)\b",
    re.IGNORECASE,
)
"""A reply that says it will look something up: a small model sometimes stops there."""
GO_AHEAD = "Go ahead: call the tool now, then answer from its result."
NO_SUCH_RESULT = (
    "That cites a result no tool has returned in this answer. Call the tool that gives it, "
    "then answer from its result."
)

OnStep = Callable[[Step], None]


class Assistant:
    """One local model answering from the lab's tools."""

    def __init__(
        self,
        lab: Lab,
        settings: AssistantSettings,
        provider: OllamaProvider,
        *,
        model: str | None = None,
        toolbox: Toolbox | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lab = lab
        self._settings = settings
        self._provider = provider
        self.model = model or settings.default_model
        self._toolbox = toolbox or Toolbox.for_lab(lab)
        self._clock = clock
        self._can_think: bool | None = None

    def ask(
        self,
        question: str,
        context: Context,
        *,
        history: Sequence[Message] = (),
        on_step: OnStep | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> Answer:
        started = self._clock()
        steps: list[Step] = []

        def record(step: Step) -> None:
            steps.append(step)
            if on_step is not None:
                on_step(step)

        with self._lab.remembering():
            mentions = find_mentions(question, self._lab.entities, season=context.season)
        unclear = next((mention for mention in mentions if mention.ambiguous), None)
        if unclear is not None:
            text = clarification(unclear)
            record(Step("clarify", text))
            return Answer(
                question,
                text,
                Outcome.CLARIFY,
                options=unclear.names(),
                steps=tuple(steps),
                policy=POLICY_VERSION,
                seconds=self._clock() - started,
            )
        known = _merge(context.resolved, *(mention.names() for mention in mentions))
        pasted = links_in(question, context.sources)
        context = context.model_copy(
            update={"resolved": known, "sources": (*context.sources, *pasted)}
        )

        executor = Executor(self._lab, handlers=self._toolbox.handlers(context))
        specs = executor.available()
        by_name = {spec.name: spec for spec in specs}
        tools = tool_schemas(specs)
        mode = self._settings.mode(context.mode)
        calls_left, seconds = LIMITS[context.mode]
        messages = conversation(context, [*history, Message(role="user", content=question)])
        given = [question, render_context(context), *(turn.content for turn in history)]
        results: list[ToolResult] = []
        stopped = False
        full = False
        nudged = False

        with self._lab.remembering():
            while True:
                if should_stop is not None and should_stop():
                    stopped = True
                    record(Step("model", "stopped by the user"))
                    break
                late = self._clock() - started > seconds
                offering = tools if calls_left > 0 and not late and not full else []
                if not offering and results:
                    messages.append({"role": "user", "content": NO_MORE_TOOLS})
                reply = self._chat(messages, offering, mode)
                record(Step("model", _describe(reply), reply.wall_seconds))
                cited = checker.phantoms(reply.content, (r.result_id for r in results))
                if (
                    offering
                    and not reply.tool_calls
                    and not nudged
                    and (PROMISE.search(reply.content) or cited)
                ):
                    # Said it would look something up and stopped, or cited a result no
                    # tool returned (copying an earlier turn): asked once to make the call.
                    nudged = True
                    why = f"cited {', '.join(cited)} without calling a tool" if cited else "said it would call a tool and did not"  # fmt: skip
                    record(Step("repair", why))
                    messages.append({"role": "assistant", "content": reply.content})
                    messages.append(
                        {"role": "user", "content": NO_SUCH_RESULT if cited else GO_AHEAD}
                    )
                    continue
                if not offering or not reply.tool_calls:
                    draft = reply.content
                    break
                messages.append(_assistant_turn(reply))
                for raw in reply.tool_calls:
                    if calls_left <= 0:
                        break
                    calls_left -= 1
                    began = self._clock()
                    result = executor.run(check(raw, by_name))
                    results.append(result)
                    seen = quoted(result.tool, for_model(result))
                    given.append(seen)
                    messages.append({"role": "tool", "tool_name": result.tool, "content": seen})
                    record(
                        Step(
                            "tool",
                            f"{result.result_id} {result.tool}: {result.status.value}",
                            self._clock() - began,
                        )
                    )
                full = bool(
                    reply.prompt_tokens
                    and reply.prompt_tokens > CONTEXT_SHARE * mode.context_tokens
                )

        if stopped:
            return Answer(
                question,
                "Stopped before an answer. The results gathered so far are below.",
                Outcome.QUALIFIED if results else Outcome.INSUFFICIENT,
                results=tuple(results),
                warnings=("Stopped by the user.",),
                steps=tuple(steps),
                model=self.model,
                policy=POLICY_VERSION,
                seconds=self._clock() - started,
            )

        removed: tuple[str, ...] = ()
        reworded: tuple[str, ...] = ()
        uncited: tuple[str, ...] = ()
        resting_on = [result.tool for result in results if result.usable]
        ids = [result.result_id for result in results]
        verdict = checker.check(draft, given)
        phrases = checker.wording(draft, resting_on)
        cited = checker.phantoms(draft, ids)
        if not verdict.ok or phrases or cited:
            problems = [f"unsupported figures: {verdict.listed}"] if not verdict.ok else []
            problems += (
                [f"wording: {', '.join(item.phrase for item in phrases)}"] if phrases else []
            )
            problems += [f"cites what no tool returned: {', '.join(cited)}"] if cited else []
            record(Step("repair", "; ".join(problems)))
            messages.append({"role": "assistant", "content": draft})
            messages.append(
                {"role": "user", "content": checker.repair_note(verdict, phrases, cited)}
            )
            reply = self._chat(messages, [], mode)
            record(Step("model", _describe(reply), reply.wall_seconds))
            first, draft = draft, reply.content
            if checker.CITATION.search(first) and not checker.CITATION.search(draft):
                # Live at A2 a model answered the note instead of the user ("Therefore, they
                # cannot be cited..."): a rewrite that cites nothing is set aside, and the
                # first answer is cut instead.
                draft = first
                record(Step("check", "the rewrite cited nothing; the first answer is cut instead"))
            if not checker.check(draft, given).ok:
                draft, removed = checker.cut(draft, given)
                record(Step("check", f"removed: {', '.join(removed)}"))
            if checker.wording(draft, resting_on):
                draft, reworded = checker.cut_wording(draft, resting_on)
                record(Step("check", f"removed for wording: {', '.join(reworded)}"))
            if checker.phantoms(draft, ids):
                draft, uncited = checker.cut_phantoms(draft, ids)
                record(Step("check", f"removed for citing nothing: {', '.join(uncited)}"))
        warnings = [warning for result in results if result.usable for warning in result.warnings]
        warnings += [limit for result in results if result.usable for limit in result.limits]
        if removed:
            warnings.append(
                f"{len(removed)} figure(s) were taken out because no result supports them: "
                + ", ".join(removed)
            )
        if reworded:
            warnings.append(
                "Sentences the lab's rules do not allow were taken out: " + ", ".join(reworded)
            )
        if uncited:
            warnings.append(
                "Sentences citing results that do not exist were taken out: " + ", ".join(uncited)
            )
        outcome = _outcome(
            results, draft, (*removed, *reworded, *uncited), late=self._clock() - started > seconds
        )
        if not results and outcome is not Outcome.DECLINED:
            warnings.append("No tool result supports this answer.")
        if not draft.strip():
            draft = "Nothing in the lab's results answers this, so no figures are given."
        return Answer(
            question,
            draft.strip(),
            outcome,
            results=tuple(results),
            removed=removed,
            warnings=tuple(dict.fromkeys(warnings)),
            steps=tuple(steps),
            model=self.model,
            policy=POLICY_VERSION,
            seconds=self._clock() - started,
        )

    def _chat(self, messages: list[dict[str, Any]], tools: list, mode: Any) -> ChatReply:
        if self._can_think is None:
            self._can_think = self._provider.details(self.model).can_think
        return self._provider.chat(
            self.model,
            messages,
            tools=tools,
            think=mode.think if self._can_think else None,
            context_tokens=mode.context_tokens,
            max_output_tokens=mode.max_output_tokens,
            temperature=self._settings.temperature,
            keep_alive=self._settings.ollama.keep_alive,
        )


def for_model(result: ToolResult) -> str:
    """A result as the model reads it: its id, what it is, the rows, the notes, the source."""
    lines = [f"[{result.result_id}] {result.title} ({result.status.value})", result.text]
    lines += [f"Note: {warning}" for warning in result.warnings]
    lines += [f"Say in the answer: {limit}" for limit in result.limits]
    sources = "; ".join(item.label for item in result.evidence)
    if sources:
        lines.append(f"Source: {sources}")
    return "\n".join(lines)


def _merge(*groups: Sequence[NameCandidate]) -> tuple[NameCandidate, ...]:
    seen: dict[tuple, NameCandidate] = {}
    for group in groups:
        for name in group:
            seen.setdefault((name.kind, name.id), name)
    return tuple(seen.values())


def _assistant_turn(reply: ChatReply) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": reply.content,
        "tool_calls": [
            {
                "type": "function",
                "function": {"name": call.name, "arguments": dict(call.arguments or {})},
            }
            for call in reply.tool_calls
        ],
    }


def _describe(reply: ChatReply) -> str:
    calls = ", ".join(call.name for call in reply.tool_calls)
    return f"asked for {calls}" if calls else "answered"


def _outcome(
    results: Sequence[ToolResult], draft: str, removed: tuple[str, ...], *, late: bool
) -> Outcome:
    """What kind of answer it is, from what it rests on and what it says.

    Nothing called: a refusal, or nothing to answer from. Results, but none usable: nothing
    to answer from. An answer that says it cannot and states no figure: nothing to answer
    from either, whatever was read. Otherwise qualified when anything is missing, cut,
    late or limited - a result that holds nothing new, a refusal of part of the question -
    and supported when nothing is.
    """
    usable = [result for result in results if result.usable]
    if not results:
        return Outcome.DECLINED if DECLINING.search(draft) else Outcome.INSUFFICIENT
    if not usable:
        return Outcome.INSUFFICIENT
    declines = DECLINING.search(draft) is not None or MISSING.search(draft) is not None
    if declines and not checker.figures(draft):
        return Outcome.INSUFFICIENT
    limited = any(result.limits for result in usable)
    if removed or late or len(usable) < len(results) or declines or limited:
        return Outcome.QUALIFIED
    return Outcome.SUPPORTED
