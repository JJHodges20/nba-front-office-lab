"""Current information the league publishes: transactions and the injury report.

Fetched as published and returned unchanged (decision 0018). The player-movement file sits
on stats.nba.com and is fetched the way the lab's existing ingest fetches that host, with
nba_api's headers (docs/DATA_SOURCE_REGISTER.md). The injury report is one PDF per
publication, fetched under the lab's own name; the page that lists them loads its links by
script, so the latest report is found by its published file name - the last few quarter
hours, one request a second. A missing file is a report not published, not an error.
Completed games are not here: they come through the stats.nba.com provider.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

PLAYER_MOVEMENT_URL = "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"
INJURY_REPORT_BASE = "https://ak-static.cms.nba.com/referee/injury/"
USER_AGENT = "NBAFrontOfficeLab/0.1 (personal research; local)"
EASTERN = ZoneInfo("America/New_York")
SLOT_MINUTES = 15
NOT_THERE = (403, 404)
"""How the file host answers for a report that was never published."""


class CurrentSourceError(RuntimeError):
    """A source could not be reached, or answered with something unusable."""


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    content: bytes
    retrieved_at: datetime
    """When it was fetched, UTC without a zone marker."""
    published_at: datetime | None = None
    """When the source says it was published, UTC without a zone marker."""


Get = Callable[[str, Mapping[str, str], float], tuple[int, bytes]]


def requests_get(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
    try:
        response = requests.get(url, headers=dict(headers), timeout=timeout)
    except requests.RequestException as error:
        raise CurrentSourceError(f"{url} could not be reached: {error}") from error
    return response.status_code, response.content


def stats_headers() -> dict[str, str]:
    """The headers the lab's stats.nba.com ingest sends, through nba_api."""
    from nba_api.stats.library.http import STATS_HEADERS

    return dict(STATS_HEADERS)


def report_names(moment: datetime) -> list[str]:
    """The file names a report published at ``moment`` (Eastern time) may have: a
    quarter-hour name, and for the hour the older hourly one."""
    day, hour, half = moment.strftime("%Y-%m-%d"), moment.strftime("%I"), moment.strftime("%p")
    names = [f"Injury-Report_{day}_{hour}_{moment:%M}{half}.pdf"]
    if moment.minute == 0:
        names.append(f"Injury-Report_{day}_{hour}{half}.pdf")
    return names


class CurrentProvider:
    def __init__(
        self,
        *,
        get: Get = requests_get,
        timeout: float = 30.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        pause: float = 1.0,
        slots: int = 4,
    ) -> None:
        self._get_url = get
        self._timeout = timeout
        self._now = now
        self._sleep = sleep
        self._pause = pause
        self._slots = slots
        self._last: float | None = None

    def player_movement(self) -> Fetched:
        status, content = self._get(PLAYER_MOVEMENT_URL, stats_headers())
        if status != 200:
            raise CurrentSourceError(f"the player-movement file answered {status}")
        return Fetched(PLAYER_MOVEMENT_URL, content, _utc(self._now()))

    def injury_report(self) -> Fetched | None:
        """The latest report published in the last ``slots`` quarter hours, if any."""
        local = self._now().astimezone(EASTERN)
        slot = local.replace(
            minute=local.minute - local.minute % SLOT_MINUTES, second=0, microsecond=0
        )
        for step in range(self._slots):
            moment = slot - timedelta(minutes=SLOT_MINUTES * step)
            for name in report_names(moment):
                url = INJURY_REPORT_BASE + name
                status, content = self._get(url, {"User-Agent": USER_AGENT})
                if status == 200 and content.startswith(b"%PDF"):
                    return Fetched(url, content, _utc(self._now()), _utc(moment))
                if status == 200:
                    raise CurrentSourceError(
                        f"the injury report host sent {name} as something not a PDF"
                    )
                if status not in NOT_THERE:
                    raise CurrentSourceError(f"the injury report host answered {status} for {name}")
        return None

    def _get(self, url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        if self._last is not None:
            self._sleep(self._pause)
        self._last = 1.0
        return self._get_url(url, headers, self._timeout)


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)
