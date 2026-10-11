"""propose_experiment (A8): the model's idea in words, the lab's test from its files, drafted
for the user to review and changing nothing."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from front_office.assistant import tools as t
from front_office.assistant.executor import Executor
from front_office.assistant.routing import check
from front_office.assistant.toolbox import LAB_HANDLERS
from front_office.config import Settings
from front_office.domain.assistant import Answer, EvidenceKind, Outcome, ResultStatus
from front_office.domain.research import answer_from_dict, answer_to_dict
from front_office.providers.ollama import ToolCall
from front_office.services import Lab

IDEA = {
    "model": "player_value",
    "name": "Rookies by draft place",
    "observation": "The value model knows little of a rookie, and its projections miss them most.",
    "hypothesis": "Where a rookie was drafted says how good they are before they play.",
    "change": "Start a rookie's estimate from the level of players drafted at the same place.",
    "failure_modes": ["Too few rookies each season to tell a difference from nothing."],
}


@pytest.fixture
def documented(settings: Settings, project: Path, repo_root: Path) -> Iterator[Lab]:
    shutil.copytree(repo_root / "docs" / "decisions", project / "docs" / "decisions")
    with Lab(settings) as lab:
        yield lab


def draft(lab: Lab, **changes: object):  # type: ignore[no-untyped-def]
    return LAB_HANDLERS["propose_experiment"](lab, t.ProposeExperiment(**{**IDEA, **changes}))


def model_files(lab: Lab) -> dict[str, str]:
    folder = lab.settings.config_dir / "models"
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}


def test_a_proposal_is_drafted_with_the_lab_s_test_beside_the_idea(documented: Lab) -> None:
    found = draft(documented)
    (proposal,) = found.experiments
    model = documented.value.model()
    assert model is not None and found.status is ResultStatus.OK
    assert proposal.idea.title == "Rookies by draft place" and proposal.plan.model == "player_value"
    assert f"{model.validation.net.rmse:.2f} points" in found.text, "what a change must beat"
    assert "Leakage to rule out:" in found.text and "Tried before" in found.text
    assert "no model, setting or data was changed" in found.warnings[0]
    assert (
        found.table is not None
        and found.table["now"].tolist()[0] == f"{model.validation.net.rmse:.2f} points"
    )
    kinds = [item.kind for item in found.evidence]
    assert kinds[0] is EvidenceKind.MODEL and EvidenceKind.DOCS in kinds
    assert "docs/decisions/0010-player-value.md#tried-and-left-out" in [
        item.location for item in found.evidence
    ]


def test_drafting_fits_saves_and_changes_nothing(documented: Lab) -> None:
    before = model_files(documented)
    draft(documented)
    draft(documented, model="postseason")
    assert model_files(documented) == before
    assert documented.workspaces.list(archived=None) == (), "nothing kept: that is the user's click"


@pytest.mark.parametrize("field", ["name", "observation", "hypothesis", "change"])
def test_a_figure_in_the_idea_is_sent_back(field: str) -> None:
    """Every figure in a proposal is the lab's: one the model wrote could be cited back."""
    call = check(ToolCall("propose_experiment", {**IDEA, field: "Better by 3.01 points of rating"}))
    assert not call.valid and "write it in words, without figures" in str(call.error)
    assert 'it holds "3.01"' in str(call.error), "what to take out is quoted"
    assert "Send the same idea again in words." in str(call.error)
    assert "Value error" not in str(call.error), "a model passed that on to the user (A8)"


def test_only_a_tested_model_is_named() -> None:
    call = check(ToolCall("propose_experiment", {**IDEA, "model": "archetypes"}))
    assert not call.valid and "model" in str(call.error)


def test_the_executor_carries_the_proposal_and_the_answer_keeps_it(documented: Lab) -> None:
    result = Executor(documented).run(check(ToolCall("propose_experiment", dict(IDEA))))
    assert result.status is ResultStatus.OK and len(result.experiments) == 1
    answer = Answer("Suggest an experiment", "A proposal [r1].", Outcome.SUPPORTED, (result,))
    again = answer_from_dict(answer_to_dict(answer))
    assert again.results[0].experiments == result.experiments, "a kept answer draws it again"
