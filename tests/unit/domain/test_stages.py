"""The stages of a postseason: one list, read by the benchmarks and the postseason model."""

from __future__ import annotations

import pytest

from front_office.analytics import benchmarks
from front_office.domain import stages as module
from front_office.domain.stages import (
    BRACKET_STAGE_KEYS,
    BRACKET_STAGES,
    ROUND_STAGE_KEYS,
    STAGE_KEYS,
    STAGES,
    stage,
)


def test_six_stages_each_containing_the_next() -> None:
    assert STAGE_KEYS == (
        "reached_postseason",
        "made_playoffs",
        "won_a_round",
        "made_conference_finals",
        "made_finals",
        "won_championship",
    )
    assert [item.short for item in STAGES] == [
        "Postseason",
        "Playoffs",
        "Second round",
        "Conference finals",
        "NBA Finals",
        "Champion",
    ]
    assert all(item.label and item.description.endswith(".") for item in STAGES)


def test_the_model_estimates_the_bracket_stages_and_the_rounds_within_it() -> None:
    assert BRACKET_STAGE_KEYS == STAGE_KEYS[1:] and BRACKET_STAGES == STAGES[1:]
    assert ROUND_STAGE_KEYS == STAGE_KEYS[2:] and len(ROUND_STAGE_KEYS) == 4


def test_a_stage_is_found_by_key_and_an_unknown_key_says_what_is_known() -> None:
    assert stage("made_finals") is STAGES[4]
    with pytest.raises(KeyError, match="no stage named 'final'"):
        stage("final")


def test_the_benchmarks_read_the_same_list() -> None:
    assert benchmarks.STAGES is module.STAGES and benchmarks.STAGE_KEYS is module.STAGE_KEYS
    assert benchmarks.stage is module.stage and benchmarks.Stage is module.Stage
