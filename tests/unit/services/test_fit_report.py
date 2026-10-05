"""Roster fit written up, generated from the fixture lab and the evidence the lab ships."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.config import fit_evidence_path, load_settings
from front_office.services import Lab
from front_office.services.fit_report import NoFitEvidence, fit_report


@pytest.fixture(scope="module")
def report(lab: Lab) -> str:
    return fit_report(lab)


def test_it_says_where_it_came_from_and_what_it_is(report: str) -> None:
    assert report.startswith("# Do These Players Make Sense Together?\n")
    assert "from revision 2 of the fit evidence (gathered " in report
    assert "> A roster's profile is description" in report
    assert report.endswith("\n") and "Out of date" not in report


def test_every_section_is_there_in_order(report: str) -> None:
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## What a roster is described by",
        "## How it was tested",
        "## Each measure alone",
        "## Every measure together",
        "## Where the champions' rosters stood",
        "## What it cannot tell you",
    ]


def test_the_measures_are_listed_by_area_and_the_test_described(report: str, lab: Lab) -> None:
    evidence = lab.fit.evidence()
    assert (
        "**Offense**" in report and "- *Floor spacers*: Players in the rotation who fill" in report
    )
    assert f"- {evidence.team_seasons} team-seasons, {evidence.first_test_season} to " in report
    assert f"missed by {evidence.baseline_rmse:.2f} points of net rating (RMSE)" in report
    assert "27 of the 32 measures were tested" in report


def test_each_measure_and_the_verdict_are_the_evidences(report: str, lab: Lab) -> None:
    evidence = lab.fit.evidence()
    first = evidence.measures[0]
    assert (
        f"| {first.name} | {first.area} | {first.coefficient:+.2f} ({first.coefficient_low:+.2f} "
        f"to {first.coefficient_high:+.2f}) | {first.rmse:.2f} |"
    ) in report
    combined = evidence.combined
    assert (
        f"| With every measure | {combined.rmse:.2f} | {combined.change.difference:+.2f} ("
        in report
    )
    if combined.is_usable:
        assert "**The correction is applied to rosters.**" in report
    else:
        assert "**No correction is applied to rosters.**" in report
    for item in combined.ablations:
        assert f"| {item.label} | {item.rmse:.2f} |" in report


def test_the_champions_are_the_services(report: str, lab: Lab) -> None:
    champions = lab.fit.champions()
    assert "## Where the champions' rosters stood" in report
    row = champions.iloc[0]
    assert (
        f"| {row['name']} | {row['area']} | {row['median_percentile']:.0f} | {row['top_third']} | {row['bottom_third']} |"
        in report
    )


@pytest.fixture
def copy(built_template, tmp_path: Path) -> Path:  # type: ignore[no-untyped-def]
    target = tmp_path / "copy"
    shutil.copytree(built_template[0], target)
    return target


def test_without_evidence_there_is_nothing_to_report(copy: Path) -> None:
    fit_evidence_path(copy / "configs").unlink()
    with (
        Lab(load_settings(copy)) as opened,
        pytest.raises(NoFitEvidence, match="fol fit test --write"),
    ):
        fit_report(opened)


def test_evidence_from_another_model_is_flagged(copy: Path) -> None:
    path = fit_evidence_path(copy / "configs")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"archetype_version": "v1"', '"archetype_version": "v7"'
        ),
        encoding="utf-8",
    )
    with Lab(load_settings(copy)) as opened:
        document = fit_report(opened)
    assert (
        "> **Out of date.** The evidence was gathered against value model r2 and roles v7"
        in document
    )
