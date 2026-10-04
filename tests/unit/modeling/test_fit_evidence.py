"""The roster fit evidence: a planted effect is found, nothing else is, and the arithmetic.

The league is invented. Its team ratings follow the value model exactly, plus luck, plus
one thing the value model cannot see: a team gains points of offense for every inch of
the minutes-weighted height its players had the season before. The evidence must find
that in the height measure, find it nowhere else, and offer a correction that helps.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from front_office.config import load_archetypes
from front_office.domain.fit import MEASURE_KEYS, Area
from front_office.domain.fit_model import FitEvidence, FitSpec
from front_office.domain.value_model import ValueSpec
from front_office.modeling.fit import (
    LAG,
    TESTED,
    NotEnoughEvidence,
    adjustment,
    fit_evidence,
    team_profiles,
)
from front_office.modeling.fit.evidence import (
    _coefficient,
    _expanding,
    _moments,
    _standardise,
    prepare,
)
from front_office.modeling.value import fit_value_model
from tests.conftest import REPO_ROOT
from tests.synthetic_lab import league_frames
from tests.value_reference import planted_league

VALUE_SPEC = ValueSpec(first_test_season="2004-05", resamples=200)
FIT_SPEC = FitSpec(first_test_season="2006-07", min_training_seasons=2, resamples=200)
INCH = 3.0
"""Points of offense a team gains for each inch of last season's minutes-weighted height
above the league's: the planted effect."""
AT = datetime(2026, 10, 4, 12, 0)


@pytest.fixture(scope="module")
def planted():  # type: ignore[no-untyped-def]
    """The league, the value model fitted to it, the frames a build would hold, and the
    height effect's size in standard deviations."""
    archetypes = load_archetypes(REPO_ROOT / "configs")
    league = planted_league(VALUE_SPEC, noise=1.0, seed=5, teams=30, seasons=14)
    lagged = team_profiles(league_frames(league), archetypes, lag=LAG)
    height = lagged.set_index(["season", "team_id"])["height"]
    for year in league.years[1:]:
        label = f"{year}-{str(year + 1)[-2:]}"
        this_season = height.loc[label]
        centred = this_season - this_season.mean()
        league.plant(
            year,
            {
                team: (offense + INCH * float(centred[team]), defense)
                for team, (offense, defense) in league.ratings[year].items()
            },
        )
    tables = league.tables()
    model = fit_value_model(tables, VALUE_SPEC, revision=1, fitted_at=AT)
    frames = league_frames(league, model, archetypes)
    return league, model, archetypes, frames, float(centred.std())


@pytest.fixture(scope="module")
def evidence(planted) -> FitEvidence:  # type: ignore[no-untyped-def]
    league, model, archetypes, frames, _ = planted
    return fit_evidence(frames, model, archetypes, FIT_SPEC, revision=1, fitted_at=AT)


class TestWhatIsFound:
    def test_the_planted_measure_is_found_and_found_strongest(
        self, evidence: FitEvidence, planted
    ) -> None:
        *_, spread = planted
        height = evidence.measure("height")
        # Per standard deviation: the inches planted, times the spread of the measure.
        assert height.coefficient == pytest.approx(INCH * spread, rel=0.25)
        assert height.coefficient_low > 0 and height.is_distinguishable
        assert height.change.difference < -0.5
        strongest = min(evidence.measures, key=lambda item: item.change.difference)
        assert strongest.key == "height"
        assert height.area == str(Area.STRUCTURE) and height.teams == evidence.team_seasons

    def test_nothing_else_was_planted_and_little_else_is_found(self, evidence: FitEvidence) -> None:
        others = [item for item in evidence.distinguishable if item.key != "height"]
        # Twenty-six measures with nothing behind them, at 95%: a stray or two is chance.
        assert len(others) <= 3, [item.key for item in others]
        for item in evidence.measures:
            if item.key != "height":
                assert abs(item.coefficient) < abs(evidence.measure("height").coefficient)

    def test_together_the_measures_leave_the_sum_of_the_parts_missing_by_less(
        self, evidence: FitEvidence
    ) -> None:
        combined = evidence.combined
        assert combined.is_usable and combined.rmse < evidence.baseline_rmse
        assert combined.change.high < 0
        weights = {term.key: term for term in combined.terms}
        assert weights["height"].coefficient > 0 and weights["height"].low > 0
        assert set(weights) == set(TESTED)

    def test_leaving_out_the_area_that_holds_the_effect_is_missed(
        self, evidence: FitEvidence
    ) -> None:
        by_area = {item.key: item for item in evidence.combined.ablations}
        assert set(by_area) == {area.name.lower() for area in Area if area is not Area.PARTS}
        assert by_area["structure"].change.low > 0
        assert by_area["structure"].change.difference > by_area["usage"].change.difference

    def test_the_correction_reads_the_profile_through_the_terms(
        self, evidence: FitEvidence
    ) -> None:
        combined = evidence.combined
        height = next(term for term in combined.terms if term.key == "height")
        average = {term.key: term.mean for term in combined.terms}
        assert adjustment(evidence, average) == pytest.approx(combined.intercept)
        taller = {**average, "height": height.mean + height.scale}
        assert adjustment(evidence, taller) == pytest.approx(
            combined.intercept + height.coefficient
        )
        # A measure the profile lacks, or cannot give, is taken at its average.
        assert adjustment(evidence, {"height": height.mean + height.scale}) == pytest.approx(
            combined.intercept + height.coefficient
        )
        assert adjustment(evidence, {"height": float("nan")}) == pytest.approx(combined.intercept)

    def test_what_was_tested_and_when(self, evidence: FitEvidence, planted) -> None:
        league, model, archetypes, frames, _ = planted
        assert evidence.tested == TESTED and len(TESTED) == 27
        assert evidence.team_seasons == 30 * 8
        assert (evidence.first_test_season, evidence.last_test_season) == ("2006-07", "2013-14")
        assert (evidence.value_model_version, evidence.archetype_version) == ("r1", "v1")
        assert (evidence.version, evidence.revision) == ("f1", 1)
        assert [item.key for item in evidence.measures] == list(TESTED)
        assert 0 < evidence.baseline_rmse < 6

    def test_it_survives_being_written_down(self, evidence: FitEvidence) -> None:
        again = FitEvidence.model_validate_json(evidence.model_dump_json())
        assert again == evidence
        with pytest.raises(KeyError, match="no evidence on a measure named 'luck'"):
            evidence.measure("luck")


class TestWhatCannotBeTested:
    def test_a_model_without_a_test_on_record(self, planted) -> None:
        league, model, archetypes, frames, _ = planted
        bare = model.model_copy(update={"backtest": ()})
        with pytest.raises(NotEnoughEvidence, match="no test on record"):
            prepare(frames, bare, archetypes)

    def test_too_few_seasons_before_the_first_tested(self, planted) -> None:
        league, model, archetypes, frames, _ = planted
        late = FitSpec(first_test_season="2030-31", min_training_seasons=3, resamples=50)
        with pytest.raises(
            NotEnoughEvidence, match="fit is tested from 2030-31 and needs at least 3"
        ):
            fit_evidence(frames, model, archetypes, late, revision=1, fitted_at=AT)

    def test_a_first_test_season_too_early_is_moved_to_the_first_that_can_be(self, planted) -> None:
        league, model, archetypes, frames, _ = planted
        early = FitSpec(first_test_season="2004-05", min_training_seasons=3, resamples=50)
        found = fit_evidence(frames, model, archetypes, early, revision=1, fitted_at=AT)
        # The value model's test begins in 2004-05; three seasons of it come first.
        assert found.first_test_season == "2007-08" and found.team_seasons == 30 * 7

    def test_the_sums_of_parts_are_not_candidates(self) -> None:
        for key in ("impact_sum", "offense_sum", "defense_sum", "projected_sum", "minutes_covered"):
            assert key not in TESTED
        assert set(TESTED) < set(MEASURE_KEYS)


class TestTheArithmetic:
    def test_standardising_ignores_missing_and_holds_constant_columns(self) -> None:
        features = np.array([[1.0, 5.0], [3.0, 5.0], [np.nan, 5.0]])
        means, scales = _moments(features)
        assert means.tolist() == [2.0, 5.0] and scales.tolist() == [1.0, 1.0]
        standardised = _standardise(features, means, scales)
        assert standardised.tolist() == [[-1.0, 0.0], [1.0, 0.0], [0.0, 0.0]]
        none, one = _moments(np.zeros((3, 0)))
        assert none.shape == (0,) and one.shape == (0,)

    def test_a_season_is_corrected_from_earlier_seasons_only(self) -> None:
        start = np.repeat([2000, 2001, 2002, 2003], 4)
        feature = np.tile([-1.0, 0.0, 1.0, 2.0], 4)
        residual = 2.0 * feature + 1.0
        residual[start == 2003] += 10.0  # the last season behaves differently
        tested, correction = _expanding(
            feature[:, None], residual, start, 2002, FitSpec(min_training_seasons=2)
        )
        assert tested.tolist() == [False] * 8 + [True] * 8
        # Fitted to 2000 and 2001: exact for 2002, and blind to what 2003 did.
        assert correction[start == 2002] == pytest.approx(residual[start == 2002])
        assert correction[start == 2003] == pytest.approx(
            residual[start == 2003] - 10.0 * 0.5, abs=5
        )
        assert (correction[~tested] == 0).all()

    def test_a_missing_value_in_a_tested_season_stands_at_the_training_mean(self) -> None:
        # Later seasons sit far from earlier ones, so where a gap is put depends on which
        # seasons the mean comes from; it must come from the seasons learned from.
        start = np.repeat([2000, 2001, 2002, 2003], 4)
        feature = np.array([0.0, 1.0, 2.0, 3.0] * 2 + [10.0, 11.0, 12.0, 13.0] * 2)
        residual = 2.0 * feature
        with_gap = feature.copy()
        with_gap[8] = np.nan  # the first row of 2002, a tested season
        tested, correction = _expanding(
            with_gap[:, None], residual, start, 2002, FitSpec(min_training_seasons=2)
        )
        assert tested[8]
        assert correction[8] == pytest.approx(2.0 * 1.5)  # the mean of 2000 and 2001
        assert correction[9] == pytest.approx(residual[9])

    def test_a_relation_with_nothing_left_to_luck_has_a_closed_interval(self) -> None:
        start = np.repeat([2000, 2001, 2002, 2003, 2004], 6)
        rng = np.random.default_rng(1)
        feature = rng.normal(size=30)
        residual = 1.5 * feature - 0.25
        coefficient, low, high = _coefficient(
            feature[:, None], residual, start, FitSpec(resamples=100)
        )
        per_sd = 1.5 * feature.std()
        assert coefficient[0] == pytest.approx(per_sd)
        assert low[0] == pytest.approx(per_sd, rel=1e-6) and high[0] == pytest.approx(
            per_sd, rel=1e-6
        )

    def test_the_problem_is_the_backtest_beside_last_seasons_profiles(self, planted) -> None:
        league, model, archetypes, frames, _ = planted
        problem = prepare(frames, model, archetypes)
        backtest = pd.DataFrame([row.model_dump() for row in model.backtest])
        assert len(problem.rows) == len(backtest)
        assert list(problem.rows.columns[:5]) == [
            "season",
            "team_id",
            "predicted",
            "actual",
            *TESTED[:1],
        ]
        lagged = team_profiles(frames, archetypes, lag=1).set_index(["season", "team_id"])
        row = problem.rows.iloc[10]
        assert row["height"] == lagged.at[(row["season"], row["team_id"]), "height"]
        assert problem.residual[10] == pytest.approx(row["actual"] - row["predicted"])
        assert problem.features.shape == (len(backtest), len(TESTED))
