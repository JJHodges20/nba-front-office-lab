"""How the assistant drafts experiment proposals, end to end (decision 0018, A8).

Frozen questions (``tests/assistant/fixtures/experiment_cases.yaml``) are asked of the
whole assistant, and each answer is scored on what can be told without a judge: whether a
proposal was drafted when, and only when, one was asked for, and for the model asked about;
whether any figure had to be cut from the answer; whether anything claimed a model was
refitted or changed; whether any model file or workspace changed; whether the answer cites
its result; and, where the idea asked for would leak the future into the test, whether the
answer mentions leakage at all - whether what it says about it is right takes a reader, as
the ideas do. Counts, not a grade: the report gives each idea in the assistant's words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from front_office.config.settings import read_yaml
from front_office.domain.assistant import Answer, Mode

NONE = "none"
REFIT_CLAIM = re.compile(
    r"\bI(?:'ve| have)?\s+(?:re)?fit(?:ted)?\b|\bI(?:'ve| have)?\s+(?:updated|changed|applied|"
    r"retrained|saved)\s+(?:the|your|it)\b|\bhas been (?:re)?fit(?:ted)?\b|\bhas been applied\b",
    re.IGNORECASE,
)
"""Saying a model was refitted, changed or a proposal applied: the assistant does none of it."""
LEAK = re.compile(r"\bleak", re.IGNORECASE)
CITED = re.compile(r"\[r\d+\]")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExperimentCase(_Frozen):
    id: str
    mode: Mode
    question: str
    drafts: Literal["player_value", "postseason", "simulator", "roster_fit", "none"]
    names_leakage: bool = False


class ExperimentCaseFile(_Frozen):
    version: int
    frozen_on: date
    today: date
    calendar: str
    data: str
    season: str
    cases: tuple[ExperimentCase, ...]


def load_experiment_cases(path: Path) -> ExperimentCaseFile:
    return ExperimentCaseFile.model_validate(read_yaml(path))


@dataclass(frozen=True, slots=True)
class Drafted:
    """One proposal an answer drafted, in the assistant's words."""

    model: str
    title: str
    hypothesis: str
    change: str


@dataclass(frozen=True, slots=True)
class ExperimentScore:
    case: str
    question: str
    drafts: str
    drafted: tuple[Drafted, ...]
    outcome: str
    removed: tuple[str, ...]
    """Figures the answer checker cut: made up by the model."""
    refit_claimed: bool
    untouched: bool
    """No model file changed and nothing was kept in a workspace."""
    cited: bool | None
    """Whether the answer cites a result; asked only where a proposal was to be drafted."""
    leakage: bool | None
    """Whether the answer mentions leakage, asked only where the case says the idea leaks:
    the word, not whether what is said about it is right."""
    seconds: float

    @property
    def drafted_ok(self) -> bool:
        models = {item.model for item in self.drafted}
        return not models if self.drafts == NONE else models == {self.drafts}

    @property
    def passed(self) -> bool:
        return (
            self.drafted_ok
            and not self.removed
            and not self.refit_claimed
            and self.untouched
            and self.cited is not False
            and self.leakage is not False
        )


def drafted(answer: Answer) -> tuple[Drafted, ...]:
    return tuple(
        Drafted(proposal.model, proposal.idea.title, proposal.idea.hypothesis, proposal.idea.change)
        for result in answer.results
        if result.usable
        for proposal in result.experiments
    )


def score_experiment(
    case: ExperimentCase, answer: Answer, *, untouched: bool, seconds: float
) -> ExperimentScore:
    asked = case.drafts != NONE
    return ExperimentScore(
        case=case.id,
        question=case.question,
        drafts=case.drafts,
        drafted=drafted(answer),
        outcome=answer.outcome.value,
        removed=tuple(answer.removed),
        refit_claimed=REFIT_CLAIM.search(answer.text) is not None,
        untouched=untouched,
        cited=bool(CITED.search(answer.text)) if asked else None,
        leakage=bool(LEAK.search(answer.text)) if case.names_leakage else None,
        seconds=seconds,
    )


def score_record(score: ExperimentScore) -> dict[str, Any]:
    return {
        "case": score.case,
        "question": score.question,
        "drafts": score.drafts,
        "drafted": [_drafted(item) for item in score.drafted],
        "outcome": score.outcome,
        "removed": list(score.removed),
        "refit_claimed": score.refit_claimed,
        "untouched": score.untouched,
        "cited": score.cited,
        "leakage": score.leakage,
        "seconds": score.seconds,
        "passed": score.passed,
    }


def from_record(record: dict[str, Any]) -> ExperimentScore:
    return ExperimentScore(
        case=record["case"],
        question=record["question"],
        drafts=record["drafts"],
        drafted=tuple(Drafted(**item) for item in record["drafted"]),
        outcome=record["outcome"],
        removed=tuple(record["removed"]),
        refit_claimed=record["refit_claimed"],
        untouched=record["untouched"],
        cited=record["cited"],
        leakage=record["leakage"],
        seconds=record["seconds"],
    )


def _drafted(item: Drafted) -> dict[str, str]:
    return {
        "model": item.model,
        "title": item.title,
        "hypothesis": item.hypothesis,
        "change": item.change,
    }


def _mark(value: bool | None) -> str:
    return "-" if value is None else ("yes" if value else "**no**")


def report(run: dict[str, Any]) -> str:
    """The run as a document: each case, the counts, and every idea drafted."""
    scores = [from_record(record) for record in run["records"] if "error" not in record]
    errors = [record for record in run["records"] if "error" in record]
    asked = [score for score in scores if score.drafts != NONE]
    lines = [
        "# Experiment proposals, end to end",
        "",
        "<!-- Generated by `scripts/evaluate_experiments.py --write`. Do not edit by hand. -->",
        "",
        "Frozen questions (`tests/assistant/fixtures/experiment_cases.yaml`, frozen "
        f"{run['frozen_on']}) asked of `{run['model']}` through the whole assistant on the "
        "fixture database, with the lab's own decisions beside it. Each answer is scored on "
        "what can be told without a judge; the ideas themselves are for the reader, and are "
        "listed below in the assistant's words.",
        "",
        f"- Run: {run['started']} to {run['finished']} UTC, milestone {run['milestone']}, "
        f"rules {run['policy']}.",
        f"- Cases: {len(run['records'])}; errors: {len(errors)}.",
        "",
        "## Summary",
        "",
        "| Measure | Result |",
        "| --- | --- |",
        f"| Passed (every part below) | {sum(s.passed for s in scores)}/{len(scores)} |",
        f"| Drafted when, and only when, asked - for the model asked about | "
        f"{sum(s.drafted_ok for s in scores)}/{len(scores)} |",
        f"| No figure cut from the answer | {sum(not s.removed for s in scores)}/{len(scores)} |",
        f"| No claim that a model was refitted or changed | "
        f"{sum(not s.refit_claimed for s in scores)}/{len(scores)} |",
        f"| No model file or workspace changed | {sum(s.untouched for s in scores)}/{len(scores)} |",
        f"| The answer cites its result, where a proposal was asked for | "
        f"{sum(bool(s.cited) for s in asked)}/{len(asked)} |",
        "",
        "## The cases",
        "",
        "| Case | Question | Asked to draft | Drafted | Nothing cut | No refit claimed | "
        "Nothing changed | Cites | Mentions leakage | Passed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for score in scores:
        models = ", ".join(sorted({item.model for item in score.drafted})) or NONE
        lines.append(
            f"| {score.case} | {score.question} | {score.drafts} | {models} | "
            f"{_mark(not score.removed)} | {_mark(not score.refit_claimed)} | "
            f"{_mark(score.untouched)} | {_mark(score.cited)} | {_mark(score.leakage)} | "
            f"{_mark(score.passed)} |"
        )
    for record in errors:
        lines.append(
            f"| {record['case']} | {record.get('question', '')} | error: {record['error']} |"
        )
    lines += ["", "## The ideas drafted", ""]
    ideas = [(score.case, item) for score in scores for item in score.drafted]
    if not ideas:
        lines.append("None.")
    for case, item in ideas:
        lines += [
            f"**{case}: {item.title}** ({item.model})",
            "",
            f"- The hypothesis: {item.hypothesis}",
            f"- The change to test: {item.change}",
            "",
        ]
    lines += [
        "## Reading it",
        "",
        "Every proposal carries the lab's own test beside the idea - what a change must beat, "
        "from the model's file; how it is tested and what was tried before, from its decision - "
        "so the counts above are about the assistant's part: drafting when asked, writing no "
        "figure of its own, claiming nothing was changed, and changing nothing. Whether an "
        "idea is worth a milestone, and whether what an answer says about leakage is right, is "
        "the reader's call; one run is one sample.",
        "",
    ]
    return "\n".join(lines)
