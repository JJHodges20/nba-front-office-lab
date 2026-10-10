"""The league's player-movement file and injury report, fetched as published."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from front_office.providers.nba_current import (
    INJURY_REPORT_BASE,
    PLAYER_MOVEMENT_URL,
    USER_AGENT,
    CurrentProvider,
    CurrentSourceError,
    report_names,
    stats_headers,
)
from tests.current_fakes import REPORT, REPORT_NAME, REPORT_PUBLISHED, FakeGet, league_files

LATER = datetime(2026, 10, 21, 21, 50, tzinfo=UTC)
"""5:50 PM Eastern: the 5:30 report is the latest, two quarter hours back."""


def provider(get: FakeGet, *, now: datetime = LATER, slots: int = 4) -> tuple[CurrentProvider, list[float]]:  # fmt: skip
    pauses: list[float] = []
    return CurrentProvider(get=get, now=lambda: now, sleep=pauses.append, slots=slots), pauses


def test_the_movement_file_is_fetched_as_the_ingest_fetches_its_host() -> None:
    get = league_files()
    fetched, _ = provider(get)
    result = fetched.player_movement()
    assert result.url == PLAYER_MOVEMENT_URL
    assert result.content.startswith(b'{"NBA_Player_Movement"')
    assert get.requests[0][1] == stats_headers()
    assert result.retrieved_at == LATER.replace(tzinfo=None)


def test_a_movement_file_that_is_not_there_is_an_error() -> None:
    fetched, _ = provider(FakeGet())
    with pytest.raises(CurrentSourceError, match="answered 404"):
        fetched.player_movement()


def test_the_latest_report_is_found_by_its_name_going_back_a_quarter_hour_at_a_time() -> None:
    get = league_files()
    fetched, pauses = provider(get)
    report = fetched.injury_report()
    assert report is not None
    assert report.url == INJURY_REPORT_BASE + REPORT_NAME
    assert report.content == REPORT
    assert report.published_at == REPORT_PUBLISHED.replace(tzinfo=None)
    assert [url.rsplit("/", 1)[-1] for url in get.urls] == [
        "Injury-Report_2026-10-21_05_45PM.pdf",
        "Injury-Report_2026-10-21_05_30PM.pdf",
    ]
    assert all(headers == {"User-Agent": USER_AGENT} for _, headers in get.requests)
    assert pauses == [1.0], "one request a second"


def test_no_report_in_the_slots_looked_at_is_none() -> None:
    get = league_files(report=None)
    fetched, _ = provider(get, slots=2)
    assert fetched.injury_report() is None
    assert len(get.urls) == 2


def test_a_host_that_answers_otherwise_is_an_error() -> None:
    url = INJURY_REPORT_BASE + "Injury-Report_2026-10-21_05_45PM.pdf"
    fetched, _ = provider(FakeGet({url: (500, b"")}))
    with pytest.raises(CurrentSourceError, match="answered 500"):
        fetched.injury_report()


def test_a_file_that_is_not_a_pdf_is_an_error_not_a_missing_report() -> None:
    url = INJURY_REPORT_BASE + "Injury-Report_2026-10-21_05_45PM.pdf"
    fetched, _ = provider(FakeGet({url: (200, b"<html>Not found</html>")}), slots=1)
    with pytest.raises(CurrentSourceError, match="not a PDF"):
        fetched.injury_report()


def test_on_the_hour_the_older_hourly_name_is_tried_too() -> None:
    moment = datetime(2026, 10, 21, 17, 0)
    assert report_names(moment) == [
        "Injury-Report_2026-10-21_05_00PM.pdf",
        "Injury-Report_2026-10-21_05PM.pdf",
    ]
    assert report_names(datetime(2026, 10, 21, 9, 15)) == ["Injury-Report_2026-10-21_09_15AM.pdf"]
