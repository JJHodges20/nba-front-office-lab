"""The postseason model written up, generated from the fixture lab and the model the lab ships."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.config import load_settings, postseason_model_path
from front_office.services import Lab
from front_office.services.postseason_report import NoPostseasonModel, postseason_report


@pytest.fixture(scope="module")
def report(lab: Lab) -> str:
    return postseason_report(lab)


def test_it_says_where_it_came_from_and_what_it_is(report: str, lab: Lab) -> None:
    model = lab.postseason.model()
    assert report.startswith("# How Far Can a Team Go?\n")
    assert (
        f"from revision {model.revision} of the model (fitted {model.fitted_at:%Y-%m-%d}) "
        "and build 1"
    ) in report
    assert "> Every figure here is an estimate with an interval" in report
    assert report.endswith("\n") and "Out of date" not in report


def test_every_section_is_there_in_order(report: str) -> None:
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## What the model is",
        "## How it was tested",
        "## The series model",
        "## The bracket, out of sample",
        "## The season model",
        "## What this does not say",
    ]


def test_the_figures_are_the_models(report: str, lab: Lab) -> None:
    model = lab.postseason.model()
    game, tested = model.game, model.evaluation.series
    assert (
        f"| Home advantage (log-odds) | {game.home_advantage:+.3f} | {game.home_low:+.3f} to "
        f"{game.home_high:+.3f} |"
    ) in report
    assert (
        f"On {tested.series} series, {tested.first_test_season} to {tested.last_test_season}"
        in report
    )
    assert f"| The model | {tested.log_loss:.4f} | {tested.brier:.4f} |" in report
    for item in tested.comparisons:
        assert f"| {item.label} | {item.log_loss:.4f} | {item.brier:.4f} |" in report
    bracket = model.evaluation.bracket
    assert f"won {bracket.favourite_won} of {len(bracket.favourites)} postseasons" in report
    for item in model.evaluation.season.stages:
        assert f"| {item.log_loss:.4f} | {item.brier:.4f} |" in report


def test_the_season_model_is_read_at_several_ratings(report: str, lab: Lab) -> None:
    outlook = lab.postseason.outlook(5.0)
    chances = outlook.stages.set_index("key")
    assert (
        f"| +5 | {outlook.top_players:+.2f} | {chances.at['made_playoffs', 'probability']:.1%} ("
    ) in report


def test_the_favourites_are_named(report: str, lab: Lab) -> None:
    names = lab.team_labels()["full_name"]
    item = lab.postseason.model().evaluation.bracket.favourites[-1]
    assert (
        f"| {item.season} | {names.get(item.favourite_team_id)} | {item.favourite_probability:.1%} "
        f"| {names.get(item.champion_team_id)} | {item.champion_probability:.1%} |"
    ) in report


@pytest.fixture
def copy(built_template, tmp_path: Path) -> Path:  # type: ignore[no-untyped-def]
    target = tmp_path / "copy"
    shutil.copytree(built_template[0], target)
    return target


def test_without_a_model_there_is_nothing_to_report(copy: Path) -> None:
    postseason_model_path(copy / "configs").unlink()
    with (
        Lab(load_settings(copy)) as opened,
        pytest.raises(NoPostseasonModel, match="fol playoffs fit --write"),
    ):
        postseason_report(opened)


def test_a_model_from_another_value_model_is_flagged(copy: Path) -> None:
    path = postseason_model_path(copy / "configs")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"value_model_version": "r2"', '"value_model_version": "r9"'
        ),
        encoding="utf-8",
    )
    with Lab(load_settings(copy)) as opened:
        document = postseason_report(opened)
    assert (
        "> **Out of date.** The model was fitted with top-player quality from value model r9"
        in document
    )
