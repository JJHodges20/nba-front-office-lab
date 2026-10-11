"""The rules for experiment proposals (A8), as shipped in ``configs/experiments.yaml``."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import ConfigError, load_experiment_rules, load_sections
from front_office.config.experiments import experiment_rules_path
from front_office.domain.experiments import TESTED_MODELS
from front_office.services.experiments import quoted


def test_the_shipped_rules_cover_every_tested_model(repo_root: Path) -> None:
    rules = load_experiment_rules(repo_root / "configs")
    assert tuple(rules.models) == TESTED_MODELS
    for model in TESTED_MODELS:
        assert rules.of(model).leakage and rules.of(model).steps


def test_every_decision_and_heading_the_rules_name_is_there(repo_root: Path) -> None:
    """A proposal quotes how a model is tested and what was tried by heading; a decision
    rewritten under other headings would leave the proposal without them."""
    sections = load_sections(repo_root)
    for model, rules in load_experiment_rules(repo_root / "configs").models.items():
        assert (repo_root / rules.decision).is_file(), f"{model}: no {rules.decision}"
        for heading in (*rules.tested, *rules.tried):
            assert quoted(sections, rules.decision, [heading]), (
                f"{model}: {rules.decision} has no section {heading!r}"
            )


def test_a_file_without_every_model_is_refused(project: Path) -> None:
    path = experiment_rules_path(project / "configs")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.split("  roster_fit:")[0], encoding="utf-8")
    with pytest.raises(ConfigError, match="must cover the tested models"):
        load_experiment_rules(project / "configs")
