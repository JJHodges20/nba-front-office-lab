"""The research write-up, generated from the fixture lab's three seasons."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.analytics.benchmarks import STAGE_KEYS
from front_office.services import Lab
from front_office.services.benchmark_report import (
    _floor_remark,
    _range,
    _share,
    benchmark_report,
)


@pytest.fixture(scope="module")
def report(lab: Lab) -> str:
    return benchmark_report(lab)


def rates(champions_by_band: dict[str, tuple[float, int, int]]) -> pd.DataFrame:
    """Stage rates for champions only: band -> (lower edge, teams, champions)."""
    rows = [
        {"band": band, "lower": lower, "teams": teams, "stage": "won_championship",
         "reached": reached}
        for band, (lower, teams, reached) in champions_by_band.items()
    ]  # fmt: skip
    return pd.DataFrame(rows, columns=["band", "lower", "teams", "stage", "reached"])


def test_it_says_where_it_came_from_and_what_it_is_not(report: str) -> None:
    assert report.startswith("# What Contenders Have Looked Like\n")
    assert "`fol benchmarks --write` from build 1 of 2026-10-01" in report
    assert "It is not a forecast for any team." in report
    assert report.endswith("\n")


def test_every_section_is_there_in_order(report: str) -> None:
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Seasons covered",
        "## How to read it",
        "## How far teams went: by record",
        "## How far teams went: by net rating",
        "## How far teams went: by seed",
        "## What the teams at each stage looked like",
        "## What separates them",
        "## The eras side by side",
        "## What this cannot say",
    ]


def test_coverage_lists_every_era_as_it_falls_on_the_data(report: str) -> None:
    assert "| All seasons | 1996-97 to 2025-26 (3) | 89 | 52 | 48 | 24 | 12 | 6 | 3 |" in report
    # Only one fixture season is recent enough for the two eras with a first season.
    assert "| Modern era | 2025-26 (1) | 30 | 20 | 16 | 8 | 4 | 2 | 1 |" in report
    assert "| Play-In era | 2025-26 (1) | 30 | 20 | 16 | 8 | 4 | 2 | 1 |" in report
    assert "- **Modern era.** A convention, not a fact" in report


def test_remarks_are_drawn_from_the_data(report: str) -> None:
    assert "No champion came from below the *50 to 55* band." in report
    assert "All 3 champions were seeded 3 or better in their conference." in report
    assert "In 2 of this era's conference standings the league leaves teams" in report


def test_champions_are_profiled_with_named_teams(report: str) -> None:
    assert (
        "| Wins per 82 games | Won the championship | 3 | 53.0 (2025-26 New York Knicks) "
        "| 55.6 | 66.0 | 68.4 | 69.0 (1996-97 Chicago Bulls) |" in report
    )
    assert "| Won the championship | 3 | 1 of 3 | 2 of 3 | 3 of 3 | 3 of 3 |" in report


def test_each_comparison_states_its_field_and_its_size(report: str) -> None:
    assert "### Teams that made the playoffs, against every other team" in report
    assert "48 teams against 41, in 3 seasons (656 same-season pairs)." in report
    assert (
        "### Teams that won a playoff series, against teams that made the playoffs and "
        "went no further" in report
    )
    assert "24 teams against 24, in 3 seasons (192 same-season pairs)." in report
    assert "### Teams that won the championship, against every other team" in report


def test_the_eras_are_set_side_by_side(report: str) -> None:
    assert "| All seasons | 3 | 53.0 (2025-26 New York Knicks) | 66.0 |" in report
    assert "| Modern era | 1 | 53.0 (2025-26 New York Knicks) | 53.0 |" in report


def test_it_states_its_limits(report: str) -> None:
    for limit in (
        "It is description, not prediction.",
        "One metric at a time.",
        "Nothing on payroll.",
        "Few champions.",
    ):
        assert f"**{limit}**" in report


def test_nothing_is_left_unformatted(report: str) -> None:
    for leak in ("nan", "None", "NaT", "<NA>", "{", "}"):
        assert leak not in report, leak
    assert "\r" not in report


def test_every_table_row_has_as_many_cells_as_its_header(report: str) -> None:
    header: int | None = None
    tables = 0
    for line in report.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = line.count("|")
        if header is None:
            header, tables = cells, tables + 1
        assert cells == header, line
    assert tables >= 10


def test_the_report_is_the_same_every_time(lab: Lab, report: str) -> None:
    assert benchmark_report(lab) == report


def test_every_stage_appears_in_the_coverage_header(report: str) -> None:
    header = next(line for line in report.splitlines() if line.startswith("| Era | Seasons"))
    assert header.count("|") == 3 + len(STAGE_KEYS) + 1


def test_a_share_that_does_not_exist_is_a_dash_not_a_number() -> None:
    nothing = float("nan")
    assert _share(nothing) == "-" and _range(nothing, nothing) == "-"
    assert _range(0.1, nothing) == "-"
    assert _share(0.289) == "29%" and _share(0.0061, digits=1) == "0.6%"
    assert _range(0.0234, 0.1041) == "2% to 10%"


class TestFloorRemark:
    def test_the_teams_below_the_lowest_champion_are_counted(self) -> None:
        remark = _floor_remark(
            rates({"40 to 45": (40, 100, 0), "45 to 50": (45, 50, 0), "50 to 55": (50, 20, 2)}),
            "wins per 82 games",
        )[0]
        assert remark.startswith("No champion came from below the *50 to 55* band.")
        assert "The 150 teams in the bands beneath it won no title" in remark
        assert "up to 2.5%" in remark  # Wilson's upper end for 0 of 150
        assert "rather than impossible" in remark

    def test_no_champion_at_all(self) -> None:
        remark = _floor_remark(rates({"40 to 45": (40, 30, 0)}), "wins per 82 games")
        assert remark == ["No team in this era won a championship."]

    def test_a_champion_in_the_lowest_band(self) -> None:
        remark = _floor_remark(
            rates({"50 to 55": (50, 10, 1), "55 to 60": (55, 5, 1)}), "wins per 82 games"
        )
        assert remark == ["The lowest band of wins per 82 games already holds a champion."]
