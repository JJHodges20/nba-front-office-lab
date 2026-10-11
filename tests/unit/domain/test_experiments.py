"""Experiment proposals (A8): the assistant's idea in words, the lab's test in figures."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from front_office.domain.experiments import (
    TESTED_MODELS,
    ExperimentIdea,
    ExperimentPlan,
    ExperimentProposal,
    ExperimentRules,
    Measure,
    Quoted,
)

IDEA = {
    "title": "Rookies by draft place",
    "observation": "The value model knows little of a rookie, and its projections miss them most.",
    "hypothesis": "Where a rookie was drafted says how good they are before they play.",
    "change": "Start a rookie's estimate from the level of players drafted at the same place.",
    "failure_modes": ("Too few rookies each season to tell a difference from nothing.",),
}


def plan() -> ExperimentPlan:
    return ExperimentPlan(
        model="player_value",
        label="Player value model",
        revision=2,
        baseline=(
            Measure(label="Typical miss, minutes as played (RMSE)", value=3.01, text="3.01 points"),
        ),
        tested_on="Each season from 2006-07 to 2025-26 - 600 team-seasons.",
        split="Expanding window.",
        metric="Root mean square error.",
        uncertainty="Resampling whole seasons.",
        acceptance="Clear of zero.",
        leakage=("Nothing from the season predicted.",),
        tried=(
            Quoted(
                path="docs/decisions/0010-player-value.md",
                heading="Tried and left out",
                text="| A better starting level for high draft picks | 3.03 against 3.02 |",
            ),
        ),
        steps=("Fit it again: fol value fit --write.",),
        decision="docs/decisions/0010-player-value.md",
    )


def proposal(**idea: object) -> ExperimentProposal:
    return ExperimentProposal(idea=ExperimentIdea(**{**IDEA, **idea}), plan=plan())


class TestTheIdea:
    @pytest.mark.parametrize("field", ["title", "observation", "hypothesis", "change"])
    def test_it_holds_no_figure(self, field: str) -> None:
        """Every figure in a proposal is the lab's, so that none is made up and cited back."""
        with pytest.raises(ValidationError, match="write it in words, without figures"):
            ExperimentIdea(**{**IDEA, field: "Better by 3 points"})

    def test_nor_does_a_way_it_could_fail(self) -> None:
        with pytest.raises(ValidationError, match="write it in words, without figures"):
            ExperimentIdea(**{**IDEA, "failure_modes": ("It misses by 2 wins more.",)})

    def test_its_text_is_put_on_one_line(self) -> None:
        idea = ExperimentIdea(**{**IDEA, "title": "  Rookies\n by   draft place "})
        assert idea.title == "Rookies by draft place"

    @pytest.mark.parametrize("modes", [(), tuple(f"Way number {n}." for n in "abcdef")])
    def test_one_to_five_ways_it_could_fail(self, modes: tuple[str, ...]) -> None:
        with pytest.raises(ValidationError):
            ExperimentIdea(**{**IDEA, "failure_modes": modes})


class TestTheProposal:
    def test_its_fingerprint_names_everything_in_it(self) -> None:
        assert proposal().fingerprint == proposal().fingerprint
        assert proposal().fingerprint != proposal(title="Rookies by college").fingerprint
        assert re.fullmatch(r"[0-9a-f]{12}", proposal().fingerprint)

    def test_the_document_keeps_the_idea_and_the_test_apart(self) -> None:
        document = proposal().document()
        head, test = document.split("## The test - the lab's")
        _, idea = head.split("## The idea - the assistant's, not tested")
        assert IDEA["hypothesis"] in idea and not re.search(r"\d", idea), "no figure is its"
        assert "| Typical miss, minutes as played (RMSE) | 3.01 points |" in test
        assert "> | A better starting level for high draft picks | 3.03 against 3.02 |" in test
        assert "1. Fit it again: fol value fit --write." in test
        assert "nothing in the lab applies it" in document

    def test_set_inside_another_document_its_headings_go_deeper(self) -> None:
        document = proposal().document(level=3)
        assert document.startswith("### Experiment proposal: Rookies by draft place")
        assert "#### The idea" in document and "#### The test" in document


def test_the_rules_cover_the_tested_models_and_only_those() -> None:
    assert TESTED_MODELS == ("player_value", "postseason", "simulator", "roster_fit")
    rules = {
        "label": "A model",
        "decision": "docs/decisions/x.md",
        "tested": ["How"],
        "tried": ["What"],
        "split": "s",
        "metric": "m",
        "uncertainty": "u",
        "acceptance": "a",
        "leakage": ["l"],
        "steps": ["s"],
    }
    ExperimentRules(version=1, models=dict.fromkeys(TESTED_MODELS, rules))
    with pytest.raises(ValidationError, match="must cover the tested models"):
        ExperimentRules(version=1, models=dict.fromkeys(TESTED_MODELS[:3], rules))
    with pytest.raises(ValidationError, match="must cover the tested models"):
        ExperimentRules(version=1, models=dict.fromkeys((*TESTED_MODELS, "archetypes"), rules))
