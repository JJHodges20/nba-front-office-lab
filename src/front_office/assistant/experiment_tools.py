"""Experiment proposals for the lab's tested models (decision 0018, A8).

``propose_experiment`` drafts one when the user asks for an experiment or an idea to
improve a model. The idea is the model's, in words - its arguments hold no figure, so none
can be made up and then cited back as a result's - and the lab adds the rest from the
model's file and its decision (``ExperimentService.plan``): what a change must beat or
keep, how the model is tested, the leakage to rule out, what was tried before and the
steps a future milestone would take. The proposal travels with the answer, and only the
user's click keeps it in the workspace. Nothing here fits, changes or keeps anything.
"""

from __future__ import annotations

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import Found, Handler
from front_office.domain.assistant import Evidence, EvidenceKind, ResultStatus
from front_office.domain.experiments import ExperimentIdea, ExperimentPlan
from front_office.services import Lab

TRIED_SHOWN = 900
"""Characters of what was tried before the model reads; the page and the document hold it
whole."""
NOT_APPLIED = (
    "Only a proposal, to review: no model, setting or data was changed. It can be kept in the "
    "workspace; changing a model would be a separate step, tested on past seasons first."
)
"""A note the page shows and the model reads, so it speaks to neither: at A8 a model read "for
you to review" as its own task and offered to draft the proposal it had just drafted."""


def propose_experiment(lab: Lab, args: t.ProposeExperiment) -> Found:
    idea = ExperimentIdea(
        title=args.name,
        observation=args.observation,
        hypothesis=args.hypothesis,
        change=args.change,
        failure_modes=tuple(args.failure_modes),
    )
    proposal = lab.experiments.draft(args.model, idea)
    plan = proposal.plan
    lines = [
        f'Drafted "{idea.title}", an experiment proposal for the {_about(plan)}. It is shown to '
        "the user under the answer, whole, to review and keep. In the answer, give its idea and "
        "what a change must beat, citing this result for each figure."
    ]
    if plan.missing:
        lines.append(plan.missing)
    if plan.baseline:
        lines.append("What a change must beat or keep, from the model's file:")
        lines += [
            f"- {measure.label}: {measure.text}"
            + (f" ({measure.interval})" if measure.interval else "")
            for measure in plan.baseline
        ]
    if plan.tested_on:
        lines.append(f"Tested on: {plan.tested_on}")
    lines.append(f"When a change is kept: {plan.acceptance}")
    lines.append("Leakage to rule out: " + " ".join(plan.leakage))
    for section in plan.tried:
        lines.append(f"Tried before ({section.location}): {_excerpt(section.text)}")
    table = pd.DataFrame(
        [(measure.label, measure.text, measure.interval) for measure in plan.baseline],
        columns=["measure", "now", "interval"],
    )
    return Found(
        ResultStatus.OK,
        f"Experiment proposal: {idea.title}",
        "\n".join(lines),
        table if plan.baseline else None,
        _evidence(plan),
        (NOT_APPLIED,),
        ("modeled",),
        experiments=(proposal,),
    )


def _about(plan: ExperimentPlan) -> str:
    about = plan.label
    if plan.revision is not None:
        about += f", revision {plan.revision}"
    if plan.fitted_at is not None:
        about += f", fitted {plan.fitted_at:%Y-%m-%d}"
    return about


def _evidence(plan: ExperimentPlan) -> tuple[Evidence, ...]:
    evidence = []
    if plan.model_file is not None:
        evidence.append(
            Evidence(
                EvidenceKind.MODEL,
                _about(plan)[:1].upper() + _about(plan)[1:],
                location=plan.model_file,
                version=None if plan.revision is None else f"r{plan.revision}",
            )
        )
    for section in (*plan.tested, *plan.tried):
        evidence.append(
            Evidence(
                EvidenceKind.DOCS, f"{section.path}: {section.heading}", location=section.location
            )
        )
    return tuple(evidence)


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= TRIED_SHOWN:
        return flat
    return flat[: flat.rfind(" ", 0, TRIED_SHOWN)] + " ... (the proposal holds the rest)"


EXPERIMENT_HANDLERS: dict[str, Handler] = {"propose_experiment": propose_experiment}
