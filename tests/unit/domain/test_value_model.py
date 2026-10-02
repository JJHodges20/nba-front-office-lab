"""The value model's specification and fitted form."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from front_office.domain.value_model import Comparison, Term, ValueModel, ValueSpec
from tests.value_reference import DEFENSE, MODEL_TERMS, OFFENSE, planted_model


class TestSpec:
    def test_defaults_are_the_documented_choices(self) -> None:
        spec = ValueSpec()
        assert spec.season_weights == (1.0, 0.5, 0.25)
        assert (spec.ballast_minutes, spec.age_centre) == (750, 27)
        assert (spec.first_test_season, spec.replacement_rank, spec.wins_window) == (
            "2006-07",
            10,
            2,
        )
        assert (spec.resamples, spec.seed, spec.confidence) == (2000, 0, 0.95)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("season_weights", (), "at least one season"),
            ("season_weights", (1.0, 0.0), "must be positive"),
            ("season_weights", (0.5, 1.0), "must not grow"),
            ("ballast_minutes", 0, "greater than 0"),
            ("first_test_season", "2006", "not a season label"),
            ("replacement_rank", 0, "greater than 0"),
            ("wins_window", -1, "greater than or equal to 0"),
            ("resamples", 0, "greater than 0"),
            ("confidence", 1.0, "less than 1"),
            ("confidence", 0.5, "greater than 0.5"),
        ],
    )
    def test_nonsense_is_refused(self, field: str, value: object, message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            ValueSpec(**{field: value})

    def test_unknown_settings_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="ballast"):
            ValueSpec(ballast=500)

    def test_equal_weights_are_allowed(self) -> None:
        assert ValueSpec(season_weights=(1.0, 1.0)).season_weights == (1.0, 1.0)

    def test_a_specification_cannot_be_changed_in_place(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            ValueSpec().ballast_minutes = 10

    def test_the_fingerprint_follows_every_setting(self) -> None:
        base = ValueSpec()
        assert base.fingerprint == ValueSpec().fingerprint
        assert len(base.fingerprint) == 12
        changed = [
            base.model_copy(update=update)
            for update in (
                {"season_weights": (1.0, 0.5)},
                {"ballast_minutes": 751.0},
                {"age_centre": 28.0},
                {"first_test_season": "2007-08"},
                {"replacement_rank": 11},
                {"wins_window": 3},
                {"resamples": 1999},
                {"seed": 1},
                {"confidence": 0.9},
            )
        ]
        prints = {spec.fingerprint for spec in changed}
        assert len(prints) == len(changed) and base.fingerprint not in prints


class TestTerm:
    TERM = Term(
        key="stl", offense=0.1, defense=0.6, offense_low=-0.2, offense_high=0.4,
        defense_low=0.3, defense_high=0.9, net_low=0.35, net_high=1.0,
    )  # fmt: skip

    def test_net_is_both_sides_together(self) -> None:
        assert self.TERM.net == pytest.approx(0.7)
        assert [self.TERM.weight(side) for side in ("offense", "defense", "net")] == [
            0.1, 0.6, pytest.approx(0.7),
        ]  # fmt: skip

    def test_each_side_has_its_own_interval(self) -> None:
        assert self.TERM.interval("offense") == (-0.2, 0.4)
        assert self.TERM.interval("defense") == (0.3, 0.9)
        assert self.TERM.interval("net") == (0.35, 1.0)

    @pytest.mark.parametrize("method", ["weight", "interval"])
    def test_an_unknown_side_is_an_error(self, method: str) -> None:
        with pytest.raises(KeyError, match="no such side: 'bench'"):
            getattr(self.TERM, method)("bench")


class TestComparison:
    def comparison(self, low: float, high: float) -> Comparison:
        return Comparison(
            key="pie", label="PIE", rmse=3.4, mae=2.7, difference=-0.4, low=low, high=high
        )

    @pytest.mark.parametrize(
        ("low", "high", "apart"),
        [
            (-0.5, -0.2, True),
            (0.1, 0.3, True),
            (-0.1, 0.2, False),
            (0.0, 0.3, False),
            (-0.3, 0.0, False),
        ],
    )
    def test_distinguishable_means_the_interval_excludes_zero(
        self, low: float, high: float, apart: bool
    ) -> None:
        assert self.comparison(low, high).is_distinguishable is apart


class TestModel:
    MODEL = planted_model(ValueSpec(), revision=3)

    def test_rows_are_stamped_with_the_revision(self) -> None:
        assert self.MODEL.version == "r3"

    def test_terms_keep_their_order_and_are_found_by_key(self) -> None:
        assert self.MODEL.keys == MODEL_TERMS
        assert self.MODEL.term("blk").defense == DEFENSE["blk"]
        with pytest.raises(KeyError, match="nothing named 'hustle'"):
            self.MODEL.term("hustle")

    def test_weights_by_side(self) -> None:
        assert self.MODEL.weights("offense") == OFFENSE
        assert self.MODEL.weights("defense") == DEFENSE
        net = self.MODEL.weights("net")
        assert net == {key: pytest.approx(OFFENSE[key] + DEFENSE[key]) for key in MODEL_TERMS}
        assert list(net) == list(MODEL_TERMS)

    def test_a_revision_starts_at_one(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            ValueModel.model_validate({**self.MODEL.model_dump(), "revision": 0})

    def test_validation_finds_comparisons_by_key(self) -> None:
        item = Comparison(
            key="pie", label="PIE", rmse=3.4, mae=2.7, difference=-0.4, low=-0.5, high=-0.2
        )
        tested = self.MODEL.validation.model_copy(
            update={"baselines": (item,), "ablations": (item,)}
        )
        assert tested.baseline("pie") is item and tested.ablation("pie") is item
        with pytest.raises(KeyError, match="nothing named 'zero'"):
            tested.baseline("zero")

    def test_a_model_round_trips_through_json(self) -> None:
        assert ValueModel.model_validate_json(self.MODEL.model_dump_json()) == self.MODEL
