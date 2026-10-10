"""Refreshing current information: what is due, logged, and nothing else touched."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from front_office.config import Settings
from front_office.domain.datasets import NBA_STATS
from front_office.pipelines.current import refresh_current
from front_office.providers.nba_current import (
    PLAYER_MOVEMENT_URL,
    CurrentProvider,
    CurrentSourceError,
)
from front_office.rawstore import RawStore
from front_office.storage.current import CurrentStore
from tests.current_fakes import FakeGet, FakeStats, fixture_game_logs, league_files

START = datetime(2026, 10, 21, 21, 50)
"""Naive UTC, as the pipeline keeps time: 5:50 PM Eastern on a game day of 2026-27."""


class Clock:
    def __init__(self, moment: datetime = START) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def refresh(settings: Settings, clock: Clock, get: FakeGet, stats: FakeStats | None = None, **kwargs):  # type: ignore[no-untyped-def]  # fmt: skip
    provider = CurrentProvider(
        get=get, now=lambda: clock.moment.replace(tzinfo=UTC), sleep=lambda _: None
    )
    return refresh_current(
        settings, now=clock, provider=provider, stats=stats or FakeStats(), **kwargs
    )


def statuses(report) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {result.source: result.status for result in report.results}


def test_a_first_refresh_stores_each_source_and_logs_it(settings: Settings) -> None:
    report = refresh(settings, Clock(), league_files())
    assert statuses(report) == {"games": "none", "transactions": "stored", "injuries": "stored"}
    with CurrentStore(settings.current_path) as store:
        assert len(store.read("transactions")) == 3
        assert len(store.read("injury_reports")) == 6
        log = store.refreshes()
    assert sorted(log["source"]) == ["games", "injuries", "transactions"]
    assert not settings.database_path.exists(), "a refresh never touches the lab's database"


def test_before_its_interval_a_source_is_not_fetched_again(settings: Settings) -> None:
    clock, get = Clock(), league_files()
    refresh(settings, clock, get)
    asked = len(get.urls)
    clock.moment += timedelta(minutes=20)
    report = refresh(settings, clock, get)
    assert set(statuses(report).values()) == {"skipped"}
    assert len(get.urls) == asked
    clock.moment += timedelta(minutes=15)  # injuries are due after 30 minutes
    assert statuses(refresh(settings, clock, get))["injuries"] == "stored"


def test_force_fetches_and_a_file_that_has_not_changed_says_so(settings: Settings) -> None:
    clock, get = Clock(), league_files()
    refresh(settings, clock, get, sources=["transactions"])
    report = refresh(settings, clock, get, sources=["transactions"], force=True)
    (result,) = report.results
    assert (result.status, result.rows) == ("unchanged", 3)


def test_a_failure_is_logged_and_the_last_copy_stays(settings: Settings) -> None:
    clock = Clock()
    refresh(settings, clock, league_files(), sources=["transactions"])
    broken = FakeGet(
        {PLAYER_MOVEMENT_URL: CurrentSourceError("stats.nba.com could not be reached")}
    )
    report = refresh(settings, clock, broken, sources=["transactions"], force=True)
    assert [r.status for r in report.failed] == ["failed"]
    with CurrentStore(settings.current_path) as store:
        assert len(store.read("transactions")) == 3
        assert store.refreshes("transactions")["status"].tolist() == ["failed", "stored"]


def test_no_report_published_keeps_the_last_one(settings: Settings) -> None:
    clock = Clock()
    refresh(settings, clock, league_files(), sources=["injuries"])
    clock.moment += timedelta(hours=3)
    report = refresh(settings, clock, league_files(report=None), sources=["injuries"])
    (result,) = report.results
    assert result.status == "none" and "the last one fetched stays" in result.detail
    with CurrentStore(settings.current_path) as store:
        assert len(store.read("injury_reports")) == 6


def test_games_of_the_season_in_progress_are_stored_and_snapshotted(settings: Settings) -> None:
    stats = FakeStats({"regular": fixture_game_logs("regular", 3)})
    report = refresh(settings, Clock(), league_files(), stats, sources=["games"])
    (result,) = report.results
    assert (result.status, result.rows) == ("stored", 6)
    assert result.detail == "3 games of 2026-27 so far"
    assert {call["season_type"] for call in stats.calls} == {"regular", "playin", "playoffs"}
    with CurrentStore(settings.current_path) as store:
        games = store.read("current_games")
    assert set(games["season"]) == {"2026-27"} and games["game_id"].nunique() == 3
    raw = RawStore(settings.raw_dir)
    held = raw.latest(NBA_STATS, "team_game_logs", {"season": "2026-27", "season_type": "regular"})
    assert held is not None, "the next build finds the games in the raw store"


def test_games_that_cannot_be_fetched_are_a_failure(settings: Settings) -> None:
    report = refresh(settings, Clock(), league_files(), FakeStats(fail=True), sources=["games"])
    (result,) = report.results
    assert result.status == "failed" and "could not be fetched" in result.detail


def test_an_unknown_source_is_refused(settings: Settings) -> None:
    with pytest.raises(ValueError, match="no current source"):
        refresh(settings, Clock(), league_files(), sources=["rumours"])
