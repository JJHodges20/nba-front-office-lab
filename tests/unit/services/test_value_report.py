"""The value model's write-up, generated from the fixture lab and the model the lab ships."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.config import load_settings, save_value_model, value_model_path
from front_office.services import Lab
from front_office.services.value_report import (
    NoValueModel,
    _listed,
    _roles,
    _signed,
    value_report,
)


@pytest.fixture(scope="module")
def report(lab: Lab) -> str:
    return value_report(lab)


def test_it_says_where_it_came_from_and_what_it_is(report: str, lab: Lab) -> None:
    model = lab.value.model()
    assert report.startswith("# What a Player Is Worth\n")
    assert f"from revision {model.revision} of the fitted model" in report
    assert f"(fitted {model.fitted_at:%Y-%m-%d}) and build 1" in report
    assert "> Everything here is an estimate." in report
    assert "no weight in it is the price of anything" in report
    assert report.endswith("\n") and "Out of date" not in report


def test_every_section_is_there_in_order(report: str) -> None:
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## What is estimated, and how",
        "## The test",
        "## What each part adds",
        "## The weights",
        "## From impact to wins",
        "## Projected minutes",
        "## Who it rates highest",
        "## The roles",
        "## What it cannot tell you",
    ]


def test_the_test_lists_the_model_first_then_every_simpler_method(report: str, lab: Lab) -> None:
    card = lab.value.card()
    tested = card.model.validation
    assert f"{tested.team_seasons} team-seasons, {tested.first_test_season} to" in report
    lines = report.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("| Method |"))
    rows = lines[start + 2 : start + 2 + len(card.baselines)]
    assert rows[0] == f"| **Value model** | {tested.net.rmse:.2f} | {tested.net.mae:.2f} |  |"
    assert len(rows) == 7 and all(row.startswith("| ") for row in rows)
    for row, baseline in zip(rows[1:], card.baselines.iloc[1:].itertuples(), strict=True):
        assert row.startswith(f"| {baseline.label} | {baseline.rmse:.2f} | {baseline.mae:.2f} | -")
        assert f"({baseline.low:+.2f} to {baseline.high:+.2f})" in row


def test_parts_that_cannot_be_told_from_nothing_are_named(report: str, lab: Lab) -> None:
    ablations = lab.value.card().ablations
    unsure = ablations.loc[~ablations["distinguishable"], "label"].tolist()
    assert unsure
    for label in unsure:
        assert f"| {label} |" in report
    assert report.count("| cannot be told |") == len(unsure)
    assert report.count("| yes |") == len(ablations) - len(unsure)
    assert "cannot be told from adding nothing on this evidence" in report


def test_every_weight_is_given_with_its_interval(report: str, lab: Lab) -> None:
    terms = lab.value.card().terms
    for row in terms.itertuples():
        assert f"| {row.label} | {row.group} | " in report, row.key
    assert report.count("| unclear |") == int((~terms["known"]).sum())
    # Nothing so small that it rounds away is shown as negative.
    assert "-0.00 (" not in report and "-0.00)" not in report and "-0.00 to" not in report
    new = terms.set_index("key").at["new_player", "net"]
    assert f"A player with no earlier season starts at {new:+.2f}." in report


def test_levels_and_minutes_are_stated_from_the_model(report: str, lab: Lab) -> None:
    model = lab.value.model()
    assert f"- **Replacement level is {model.replacement_level:+.2f}.**" in report
    same = model.validation.same_season
    assert f"is {same.slope:.2f} times the sum" in report
    assert f"(correlation {same.correlation:.2f})" in report
    minutes = model.availability
    assert f"Tested on {minutes.players:,} player-seasons: RMSE {minutes.rmse:.3f}" in report
    assert "A point of net rating has been worth" in report


def test_the_leaders_are_the_services(report: str, lab: Lab) -> None:
    season = lab.value.season("2025-26")
    best = season.iloc[0]
    assert "**2025-26, by wins above replacement**" in report
    assert (
        f"| {best['player_name']} | {best['team']} | {best['impact']:+.1f} | "
        f"{best['impact_offense']:+.1f} | {best['impact_defense']:+.1f} | "
        f"{best['minutes_share']:.0%} | {best['wins_added']:.1f} |"
    ) in report
    assert "**The 10 most valuable seasons on record**" in report
    projected = lab.value.projections().iloc[0]
    assert "**Projected for 2026-27**" in report
    assert f"| {projected['player_name']} | {projected['team']} | {projected['age']} |" in report


def test_the_roles_are_the_services(report: str, lab: Lab) -> None:
    summary = lab.value.role_summary("2025-26").set_index("archetype")
    assert "Archetypes are rules, not findings (`configs/archetypes.yaml`, version 1)" in report
    assert "| Role | Open to | Strong on, together | Fills from | Scored in 2025-26 |" in report
    first = summary.loc["primary_creator"]
    assert first["scored"] > first["filled"] > 0
    assert (
        f"| Primary Creator | Everyone | usage, assist percentage | 85 | {first['scored']} | "
        f"{first['filled']} | - | - |"
    ) in report
    assert "| Rim Protector | Big men | blocks, defensive impact | 67 |" in report
    # The fixture store has one season, so nothing carries over and the report says so.
    assert "With one season on record, nothing can be said about carrying over." in report


def test_which_roles_carry_over_is_read_off_the_record(value_lab: Lab) -> None:
    lines = _roles(value_lab, value_lab.value.status())
    summary = value_lab.value.role_summary(value_lab.value.status().seasons[0])
    ratio = summary["again"] / summary["anyone"]
    most, least = summary.loc[ratio.idxmax()], summary.loc[ratio.idxmin()]
    said = next(line for line in lines if line.startswith("The ") and "carries over most" in line)
    assert said.startswith(
        f"The {most['name'].lower()} carries over most ({most['again']:.0%} against "
        f"{most['anyone']:.0%}) and the {least['name'].lower()} least"
    )
    assert "nothing can be said" not in "\n".join(lines)
    assert all("| - |" not in line for line in lines if line.startswith("| ") and "---" not in line)


def test_it_says_what_it_cannot(report: str, lab: Lab) -> None:
    assert "- **Defense is the weak side.**" in report
    assert f"This revision knows seasons to {lab.value.model().fitted_on.last_season}." in report


@pytest.fixture
def copy(built_template, tmp_path: Path) -> Path:
    target = tmp_path / "copy"
    shutil.copytree(built_template[0], target)
    return target


def test_a_model_that_is_behind_the_data_or_ahead_of_the_build_is_flagged(copy: Path) -> None:
    settings = load_settings(copy)
    with Lab(settings) as opened:
        model = opened.value.model()
    older = model.fitted_on.model_copy(update={"last_season": "2024-25"})
    changed = model.model_copy(update={"revision": model.revision + 1, "fitted_on": older})
    save_value_model(settings.config_dir, changed)
    with Lab(settings) as opened:
        document = value_report(opened)
    assert (
        f"**Out of date.** The model on file is revision {changed.revision}; the values" in document
    )
    assert "fitted on seasons to 2024-25; 2025-26 finished since" in document


def test_without_a_model_there_is_nothing_to_report(copy: Path) -> None:
    settings = load_settings(copy)
    value_model_path(settings.config_dir).unlink()
    with Lab(settings) as opened, pytest.raises(NoValueModel, match="fol value fit --write"):
        value_report(opened)


def test_small_helpers() -> None:
    assert [_signed(value) for value in (0.004, -0.004, -0.006, 1.0)] == [
        "+0.00", "+0.00", "-0.01", "+1.00",
    ]  # fmt: skip
    assert _listed([]) == "" and _listed(["a"]) == "a"
    assert _listed(["a", "b"]) == "a and b" and _listed(["a", "b", "c"]) == "a, b and c"
