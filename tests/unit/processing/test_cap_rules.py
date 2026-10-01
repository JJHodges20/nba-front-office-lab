from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config.season_rules import load_all_season_rules
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.schema import validate_frame
from front_office.domain.tables.finance import SALARY_CAP_RULES
from front_office.processing.cap_rules import cap_rules_frame


@pytest.fixture(scope="module")
def shipped(repo_root: Path) -> list[SeasonRules]:
    return list(load_all_season_rules(repo_root / "configs" / "seasons").values())


def test_one_row_per_season_oldest_first(shipped: list[SeasonRules]) -> None:
    frame = cap_rules_frame(reversed(shipped))
    assert frame["season"].tolist() == ["2024-25", "2025-26", "2026-27"]


def test_frame_satisfies_the_contract(shipped: list[SeasonRules]) -> None:
    frame = cap_rules_frame(shipped)
    assert validate_frame(frame, SALARY_CAP_RULES) == []
    assert tuple(frame.columns) == SALARY_CAP_RULES.column_names


def test_figures_are_carried_over_exactly(shipped: list[SeasonRules]) -> None:
    frame = cap_rules_frame(shipped).set_index("season")
    for rules in shipped:
        row = frame.loc[rules.season]
        assert row["salary_cap"] == rules.thresholds.salary_cap
        assert row["second_apron"] == rules.thresholds.second_apron
        assert row["bi_annual"] == rules.exceptions.bi_annual
        assert row["max_salary_10_plus_years"] == rules.maximum_salaries.service_10_plus_years
        assert row["max_two_way_contracts"] == rules.roster.max_two_way_contracts
        assert row["rules_version"] == rules.version
        assert row["source_urls"].splitlines() == [source.url for source in rules.sources]


def test_optional_sections_become_nulls(shipped: list[SeasonRules]) -> None:
    bare = shipped[0].model_copy(update={"exceptions": None, "maximum_salaries": None})
    frame = cap_rules_frame([bare])
    optional = [
        "non_taxpayer_mid_level",
        "taxpayer_mid_level",
        "room_mid_level",
        "bi_annual",
        "max_salary_0_to_6_years",
        "max_salary_7_to_9_years",
        "max_salary_10_plus_years",
    ]
    assert frame[optional].isna().all().all()
    assert frame["salary_cap"].notna().all()


def test_no_seasons_gives_an_empty_conforming_frame() -> None:
    frame = cap_rules_frame([])
    assert len(frame) == 0
    assert tuple(frame.columns) == SALARY_CAP_RULES.column_names


def test_version_tracks_figures_but_not_citations(shipped: list[SeasonRules]) -> None:
    rules = shipped[-1]
    renoted = rules.model_copy(update={"notes": "edited", "sources": rules.sources[:1]})
    assert renoted.version == rules.version

    raised = rules.thresholds.model_copy(update={"second_apron": rules.thresholds.second_apron + 1})
    assert rules.model_copy(update={"thresholds": raised}).version != rules.version
    assert len({r.version for r in shipped}) == len(shipped)
