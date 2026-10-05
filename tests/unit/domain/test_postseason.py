"""The postseason model's vocabulary: series formats, the specification, and the pieces a fit
writes down."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from front_office.config import load_postseason_spec
from front_office.domain.postseason import (
    DEFAULT_PATTERN,
    FINALS,
    FIRST_ROUND,
    Comparison,
    FormatRule,
    PostseasonSpec,
    SeasonFavourite,
    TypicalTop,
    home_pattern,
)


class TestHomePattern:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("2-2-1-1-1", (True, True, False, False, True, False, True)),
            ("2-3-2", (True, True, False, False, False, True, True)),
            ("2-2-1", (True, True, False, False, True)),
            ("1-1-1", (True, False, True)),
        ],
    )
    def test_blocks_alternate_starting_at_home(self, name: str, expected: tuple) -> None:
        assert home_pattern(name) == expected

    @pytest.mark.parametrize("name", ["2-2", "2-2-1-1", "0-1", "", "2-x-1", "-1-2"])
    def test_a_format_needs_positive_blocks_adding_to_an_odd_length(self, name: str) -> None:
        with pytest.raises(ValueError, match="series format"):
            home_pattern(name)


class TestSpecification:
    def test_the_shipped_specification_is_the_documented_default(self, repo_root: Path) -> None:
        # Written out in full in the file so that every choice can be seen and changed.
        assert load_postseason_spec(repo_root / "configs") == PostseasonSpec()
        text = (repo_root / "configs" / "models" / "postseason.yaml").read_text(encoding="utf-8")
        for setting in PostseasonSpec.model_fields:
            assert f"\n{setting}:" in text, setting
        assert "fol playoffs fit --write" in text

    def test_formats_by_round_and_season(self) -> None:
        spec = PostseasonSpec()
        assert spec.pattern_for(FIRST_ROUND, "2001-02") == "2-2-1"
        assert spec.pattern_for(FIRST_ROUND, "2002-03") == DEFAULT_PATTERN
        assert spec.pattern_for(FINALS, "2012-13") == "2-3-2"
        assert spec.pattern_for(FINALS, "2013-14") == DEFAULT_PATTERN
        assert spec.pattern_for(2, "1996-97") == DEFAULT_PATTERN
        assert spec.is_neutral("2019-20") and not spec.is_neutral("2020-21")

    def test_a_rule_is_validated_like_the_specification(self) -> None:
        rule = FormatRule(round=1, through_season="2001-02", pattern="2-2-1")
        assert rule.through_season == "2001-02"
        with pytest.raises(ValidationError):
            FormatRule(round=5, through_season="2001-02", pattern="2-2-1")
        with pytest.raises(ValidationError):
            FormatRule(round=1, through_season="2001-02", pattern="2-2")

    def test_the_fingerprint_changes_with_any_choice(self) -> None:
        base = PostseasonSpec()
        assert base.fingerprint == PostseasonSpec().fingerprint
        assert PostseasonSpec(top_players=4).fingerprint != base.fingerprint
        assert PostseasonSpec(seed=1).fingerprint != base.fingerprint
        assert len(base.fingerprint) == 12

    @pytest.mark.parametrize(
        "bad",
        [
            {"reliability_edges": (0.0, 0.5)},
            {"reliability_edges": (0.0, 0.6, 0.4, 1.0)},
            {"reliability_edges": (0.1, 1.0)},
            {"kept_draws": 500, "resamples": 100},
            {"confidence": 1.0},
            {"default_pattern": "2-2"},
            {"top_players": 0},
            {"first_test_season": "nonsense"},
            {"unknown": 1},
        ],
    )
    def test_an_impossible_specification_is_refused(self, bad: dict) -> None:
        with pytest.raises((ValidationError, ValueError)):
            PostseasonSpec(**bad)


class TestTheFittedPieces:
    def test_a_comparison_is_clearly_better_when_its_interval_stays_below_zero(self) -> None:
        def comparison(difference: float, low: float, high: float) -> Comparison:
            return Comparison(
                key="a", label="A", log_loss=0.5, brier=0.2, difference=difference, low=low,
                high=high,
            )  # fmt: skip

        better, worse, unsure = (
            comparison(-0.02, -0.03, -0.01),
            comparison(0.02, 0.01, 0.03),
            comparison(0.0, -0.01, 0.01),
        )
        assert better.is_clearly_better and not better.is_clearly_worse
        assert worse.is_clearly_worse and not worse.is_clearly_better
        assert not unsure.is_clearly_better and not unsure.is_clearly_worse

    def test_a_favourite_won_when_it_is_the_champion(self) -> None:
        won = SeasonFavourite(
            season="2006-07", favourite_team_id=1, favourite_probability=0.4,
            champion_team_id=1, champion_probability=0.4,
        )  # fmt: skip
        lost = won.model_copy(update={"champion_team_id": 2, "champion_probability": 0.1})
        assert won.favourite_won and not lost.favourite_won

    def test_typical_top_player_quality_is_a_line_in_net_rating(self) -> None:
        assert TypicalTop(slope=0.2, intercept=1.5).at(5.0) == pytest.approx(2.5)
        assert TypicalTop(slope=0.2, intercept=1.5).at(-5.0) == pytest.approx(0.5)
