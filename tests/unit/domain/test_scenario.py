"""A scenario: what the user lays over a roster, and what is refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from front_office.domain.scenario import (
    Adjustment,
    Availability,
    Development,
    Scenario,
    SubjectKind,
)


class TestScenario:
    def test_an_unchanged_scenario_is_its_own_baseline(self) -> None:
        scenario = Scenario(subject=SubjectKind.TEAM, key=1)
        assert not scenario.is_changed and scenario.baseline == scenario
        assert scenario.simulations == 10_000 and scenario.seed == 0
        assert scenario.adjustment(5) == Adjustment() and scenario.adjustment(5).is_empty
        assert scenario.availability is Availability.AS_PROJECTED
        assert scenario.development is Development.EXPECTED

    @pytest.mark.parametrize(
        "change",
        [
            {"added": (2,)},
            {"removed": (2,)},
            {"adjustments": {2: Adjustment(games_missed=10)}},
            {"availability": "healthy"},
            {"development": "regression"},
        ],
    )
    def test_anything_that_differs_is_a_change(self, change: dict) -> None:
        assert Scenario(subject="team", key=1, **change).is_changed

    def test_an_empty_adjustment_changes_nothing(self) -> None:
        assert not Scenario(subject="team", key=1, adjustments={2: Adjustment()}).is_changed

    def test_the_baseline_keeps_the_subject_and_the_draw(self) -> None:
        changed = Scenario(
            subject="roster", key=3, added=(2,), availability="healthy", simulations=500, seed=4
        )
        assert changed.baseline == Scenario(subject="roster", key=3, simulations=500, seed=4)
        assert (
            changed.subject is SubjectKind.ROSTER and changed.availability is Availability.HEALTHY
        )

    def test_the_fingerprint_follows_every_field(self) -> None:
        base = Scenario(subject="team", key=1)
        assert base.fingerprint == Scenario(subject="team", key=1).fingerprint
        assert len(base.fingerprint) == 12
        for other in (
            Scenario(subject="team", key=1, seed=1),
            Scenario(subject="team", key=2),
            Scenario(subject="team", key=1, adjustments={2: Adjustment(share=0.3)}),
            Scenario(subject="team", key=1, development="optimistic"),
        ):
            assert other.fingerprint != base.fingerprint

    @pytest.mark.parametrize(
        "bad",
        [
            {"added": (2,), "removed": (2,)},
            {"added": (2, 2)},
            {"removed": (3, 3)},
            {"removed": (2,), "adjustments": {2: Adjustment(games_missed=1)}},
            {"simulations": 10},
            {"simulations": 10**6},
            {"subject": "club"},
            {"availability": "lucky"},
        ],
    )
    def test_an_impossible_scenario_is_refused(self, bad: dict) -> None:
        fields = {"subject": "team", "key": 1, **bad}
        with pytest.raises((ValidationError, ValueError)):
            Scenario(**fields)

    def test_adjustments_keep_to_their_limits(self) -> None:
        full = Adjustment(games_missed=82, development=10, share=1.0, salary=0)
        assert not full.is_empty
        for bad in ({"games_missed": 83}, {"development": 11}, {"share": 1.5}, {"salary": -1}):
            with pytest.raises(ValidationError):
                Adjustment(**bad)


def test_presets_have_titles_and_descriptions() -> None:
    for item in (*Availability, *Development):
        assert item.title and item.description.endswith(".")
    assert Availability.AS_PROJECTED.title == "As projected"
    assert Development.EXPECTED.title == "As projected"
    assert "optimistic" in Availability.HEALTHY.description.lower()
    assert "pessimistic" in Availability.HIGH_INJURY.description.lower()
