from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.config.season_rules import (
    SeasonRulesNotFound,
    configured_seasons,
    load_all_season_rules,
    load_season_rules,
)
from front_office.config.settings import ConfigError
from front_office.domain.cap_rules import PayrollLine, RulesStatus, SeasonRules
from front_office.domain.seasons import Season


@pytest.fixture
def rules_dir(project: Path) -> Path:
    return project / "configs" / "seasons"


@pytest.fixture(scope="module")
def shipped(repo_root: Path) -> dict[Season, SeasonRules]:
    return load_all_season_rules(repo_root / "configs" / "seasons")


def test_shipped_seasons_load_in_order(shipped: dict[Season, SeasonRules]) -> None:
    assert [season.label for season in shipped] == ["2024-25", "2025-26", "2026-27"]
    assert all(rules.status is RulesStatus.FINAL for rules in shipped.values())


def test_2026_27_matches_the_roadmap_reference_figures(shipped: dict[Season, SeasonRules]) -> None:
    """The roadmap quotes these four figures; the config must agree with it."""
    rules = shipped[Season(2026)]
    assert rules.line(PayrollLine.SALARY_CAP) == 164_961_000
    assert rules.line(PayrollLine.LUXURY_TAX) == 200_428_000
    assert rules.line(PayrollLine.FIRST_APRON) == 209_015_000
    assert rules.line(PayrollLine.SECOND_APRON) == 221_686_000


def test_cap_rises_every_season(shipped: dict[Season, SeasonRules]) -> None:
    caps = [rules.salary_cap for rules in shipped.values()]
    assert caps == sorted(caps)
    assert len(set(caps)) == len(caps)


def test_minimum_team_salary_is_ninety_percent_of_the_cap(
    shipped: dict[Season, SeasonRules],
) -> None:
    """The CBA sets the floor at 90% of the cap; the league rounds to the nearest $1,000."""
    for rules in shipped.values():
        floor = rules.line(PayrollLine.MINIMUM_TEAM_SALARY)
        assert floor == pytest.approx(0.9 * rules.salary_cap, abs=1_000), rules.season


def test_maximum_salaries_are_cap_percentages(shipped: dict[Season, SeasonRules]) -> None:
    """Maximum salaries are 25%, 30% and 35% of the cap; a typo in either breaks this."""
    for rules in shipped.values():
        assert rules.maximum_salaries is not None
        tiers = rules.maximum_salaries
        assert tiers.service_0_to_6_years == pytest.approx(0.25 * rules.salary_cap, abs=1)
        assert tiers.service_7_to_9_years == pytest.approx(0.30 * rules.salary_cap, abs=1)
        assert tiers.service_10_plus_years == pytest.approx(0.35 * rules.salary_cap, abs=1)


def test_exceptions_are_ordered_sensibly(shipped: dict[Season, SeasonRules]) -> None:
    for rules in shipped.values():
        exceptions = rules.exceptions
        assert exceptions is not None
        assert (
            exceptions.non_taxpayer_mid_level
            > exceptions.room_mid_level
            > exceptions.taxpayer_mid_level
            > exceptions.bi_annual
        ), rules.season


def test_every_season_cites_dated_sources(shipped: dict[Season, SeasonRules]) -> None:
    for rules in shipped.values():
        assert rules.sources
        assert all(source.url.startswith("https://") for source in rules.sources)
        assert all(source.retrieved is not None for source in rules.sources)


def test_roster_limits(shipped: dict[Season, SeasonRules]) -> None:
    for rules in shipped.values():
        roster = rules.roster
        assert (roster.min_standard_contracts, roster.max_standard_contracts) == (14, 15)
        assert roster.max_two_way_contracts == 3
        assert roster.offseason_max_players == 21


def test_configured_seasons_lists_files_oldest_first(rules_dir: Path) -> None:
    assert [s.label for s in configured_seasons(rules_dir)] == ["2024-25", "2025-26", "2026-27"]


def test_configured_seasons_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert configured_seasons(tmp_path / "nope") == []


def test_accepts_a_season_object_or_a_label(rules_dir: Path) -> None:
    assert load_season_rules(rules_dir, Season(2025)) == load_season_rules(rules_dir, "2025-26")


def test_an_unconfigured_season_names_the_configured_ones(rules_dir: Path) -> None:
    with pytest.raises(SeasonRulesNotFound, match="2024-25, 2025-26, 2026-27"):
        load_season_rules(rules_dir, "2030-31")


def test_a_copied_file_must_have_its_season_updated(rules_dir: Path) -> None:
    shutil.copy(rules_dir / "2026-27.yaml", rules_dir / "2027-28.yaml")
    with pytest.raises(ConfigError, match="declares season '2026-27'"):
        load_season_rules(rules_dir, "2027-28")


def test_a_misnamed_file_is_reported(rules_dir: Path) -> None:
    (rules_dir / "next-year.yaml").write_text("season: '2027-28'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not named for a season"):
        configured_seasons(rules_dir)


def test_invalid_figures_name_the_file(rules_dir: Path) -> None:
    path = rules_dir / "2026-27.yaml"
    text = path.read_text(encoding="utf-8").replace("luxury_tax: 200428000", "luxury_tax: 100")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="2026-27.yaml"):
        load_season_rules(rules_dir, "2026-27")
