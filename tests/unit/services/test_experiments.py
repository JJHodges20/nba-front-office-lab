"""The lab's part of an experiment proposal (A8): figures from the model files, how each
model is tested and what was tried from its decision, the rules from
``configs/experiments.yaml``. Nothing is fitted or changed."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from front_office.config import Settings
from front_office.domain.experiments import TESTED_MODELS, ExperimentIdea
from front_office.services import Lab
from front_office.services.experiments import UnknownModel

IDEA = ExperimentIdea(
    title="Rookies by draft place",
    observation="The value model knows little of a rookie, and its projections miss them most.",
    hypothesis="Where a rookie was drafted says how good they are before they play.",
    change="Start a rookie's estimate from the level of players drafted at the same place.",
    failure_modes=("Too few rookies each season to tell a difference from nothing.",),
)


@pytest.fixture
def documented(settings: Settings, project: Path, repo_root: Path) -> Iterator[Lab]:
    """A project with the shipped model files and the lab's own decisions."""
    shutil.copytree(repo_root / "docs" / "decisions", project / "docs" / "decisions")
    with Lab(settings) as lab:
        yield lab


def files(project: Path) -> dict[str, str]:
    folder = project / "configs" / "models"
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()}


def test_the_value_model_s_plan_is_read_from_its_file_and_decision(documented: Lab) -> None:
    plan = documented.experiments.plan("player_value")
    model = documented.value.model()
    assert model is not None and model.validation.projected is not None
    tested = model.validation
    assert [measure.value for measure in plan.baseline] == [
        tested.net.rmse,
        tested.projected.rmse,
    ]
    assert plan.baseline[0].text == f"{tested.net.rmse:.2f} points"
    assert plan.revision == model.revision and plan.model_file == "configs/models/player_value.json"
    assert tested.first_test_season in plan.tested_on and str(tested.team_seasons) in plan.tested_on
    assert [section.heading.split(" › ")[-1] for section in plan.tried] == ["Tried and left out"]
    assert "playoff minutes" in plan.tried[0].text
    assert any("fol value fit --write" in step for step in plan.steps)


@pytest.mark.parametrize("model", TESTED_MODELS)
def test_every_tested_model_has_a_plan_whole(documented: Lab, model: str) -> None:
    plan = documented.experiments.plan(model)
    assert plan.missing is None and plan.baseline and plan.tested_on
    assert plan.tested and plan.tried and plan.leakage and plan.steps
    assert plan.decision.startswith("docs/decisions/")


def test_the_simulator_s_coverage_is_the_file_s(documented: Lab) -> None:
    model = documented.simulator.model()
    assert model is not None
    plan = documented.experiments.plan("simulator")
    shares = [measure.value for measure in plan.baseline if "interval held" in measure.label]
    assert shares == [item.share for item in model.test.coverage]


def test_the_fit_test_says_whether_its_correction_is_used(documented: Lab) -> None:
    evidence = documented.fit.evidence()
    assert evidence is not None
    (combined,) = [m for m in documented.experiments.plan("roster_fit").baseline if m.interval]
    verdict = "usable" if evidence.combined.is_usable else "not usable: none is applied"
    assert combined.value == evidence.combined.rmse and verdict in str(combined.interval)


def test_a_model_never_fitted_says_so_and_has_nothing_to_beat(
    settings: Settings, project: Path
) -> None:
    (project / "configs" / "models" / "postseason.json").unlink()
    with Lab(settings) as lab:
        plan = lab.experiments.plan("postseason")
    assert plan.baseline == () and plan.revision is None
    assert "fol playoffs fit --write" in str(plan.missing)


def test_without_its_documents_a_plan_quotes_nothing(lab: Lab) -> None:
    """The built test lab has no docs folder: the test and the rules still stand."""
    plan = lab.experiments.plan("roster_fit")
    assert plan.tested == plan.tried == () and plan.baseline and plan.leakage


def test_only_a_tested_model_has_a_plan(documented: Lab) -> None:
    with pytest.raises(UnknownModel, match="the lab tests player_value, postseason"):
        documented.experiments.plan("archetypes")


def test_drafting_fits_and_changes_nothing(documented: Lab, project: Path) -> None:
    before = files(project)
    proposal = documented.experiments.draft("player_value", IDEA)
    assert proposal.idea == IDEA and proposal.plan.model == "player_value"
    assert files(project) == before
