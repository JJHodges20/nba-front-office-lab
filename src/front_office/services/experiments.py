"""Experiment proposals for the lab's tested models: the lab's part (decision 0018, A8).

``plan`` reads what a proposal for one model must say from the lab's own records: the
figures a change must beat or keep, from the model's fitted file; how the model is tested
and what was tried before, quoted whole from its decision; and the rules written in
``configs/experiments.yaml``. ``draft`` puts the assistant's idea beside it.

Nothing here fits, changes or keeps anything. Keeping a proposal is the workspace's
(``WorkspaceService.keep_experiment``), at the user's click, and it changes no model, no
setting and no data.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from front_office.config.experiments import load_experiment_rules
from front_office.config.models import (
    fit_evidence_path,
    postseason_model_path,
    simulator_model_path,
    value_model_path,
)
from front_office.domain.documents import TRAIL, Section
from front_office.domain.experiments import (
    TESTED_MODELS,
    ExperimentIdea,
    ExperimentPlan,
    ExperimentProposal,
    ExperimentRules,
    Measure,
    Quoted,
)
from front_office.domain.stages import stage
from front_office.services.lab import Lab


class UnknownModel(ValueError):
    """A proposal names a model the lab does not test."""


class _Baseline:
    """What one model's file says a change must beat: its figures, and where they are."""

    def __init__(
        self,
        measures: Sequence[Measure] = (),
        *,
        tested_on: str | None = None,
        revision: int | None = None,
        fitted_at: datetime | None = None,
        model_file: str | None = None,
        missing: str | None = None,
    ) -> None:
        self.measures = tuple(measures)
        self.tested_on = tested_on
        self.revision = revision
        self.fitted_at = fitted_at
        self.model_file = model_file
        self.missing = missing


class ExperimentService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def rules(self) -> ExperimentRules:
        return load_experiment_rules(self._lab.settings.config_dir)

    @property
    def models(self) -> tuple[str, ...]:
        """The models a proposal may aim at."""
        return TESTED_MODELS

    def plan(self, model: str) -> ExperimentPlan:
        """The lab's part of a proposal for ``model``."""
        if model not in TESTED_MODELS:
            raise UnknownModel(
                f"no tested model called {model!r}; the lab tests {', '.join(TESTED_MODELS)}"
            )
        rules = self.rules.of(model)
        readers: dict[str, Callable[[], _Baseline]] = {
            "player_value": self._value,
            "postseason": self._postseason,
            "simulator": self._simulator,
            "roster_fit": self._fit,
        }
        baseline = readers[model]()
        sections = self._lab.documents.sections()
        return ExperimentPlan(
            model=model,  # type: ignore[arg-type]
            label=rules.label,
            revision=baseline.revision,
            fitted_at=baseline.fitted_at,
            model_file=baseline.model_file,
            missing=baseline.missing,
            baseline=baseline.measures,
            tested_on=baseline.tested_on,
            split=rules.split,
            metric=rules.metric,
            uncertainty=rules.uncertainty,
            acceptance=rules.acceptance,
            leakage=rules.leakage,
            tested=quoted(sections, rules.decision, rules.tested),
            tried=quoted(sections, rules.decision, rules.tried),
            steps=rules.steps,
            decision=rules.decision,
        )

    def draft(self, model: str, idea: ExperimentIdea) -> ExperimentProposal:
        """The assistant's idea beside the lab's part: a proposal for the user to review."""
        return ExperimentProposal(idea=idea, plan=self.plan(model))

    # --- what each model's file says --------------------------------------------------------

    def _file(self, path: Path) -> str:
        try:
            return path.relative_to(self._lab.settings.project_root).as_posix()
        except ValueError:
            return path.name

    def _value(self) -> _Baseline:
        model = self._lab.value.model()
        if model is None:
            return _Baseline(missing=_unfitted("player value model", "fol value fit --write"))
        tested = model.validation
        measures = [
            Measure(
                label="Typical miss on a team's net rating, minutes as played (RMSE)",
                value=tested.net.rmse,
                text=f"{tested.net.rmse:.2f} points",
            )
        ]
        if tested.projected is not None:
            measures.append(
                Measure(
                    label="Typical miss with the minutes projected, as a forecast has them (RMSE)",
                    value=tested.projected.rmse,
                    text=f"{tested.projected.rmse:.2f} points",
                )
            )
        return _Baseline(
            measures,
            tested_on=(
                f"Each season from {tested.first_test_season} to {tested.last_test_season} - "
                f"{tested.team_seasons} team-seasons - predicted from the seasons before it."
            ),
            revision=model.revision,
            fitted_at=model.fitted_at,
            model_file=self._file(value_model_path(self._lab.settings.config_dir)),
        )

    def _postseason(self) -> _Baseline:
        model = self._lab.postseason.model()
        if model is None:
            return _Baseline(missing=_unfitted("postseason model", "fol playoffs fit --write"))
        evaluation = model.evaluation
        series = evaluation.series
        measures = [
            Measure(
                label=f"Series model: log loss on {series.series} series",
                value=series.log_loss,
                text=f"{series.log_loss:.3f}",
            ),
            Measure(
                label="Series model: calibration slope (1 means its chances mean what they say)",
                value=series.calibration.slope,
                text=f"{series.calibration.slope:.2f}",
            ),
        ]
        for item in evaluation.bracket.stages:
            if item.key == "won_championship":
                measures.append(
                    Measure(
                        label="The bracket carried through each season: the title, log loss",
                        value=item.log_loss,
                        text=f"{item.log_loss:.3f}",
                    )
                )
        for reading, stages in (
            ("Season model", evaluation.season.stages),
            (
                "Season model read as a forecast",
                () if evaluation.before_season is None else evaluation.before_season.stages,
            ),
        ):
            for item in stages:
                if item.key in ("made_playoffs", "won_championship"):
                    measures.append(
                        Measure(
                            label=f"{reading}: {stage(item.key).label.lower()}, log loss",
                            value=item.log_loss,
                            text=f"{item.log_loss:.3f}",
                        )
                    )
        return _Baseline(
            measures,
            tested_on=(
                f"Each season from {series.first_test_season} to {series.last_test_season} - "
                f"{series.series} series and {evaluation.season.team_seasons} team-seasons - "
                "scored from the seasons before it."
            ),
            revision=model.revision,
            fitted_at=model.fitted_at,
            model_file=self._file(postseason_model_path(self._lab.settings.config_dir)),
        )

    def _simulator(self) -> _Baseline:
        model = self._lab.simulator.model()
        if model is None:
            return _Baseline(missing=_unfitted("simulator", "fol simulate fit --write"))
        test = model.test
        measures = [
            Measure(
                label="The median drawn season's miss on wins per 82 (RMSE)",
                value=test.rmse,
                text=f"{test.rmse:.2f} wins",
            ),
            Measure(
                label="An even record for every team, for comparison (RMSE)",
                value=test.baseline_rmse,
                text=f"{test.baseline_rmse:.2f} wins",
            ),
        ]
        for item in test.coverage:
            measures.append(
                Measure(
                    label=f"How often the {item.level:.0%} interval held the wins that happened",
                    value=item.share,
                    text=f"{item.share:.0%} of {item.cases} team-seasons",
                )
            )
        return _Baseline(
            measures,
            tested_on=(
                f"Every team-season the value model predicted out of sample, "
                f"{test.first_test_season} to {test.last_test_season}: {test.team_seasons}."
            ),
            revision=model.revision,
            fitted_at=model.fitted_at,
            model_file=self._file(simulator_model_path(self._lab.settings.config_dir)),
        )

    def _fit(self) -> _Baseline:
        evidence = self._lab.fit.evidence()
        if evidence is None:
            return _Baseline(missing=_unfitted("roster fit test", "fol fit test --write"))
        change = evidence.combined.change
        verdict = "usable" if evidence.combined.is_usable else "not usable: none is applied"
        measures = [
            Measure(
                label="The value model's typical miss on the team-seasons tested (RMSE)",
                value=evidence.baseline_rmse,
                text=f"{evidence.baseline_rmse:.2f} points",
            ),
            Measure(
                label="With the correction from every fit measure together (RMSE)",
                value=evidence.combined.rmse,
                text=f"{evidence.combined.rmse:.2f} points",
                interval=(
                    f"a change of {change.difference:+.2f}, 95% interval {change.low:+.2f} to "
                    f"{change.high:+.2f}; the correction is {verdict}"
                ),
            ),
        ]
        return _Baseline(
            measures,
            tested_on=(
                f"Each season from {evidence.first_test_season} to {evidence.last_test_season} "
                f"- {evidence.team_seasons} team-seasons - with corrections learned from the "
                "seasons before it."
            ),
            revision=evidence.revision,
            fitted_at=evidence.fitted_at,
            model_file=self._file(fit_evidence_path(self._lab.settings.config_dir)),
        )


def quoted(sections: Sequence[Section], path: str, headings: Sequence[str]) -> tuple[Quoted, ...]:
    """The sections of ``path`` under ``headings``, each named by its own heading, in the
    order asked; a heading the document no longer has is left out."""
    found = []
    for heading in headings:
        for section in sections:
            if section.path == path and section.heading.split(TRAIL)[-1] == heading:
                found.append(
                    Quoted(
                        path=path,
                        heading=section.heading,
                        text=section.text,
                        anchor=section.anchor,
                    )
                )
                break
    return tuple(found)


def _unfitted(what: str, command: str) -> str:
    return f"No {what} has been fitted yet ({command}), so there is no figure to beat."
