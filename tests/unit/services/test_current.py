"""Current information as the services read it: where each source stands, and its rows
joined to the lab's names."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from front_office.config import Settings
from front_office.pipelines.current import refresh_current
from front_office.providers.nba_current import CurrentProvider
from front_office.services import Lab
from front_office.storage.current import CurrentStore
from tests.current_fakes import FakeGet, FakeStats, fixture_game_logs, league_files
from tests.helpers import BOS, BROWN, HART, NYK, TATUM
from tests.web_fakes import FakeWeb, Story, atom, rss

GAME_DAY = datetime(2026, 10, 21, 21, 50)


def fill(settings: Settings, moment: datetime = GAME_DAY, get: FakeGet | None = None, **logs: dict) -> None:  # fmt: skip
    """Refresh every source from the fakes, as at ``moment`` (naive UTC)."""
    provider = CurrentProvider(
        get=get or league_files(), now=lambda: moment.replace(tzinfo=UTC), sleep=lambda _: None
    )
    refresh_current(settings, now=lambda: moment, provider=provider, stats=FakeStats(logs))


def test_reading_before_anything_is_fetched_creates_nothing(built_lab: Settings) -> None:
    with Lab(built_lab) as lab:
        sources = lab.current.status()
        games = lab.current.games()
        report = lab.current.injuries()
    assert [(s.source, s.state, s.rows) for s in sources] == [
        ("games", "absent", 0),
        ("transactions", "absent", 0),
        ("injuries", "absent", 0),
        ("news", "absent", 0),
    ]
    assert games.empty and {"team", "opponent", "in_build"} <= set(games.columns)
    assert report.empty
    assert not built_lab.current_path.exists()


def test_a_source_is_ok_within_its_interval_then_stale_and_failing_after_a_failure(
    built_lab: Settings,
) -> None:
    fill(built_lab)
    with Lab(built_lab) as lab:
        fresh = {s.source: s for s in lab.current.status(now=GAME_DAY + timedelta(minutes=20))}
        later = {s.source: s for s in lab.current.status(now=GAME_DAY + timedelta(minutes=45))}
    assert fresh["injuries"].state == "ok" and fresh["injuries"].rows == 6
    assert fresh["injuries"].stored_at == GAME_DAY
    assert later["injuries"].state == "stale", "injuries are due again after 30 minutes"
    assert later["transactions"].state == "ok", "transactions after three hours"
    with CurrentStore(built_lab.current_path) as store:
        store.record(
            {
                "source": "transactions",
                "attempted_at": GAME_DAY + timedelta(hours=4),
                "status": "failed",
                "detail": "timed out",
            }  # fmt: skip
        )
    with Lab(built_lab) as lab:
        moves = next(s for s in lab.current.status() if s.source == "transactions")
    assert (moves.state, moves.detail, moves.stored_at) == ("failing", "timed out", GAME_DAY)


def test_games_are_named_and_marked_when_the_build_holds_them(built_lab: Settings) -> None:
    # In the 2025-26 league year the fixture's own snapshots are the season in progress.
    fill(built_lab, datetime(2026, 4, 1, 12))
    with Lab(built_lab) as lab:
        celtics = lab.current.games(team_id=BOS)
        april = lab.current.games(since=date(2026, 4, 1), until=date(2026, 4, 3))
    assert len(celtics) > 80 and celtics["in_build"].all()
    assert set(celtics["team"]) == {"BOS"}
    assert celtics["game_date"].is_monotonic_decreasing
    assert april["game_date"].between(pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-03")).all()


def test_games_newer_than_the_build_are_not_marked(built_lab: Settings) -> None:
    fill(built_lab, GAME_DAY, regular=fixture_game_logs("regular", 2))
    with Lab(built_lab) as lab:
        games = lab.current.games()
    assert len(games) == 4 and not games["in_build"].any()
    assert set(games["season"]) == {"2026-27"}


def test_moves_newest_first_by_team_player_and_date(built_lab: Settings) -> None:
    fill(built_lab)
    with Lab(built_lab) as lab:
        knicks = lab.current.transactions(team_id=NYK)
        brown = lab.current.transactions(player_id=BROWN)
        recent = lab.current.transactions(since=date(2026, 10, 3))
    assert knicks["transaction_type"].tolist() == ["Waive", "Signing"]
    assert set(knicks["team"]) == {"NYK"}
    assert len(brown) == 1 and len(recent) == 1


def test_the_report_names_are_matched_to_the_labs_ids(built_lab: Settings) -> None:
    fill(built_lab)
    with Lab(built_lab) as lab:
        report = lab.current.injuries()
        celtics = lab.current.injuries(team_id=BOS)
        hart = lab.current.injuries(player_id=HART)
    assert report.set_index("player_name")["player_id"].dropna().to_dict() == {
        "Brown, Jaylen": BROWN,
        "Tatum, Jayson": TATUM,
        "Hart, Josh": HART,
    }
    assert celtics["player_name"].tolist() == ["Brown, Jaylen", "Tatum, Jayson"]
    assert hart["status"].tolist() == ["Available"]
    unmatched = report[report["team_name"] == "Milwaukee Bucks"]
    assert unmatched["player_id"].isna().all(), "a name the lab does not hold gets no id"


# --- news (A7) -------------------------------------------------------------------------------

EXTENSION = Story(
    "Celtics Sign Pritchard To Extension",
    "https://www.hoopsrumors.com/2026/10/pritchard.html",
    GAME_DAY - timedelta(hours=3),
    ("Boston Celtics", "Transactions", "Payton Pritchard"),
)
TATUM_NOTE = Story(
    "Injury Notes: Tatum Ahead Of Schedule",
    "https://www.hoopsrumors.com/2026/10/tatum.html",
    GAME_DAY - timedelta(days=2),
    ("Jayson Tatum",),
)
KNICKS = Story(
    "Knicks Pause Extension Talks With Josh Hart",
    "https://www.hoopsrumors.com/2026/10/hart.html",
    GAME_DAY - timedelta(days=5),
    ("New York Knicks", "Josh Hart"),
)
BROWN_NOTE = Story(
    "Atlantic Notes: Brown, Embiid",
    "https://www.hoopsrumors.com/2026/09/atlantic.html",
    GAME_DAY - timedelta(days=20),
    ("Jaylen Brown (Player)", "Philadelphia 76ers"),
)


def fill_news(settings: Settings) -> None:
    web = FakeWeb(
        {
            "https://www.hoopsrumors.com/feed": rss(EXTENSION, KNICKS),
            "https://www.hoopsrumors.com/transactions/feed": rss(EXTENSION),
            "https://www.hoopsrumors.com/boston-celtics/feed/atom": atom(TATUM_NOTE, BROWN_NOTE),
        }
    )
    refresh_current(
        settings, sources=["news"], teams=["BOS"], now=lambda: GAME_DAY, web=web.provider()
    )


def test_news_for_a_team_is_its_feed_its_tags_and_its_headlines(built_lab: Settings) -> None:
    fill_news(built_lab)
    with Lab(built_lab) as lab:
        celtics = lab.current.news(team_id=BOS)["title"].tolist()
        knicks = lab.current.news(team_id=NYK)["title"].tolist()
        status = {s.source: s for s in lab.current.status(now=GAME_DAY)}["news"]
    assert celtics == [EXTENSION.title, TATUM_NOTE.title, BROWN_NOTE.title], "newest first"
    assert knicks == [KNICKS.title]
    assert (status.state, status.rows) == ("ok", 4)


def test_news_for_a_player_is_what_the_site_tagged_with_their_name(built_lab: Settings) -> None:
    fill_news(built_lab)
    with Lab(built_lab) as lab:
        assert lab.current.news(player_id=TATUM)["title"].tolist() == [TATUM_NOTE.title]
        assert lab.current.news(player_id=BROWN)["title"].tolist() == [BROWN_NOTE.title]
        assert lab.current.news(player_id=HART)["title"].tolist() == [KNICKS.title]


def test_news_since_a_day_and_moves_alone(built_lab: Settings) -> None:
    fill_news(built_lab)
    with Lab(built_lab) as lab:
        week = lab.current.news(since=GAME_DAY - timedelta(days=7))
        moves = lab.current.news(moves_only=True)
    assert week["title"].tolist() == [EXTENSION.title, TATUM_NOTE.title, KNICKS.title]
    assert moves["title"].tolist() == [EXTENSION.title]
