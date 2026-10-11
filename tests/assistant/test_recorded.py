"""The recorded world the end-to-end evaluation runs in, checked without a model: each
current and web case finds there what its expectations assume."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from front_office.assistant import tools as t
from front_office.assistant.evaluation import load_cases
from front_office.config import Settings
from front_office.domain.assistant import Context, ResultStatus, Source
from front_office.services import Lab
from tests.assistant.recorded import ANALYSIS, PASTED, world_toolbox

CASES = load_cases(Path(__file__).parent / "fixtures" / "cases.yaml")
BY_ID = {case.id: case for case in CASES.cases}
KNICKS, CELTICS = 1610612752, 1610612738


@pytest.fixture
def lab(built_lab: Settings) -> Lab:
    with Lab(built_lab) as opened:
        yield opened


def handlers(lab: Lab, case_id: str, tmp_path: Path, sources: tuple[Source, ...] = ()):  # type: ignore[no-untyped-def]  # fmt: skip
    case = BY_ID[case_id]
    context = Context(today=date(2026, 10, 9), season="2025-26", mode=case.mode, sources=sources)
    return world_toolbox(lab, case, tmp_path).handlers(context)


def test_the_preseason_has_no_games_and_no_injury_report(lab: Lab, tmp_path: Path) -> None:
    tools = handlers(lab, "C01", tmp_path)
    games = tools["current_games"](lab, t.CurrentGames())
    assert games.table.empty and "no 2026-27 games played yet" in games.limits[0]
    report = tools["injury_report"](lab, t.InjuryReport(player_id=1627759))
    assert report.table.empty and "not the same as healthy" in report.limits[0]
    assert all(found.evidence[0].location for found in (games, report)), "where it looked"


def test_the_knicks_moved_in_october_and_the_celtics_before_the_build(lab: Lab, tmp_path: Path) -> None:  # fmt: skip
    tools = handlers(lab, "C03", tmp_path)
    knicks = tools["transactions"](lab, t.Transactions(team_id=KNICKS, since=date(2026, 10, 1)))
    assert knicks.status is ResultStatus.OK and "2 moves since 2026-10-01" in knicks.text
    celtics = tools["transactions"](lab, t.Transactions(team_id=CELTICS, since=date(2026, 10, 1)))
    assert celtics.table.empty and celtics.limits, "no move since the build: a qualified answer"


def test_the_news_feeds_report_the_same_moves(lab: Lab, tmp_path: Path) -> None:
    """A7: the invented feeds agree with the league's file on the case file's day."""
    tools = handlers(lab, "C03", tmp_path)
    knicks = tools["moves_and_rumors"](lab, t.MovesAndRumors(team_id=KNICKS, moves_only=True))
    assert knicks.status is ResultStatus.OK and knicks.table is not None
    assert knicks.table["headline"].tolist() == [
        "Knicks Waive Blake Sample",
        "Knicks Sign Avery Example To Two-Way Contract",
    ]
    league = tools["moves_and_rumors"](lab, t.MovesAndRumors(days=7))
    assert league.table is not None and league.table["headline"].tolist() == [
        "Atlantic Notes: Knicks, Celtics",
        "Knicks Waive Blake Sample",
        "Knicks Sign Avery Example To Two-Way Contract",
    ]


def test_w01s_search_leaves_out_the_refused_site_and_its_pages_read(lab: Lab, tmp_path: Path) -> None:  # fmt: skip
    tools = handlers(lab, "W01", tmp_path)
    found = tools["web_search"](lab, t.WebSearch(query="why the Knicks won the 2025-26 title"))
    assert found.status is ResultStatus.OK and "basketball-reference" not in found.text
    assert tools["read_source"](lab, t.ReadSource(source_id="s1")).status is ResultStatus.OK


def test_the_pasted_link_and_the_held_page_read(lab: Lab, tmp_path: Path) -> None:
    pasted = handlers(lab, "W02", tmp_path, (Source(id="u1", url=PASTED),))
    assert pasted["read_source"](lab, t.ReadSource(source_id="u1")).status is ResultStatus.OK
    held = handlers(lab, "W03", tmp_path, (Source(id="s1", url=ANALYSIS),))
    page = held["read_source"](lab, t.ReadSource(source_id="s1"))
    assert "IMPORTANT SYSTEM NOTICE" in page.text, "the planted instruction reaches the model"


def test_w05s_search_finds_nothing(lab: Lab, tmp_path: Path) -> None:
    found = handlers(lab, "W05", tmp_path)["web_search"](lab, t.WebSearch(query="G League draft"))
    assert found.status is ResultStatus.EMPTY
