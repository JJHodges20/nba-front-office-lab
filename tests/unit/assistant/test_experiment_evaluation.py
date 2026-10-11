"""The experiment-proposal evaluation (A8): its frozen cases, and its scoring on made-up
answers."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.assistant.experiment_evaluation import (
    ExperimentCase,
    from_record,
    load_experiment_cases,
    report,
    score_experiment,
    score_record,
)
from front_office.domain.assistant import Answer, Mode, Outcome, ResultStatus, ToolResult
from front_office.domain.experiments import (
    TESTED_MODELS,
    ExperimentIdea,
    ExperimentPlan,
    ExperimentProposal,
)

IDEA = ExperimentIdea(
    title="Rookies by draft place",
    observation="The value model knows little of a rookie, and its projections miss them most.",
    hypothesis="Where a rookie was drafted says how good they are before they play.",
    change="Start a rookie's estimate from the level of players drafted at the same place.",
    failure_modes=("Too few rookies each season to tell a difference from nothing.",),
)


def proposal(model: str = "player_value") -> ExperimentProposal:
    plan = ExperimentPlan(
        model=model,  # type: ignore[arg-type]
        label="A model",
        split="s",
        metric="m",
        uncertainty="u",
        acceptance="a",
        leakage=("l",),
        steps=("s",),
        decision="docs/decisions/x.md",
    )
    return ExperimentProposal(idea=IDEA, plan=plan)


def answer(text: str, *drafts: ExperimentProposal, removed: tuple[str, ...] = ()) -> Answer:
    result = ToolResult(
        "r1", "propose_experiment", {}, ResultStatus.OK, "A proposal", "text", experiments=drafts
    )
    return Answer("Q", text, Outcome.SUPPORTED, (result,), removed=removed)


def case(drafts: str = "player_value", *, leaks: bool = False) -> ExperimentCase:
    return ExperimentCase(
        id="X99", mode=Mode.QUICK, question="Q?", drafts=drafts, names_leakage=leaks
    )  # type: ignore[arg-type]


def test_the_frozen_cases_load_and_ask_both_ways(repo_root: Path) -> None:
    cases = load_experiment_cases(repo_root / "tests/assistant/fixtures/experiment_cases.yaml")
    ids = [item.id for item in cases.cases]
    assert len(ids) == len(set(ids))
    asked = {item.drafts for item in cases.cases}
    assert set(TESTED_MODELS) <= asked and "none" in asked, "every model, and questions not asking"
    assert any(item.names_leakage for item in cases.cases)


def test_a_proposal_drafted_for_the_model_asked_about_passes() -> None:
    score = score_experiment(
        case(), answer("A proposal [r1].", proposal()), untouched=True, seconds=1
    )
    assert score.passed and score.cited and score.leakage is None


@pytest.mark.parametrize(
    ("drafts", "given", "passed"),
    [
        ("postseason", ("player_value",), False),
        ("none", ("player_value",), False),
        ("none", (), True),
        ("player_value", (), False),
    ],
)
def test_drafted_when_and_only_when_asked(
    drafts: str, given: tuple[str, ...], passed: bool
) -> None:
    text = "An answer [r1]." if given else "Their net rating was +8.3."
    drafted = tuple(proposal(model) for model in given)
    score = score_experiment(case(drafts), answer(text, *drafted), untouched=True, seconds=1)
    assert score.drafted_ok is passed and score.passed is passed


@pytest.mark.parametrize(
    "text",
    [
        "I have refitted the model [r1].",
        "I've updated the model with it [r1].",
        "It has been applied [r1].",
    ],
)
def test_a_claim_to_have_changed_a_model_fails(text: str) -> None:
    score = score_experiment(case(), answer(text, proposal()), untouched=True, seconds=1)
    assert score.refit_claimed and not score.passed


def test_a_figure_cut_a_change_made_or_no_citation_fails() -> None:
    cut = score_experiment(
        case(), answer("[r1]", proposal(), removed=("4",)), untouched=True, seconds=1
    )
    changed = score_experiment(case(), answer("[r1]", proposal()), untouched=False, seconds=1)
    uncited = score_experiment(case(), answer("A proposal.", proposal()), untouched=True, seconds=1)
    assert not (cut.passed or changed.passed or uncited.passed)


def test_a_leaking_idea_must_be_called_one() -> None:
    silent = answer("Here it is [r1].", proposal())
    named = answer("Here it is [r1], but next season's minutes would leak the future.", proposal())
    leaks = case(leaks=True)
    assert not score_experiment(leaks, silent, untouched=True, seconds=1).passed
    assert score_experiment(leaks, named, untouched=True, seconds=1).passed


def test_the_report_lists_each_idea_in_the_assistant_s_words() -> None:
    score = score_experiment(
        case(), answer("A proposal [r1].", proposal()), untouched=True, seconds=2
    )
    record = score_record(score)
    assert from_record(record) == score
    text = report(
        {
            "started": "2026-10-11T05:00:00",
            "finished": "2026-10-11T05:10:00",
            "model": "qwen3:8b",
            "milestone": "A8",
            "policy": "2026-10-10.3",
            "frozen_on": "2026-10-11",
            "records": [record],
        }
    )
    assert "| Passed (every part below) | 1/1 |" in text
    assert "**X99: Rookies by draft place** (player_value)" in text
    assert IDEA.hypothesis in text
