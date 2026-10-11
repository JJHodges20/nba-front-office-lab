"""An experiment proposal: a test a future milestone might run on one of the lab's models
(decision 0018, A8).

The assistant drafts one only when the user asks for an experiment or an idea to improve a
model, and only for the four models the lab tests out of sample: player value, the
postseason model, the simulator and the roster fit test. A proposal has two parts, kept
apart on the page and in the document.

The idea is the assistant's, in words: what it noticed, what it supposes, the change to
try and how the change could fail. It holds no figures. Every figure in a proposal is the
lab's, read from the model's file, so that none can be made up and then cited back as a
tool's.

The plan is the lab's: what the change must beat, how the model is tested, how future
information could leak into the test, what was tried before - quoted from the model's
decision - and the steps a future milestone would take. The rules behind it are written
in ``configs/experiments.yaml``; the figures come from the fitted files.

Nothing in the lab applies a proposal. A user may keep one in a workspace; a change to a
model is still a milestone of its own, fitted on request and tested out of sample.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TESTED_MODELS: tuple[str, ...] = ("player_value", "postseason", "simulator", "roster_fit")
"""The models a proposal may aim at: each has an out-of-sample test that can judge a change.
Archetypes are rules a person sets, not fitted, and are left out (the user's decision)."""
ModelKey = Literal["player_value", "postseason", "simulator", "roster_fit"]

IN_WORDS = (
    "write it in words, without figures: every figure in a proposal is the lab's, added from "
    "the model's file"
)
FAILURE_MODES = 5


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


WITH_FIGURE = re.compile(r"\S*\d\S*")


def in_words(value: str) -> str:
    """Text the assistant wrote, on one line, holding no figure. The refusal quotes what it
    found: at A8 a model told only to write in words sent the same "3.01" back six times."""
    text = " ".join(str(value).split())
    found = WITH_FIGURE.search(text)
    if found is not None:
        raise ValueError(
            f'{IN_WORDS} - it holds "{found.group().strip(",.;:()")}". Send the same idea '
            "again in words."
        )
    return text


# --- the rules: configs/experiments.yaml ------------------------------------------------------


class ModelRules(_Frozen):
    """How the lab tests a change to one model, as a person wrote it down."""

    label: str = Field(min_length=3)
    decision: str
    """The model's decision record, from the project root: where what was tried is kept."""
    tested: tuple[str, ...] = Field(min_length=1)
    """Headings of the decision's sections on how the model is tested."""
    tried: tuple[str, ...] = Field(min_length=1)
    """Headings of the sections on what was tried, or decided against, before."""
    split: str
    metric: str
    uncertainty: str
    acceptance: str
    leakage: tuple[str, ...] = Field(min_length=1)
    steps: tuple[str, ...] = Field(min_length=1)


class ExperimentRules(_Frozen):
    version: int = Field(ge=1)
    models: dict[str, ModelRules]

    @model_validator(mode="after")
    def _every_tested_model(self) -> ExperimentRules:
        if tuple(self.models) != TESTED_MODELS:
            raise ValueError(
                f"the rules must cover the tested models in order, {list(TESTED_MODELS)}, not "
                f"{list(self.models)}"
            )
        return self

    def of(self, model: str) -> ModelRules:
        return self.models[model]


# --- the proposal -----------------------------------------------------------------------------


class ExperimentIdea(_Frozen):
    """The assistant's part of a proposal, in words."""

    title: str = Field(min_length=3, max_length=80)
    observation: str = Field(min_length=10, max_length=600)
    """What the assistant noticed in what the lab showed it."""
    hypothesis: str = Field(min_length=10, max_length=400)
    """What it supposes, put so that a test can say no."""
    change: str = Field(min_length=5, max_length=400)
    """The candidate feature or model change to test."""
    failure_modes: tuple[str, ...] = Field(min_length=1, max_length=FAILURE_MODES)
    """How the change could fail, or fool the test."""

    @field_validator("title", "observation", "hypothesis", "change")
    @classmethod
    def _in_words(cls, value: str) -> str:
        return in_words(value)

    @field_validator("failure_modes")
    @classmethod
    def _each_in_words(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        modes = tuple(in_words(item) for item in value)
        if any(not 5 <= len(item) <= 300 for item in modes):
            raise ValueError("each way it could fail is a sentence of 5 to 300 characters")
        return modes


class Measure(_Frozen):
    """One figure from the model's file that a change must beat or keep."""

    label: str
    value: float
    text: str
    """The figure as the lab writes it: "3.01 points of net rating"."""
    interval: str | None = None


class Quoted(_Frozen):
    """A section of the model's decision, quoted whole."""

    path: str
    heading: str
    text: str
    anchor: str = ""
    """The section's heading as a link fragment, as the document index writes it."""

    @property
    def location(self) -> str:
        return f"{self.path}#{self.anchor}" if self.anchor else self.path


class ExperimentPlan(_Frozen):
    """The lab's part of a proposal: how the model is tested now, from its file and its
    decision."""

    model: ModelKey
    label: str
    revision: int | None = None
    fitted_at: datetime | None = None
    model_file: str | None = None
    missing: str | None = None
    """Why there is no baseline, when the model has not been fitted."""
    baseline: tuple[Measure, ...] = ()
    tested_on: str | None = None
    """The seasons the current test predicted, in words."""
    split: str
    metric: str
    uncertainty: str
    acceptance: str
    leakage: tuple[str, ...]
    tested: tuple[Quoted, ...] = ()
    tried: tuple[Quoted, ...] = ()
    steps: tuple[str, ...]
    decision: str


class ExperimentProposal(_Frozen):
    """An experiment for a future milestone, as the user reviews it."""

    idea: ExperimentIdea
    plan: ExperimentPlan

    @property
    def model(self) -> str:
        return self.plan.model

    @property
    def title(self) -> str:
        return self.idea.title

    @property
    def fingerprint(self) -> str:
        """Twelve hex digits naming everything in the proposal: kept twice, it is kept once."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]

    def document(self, level: int = 1) -> str:
        """The proposal as a Markdown document: the idea, then the lab's test. ``level`` is
        the depth of its title, for a proposal set inside another document."""
        idea, plan = self.idea, self.plan
        title, part = "#" * level, "#" * (level + 1)
        about = plan.label
        if plan.revision is not None:
            about += f", revision {plan.revision}"
        if plan.fitted_at is not None:
            about += f", fitted {plan.fitted_at:%Y-%m-%d}"
        lines = [
            f"{title} Experiment proposal: {idea.title}",
            "",
            f"For the {about}. A proposal only: nothing in the lab applies it. A change to the "
            "model is a milestone of its own, fitted on request and tested out of sample.",
            "",
            f"{part} The idea - the assistant's, not tested",
            "",
            f"**What was noticed.** {idea.observation}",
            "",
            f"**The hypothesis.** {idea.hypothesis}",
            "",
            f"**The change to test.** {idea.change}",
            "",
            "**How it could fail.**",
            "",
            *(f"- {item}" for item in idea.failure_modes),
            "",
            f"{part} The test - the lab's, from the model's file and its decision",
            "",
        ]
        if plan.baseline:
            lines += ["**What it must beat or keep.**", "", "| Measure | Now |", "| --- | --- |"]
            for measure in plan.baseline:
                now = measure.text + (f" ({measure.interval})" if measure.interval else "")
                lines.append(f"| {measure.label} | {now} |")
            lines.append("")
        if plan.missing:
            lines += [f"**What it must beat.** {plan.missing}", ""]
        if plan.tested_on:
            lines += [f"**Tested on.** {plan.tested_on}", ""]
        lines += [
            f"**How seasons are split.** {plan.split}",
            "",
            f"**What is measured.** {plan.metric}",
            "",
            f"**How sure.** {plan.uncertainty}",
            "",
            f"**When it would be kept.** {plan.acceptance}",
            "",
            "**Leakage to rule out.**",
            "",
            *(f"- {item}" for item in plan.leakage),
            "",
        ]
        for heading, sections in (
            ("How the model is tested now", plan.tested),
            ("What was tried before", plan.tried),
        ):
            for section in sections:
                lines += [f"**{heading}** ({section.path}, {section.heading}):", ""]
                lines += [f"> {line}" if line else ">" for line in section.text.splitlines()]
                lines.append("")
        lines += ["**Steps for the milestone that would build it.**", ""]
        lines += [f"{number}. {step}" for number, step in enumerate(plan.steps, start=1)]
        return "\n".join(lines).rstrip() + "\n"
