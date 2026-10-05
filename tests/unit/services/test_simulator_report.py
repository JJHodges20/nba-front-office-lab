"""The simulator written up, generated from the fixture lab and the files the lab ships."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.config import load_settings, simulator_model_path
from front_office.services import Lab
from front_office.services.simulator_report import NoSimulatorModel, simulator_report


@pytest.fixture(scope="module")
def report(lab: Lab) -> str:
    return simulator_report(lab)


def test_it_says_where_it_came_from_and_what_it_is(report: str, lab: Lab) -> None:
    model = lab.simulator.model()
    assert report.startswith("# What a Season Could Bring\n")
    assert (
        f"from revision {model.revision} of the simulator's parameters (measured "
        f"{model.fitted_at:%Y-%m-%d}) and build 1"
    ) in report
    assert "> Every figure here is an estimate with an interval." in report
    assert report.endswith("\n") and "Out of date" not in report


def test_every_section_is_there_in_order(report: str) -> None:
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## What a season is drawn from",
        "## What was measured",
        "## The wins test",
        "## The season ahead, as drawn: 2026-27",
        "## What this does not say",
    ]


def test_the_figures_are_the_models(report: str, lab: Lab) -> None:
    model = lab.simulator.model()
    assert f"| The value model's miss | {model.value_error:.2f} |" in report
    assert f"| A season's own noise | {model.season_noise:.2f} |" in report
    assert f"| Wins per point of net rating | {model.wins_per_point:.2f} |" in report
    for band in model.development:
        assert (
            f"| {band.lower:.2f} to {band.upper:.2f} | {band.players:,} | {band.mean_miss:+.2f} | "
            f"{band.spread:.2f} |"
        ) in report
    for item in model.test.coverage:
        assert f"| {item.level:.0%} | {item.share:.1%} | {item.cases} |" in report
    assert f"missed the wins that happened by {model.test.mae:.1f} wins" in report


def test_the_season_ahead_lists_every_team_drawn(report: str, lab: Lab) -> None:
    league = lab.simulator.league()
    for _, row in league.iterrows():
        assert f"| {row['team_name']} | {row['players']} | {row['projected']} | " in report
    assert "| Boston Celtics |" in report


@pytest.fixture
def copy(built_template, tmp_path: Path) -> Path:  # type: ignore[no-untyped-def]
    target = tmp_path / "copy"
    shutil.copytree(built_template[0], target)
    return target


def test_without_parameters_there_is_nothing_to_report(copy: Path) -> None:
    simulator_model_path(copy / "configs").unlink()
    with (
        Lab(load_settings(copy)) as opened,
        pytest.raises(NoSimulatorModel, match="fol simulate fit --write"),
    ):
        simulator_report(opened)


def test_parameters_from_another_value_model_are_flagged(copy: Path) -> None:
    path = simulator_model_path(copy / "configs")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"value_model_version": "r1"', '"value_model_version": "r9"'
        ),
        encoding="utf-8",
    )
    with Lab(load_settings(copy)) as opened:
        document = simulator_report(opened)
    assert "> **Out of date.** The parameters were measured against value model r9" in document
