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
from tests.web_fakes import FakeWeb, Story, atom, page, robots, rss

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


# --- news (A7) -------------------------------------------------------------------------------

MAIN = "https://www.hoopsrumors.com/feed"
MOVES = "https://www.hoopsrumors.com/transactions/feed"
CELTICS = "https://www.hoopsrumors.com/boston-celtics/feed/atom"
EXTENSION = Story(
    "Celtics Sign Pritchard To Extension",
    "https://www.hoopsrumors.com/2026/10/celtics-pritchard-extension.html",
    START - timedelta(hours=3),
    ("Boston Celtics", "Transactions", "Payton Pritchard"),
)
NOTES = Story(
    "Celtics Notes: Tatum",
    "https://www.hoopsrumors.com/2026/10/celtics-notes.html",
    START - timedelta(days=2),
    ("Boston Celtics", "Jayson Tatum"),
)


def feeds(**overrides: object) -> FakeWeb:
    answers = {MAIN: rss(EXTENSION), MOVES: rss(EXTENSION), CELTICS: atom(EXTENSION, NOTES)}
    answers.update(overrides)  # type: ignore[arg-type]
    return FakeWeb(answers)


def news(settings: Settings, clock: Clock, web: FakeWeb, **kwargs):  # type: ignore[no-untyped-def]
    return refresh_current(settings, sources=["news"], now=clock, web=web.provider(), **kwargs)


def test_news_is_fetched_only_when_asked_for(settings: Settings) -> None:
    web = feeds()
    report = refresh(settings, Clock(), league_files(), web=web.provider())
    assert "news" not in statuses(report), "the league's own sources are the default"
    assert web.urls == []


def test_the_general_feeds_then_a_teams_own_each_article_once(settings: Settings) -> None:
    web, clock = feeds(), Clock()
    report = news(settings, clock, web)
    assert [(r.url, r.status, r.rows) for r in report.results] == [
        (MAIN, "stored", 1),
        (MOVES, "stored", 1),
    ]
    report = news(settings, clock, web, teams=["BOS"])
    assert [(r.url, r.status) for r in report.results] == [
        (MAIN, "skipped"),
        (MOVES, "skipped"),
        (CELTICS, "stored"),
    ]
    with CurrentStore(settings.current_path) as store:
        items = store.read("news_items").set_index("title")
        log = store.refreshes("news")
    assert len(items) == 2, "the extension came three times and is kept once"
    assert items.at[EXTENSION.title, "feeds"] == (
        "hoopsrumors; hoopsrumors-bos; hoopsrumors-transactions"
    )
    assert bool(items.at[EXTENSION.title, "transactions"])
    assert not bool(items.at[NOTES.title, "transactions"])
    assert len(log) == 3 and set(log["url"]) == {MAIN, MOVES, CELTICS}
    assert not settings.database_path.exists(), "reporting never touches the lab's database"


def test_a_feed_is_due_on_its_own_and_an_unchanged_one_says_so(settings: Settings) -> None:
    web, clock = feeds(), Clock()
    news(settings, clock, web)
    clock.moment += timedelta(minutes=31)
    report = news(settings, clock, web)
    assert {r.status for r in report.results} == {"unchanged"}
    assert {r.detail for r in report.results} == {
        "hoopsrumors: no new items",
        "hoopsrumors-transactions: no new items",
    }


def test_a_feed_that_fails_is_logged_and_what_was_held_stays(settings: Settings) -> None:
    clock = Clock()
    news(settings, clock, feeds())
    clock.moment += timedelta(hours=1)
    blocked = robots("User-agent: GPTBot\nDisallow: /\n")
    report = news(
        settings,
        clock,
        feeds(**{"https://www.hoopsrumors.com/robots.txt": blocked}),
    )
    assert {r.status for r in report.results} == {"failed"}
    assert all("robots.txt asks AI agents (GPTBot)" in r.detail for r in report.results)
    with CurrentStore(settings.current_path) as store:
        assert len(store.read("news_items")) == 1


def test_a_page_where_a_feed_should_be_is_a_failure(settings: Settings) -> None:
    report = news(settings, Clock(), feeds(**{MAIN: page("<html><p>Not a feed</p></html>")}))
    main, moves = report.results
    assert main.status == "failed" and "not an RSS or Atom feed" in main.detail
    assert moves.status == "stored"


def test_items_older_than_their_days_are_let_go(settings: Settings) -> None:
    old = Story("Summer notes", "https://www.hoopsrumors.com/2026/06/summer.html", START - timedelta(days=130))  # fmt: skip
    news(settings, Clock(), feeds(**{MAIN: rss(EXTENSION, old)}))
    with CurrentStore(settings.current_path) as store:
        assert store.read("news_items")["title"].tolist() == [EXTENSION.title]
