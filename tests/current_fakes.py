"""Made-up current information and fakes of its sources, for tests.

The league's player-movement file and injury report are drawn here rather than recorded:
the report may not be redistributed, and neither is needed whole to test what the lab
does with it. Game logs are the fixture store's real 2025-26 responses, moved into a
season still to be played.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from front_office.domain.datasets import NBA_STATS, NbaStatsDataset, partition_for
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.snapshots import Snapshot
from front_office.providers.nba_current import INJURY_REPORT_BASE, PLAYER_MOVEMENT_URL
from front_office.providers.nba_stats import ProviderError
from tests.helpers import BROWN, NYK
from tests.injury_pdf import SAMPLE, SAMPLE_CARRIED, report_pdf

FETCHED = datetime(2026, 10, 9, 15, 0)
FIXTURE_LOGS = Path(__file__).parent / "fixtures" / "raw" / "nba_stats" / "team_game_logs"


def movement(*rows: dict) -> dict:
    return {"NBA_Player_Movement": {"columns": [], "rows": list(rows)}}


def move(**fields: object) -> dict:
    """One line of the player-movement file, as the league writes it: ids as decimals."""
    row = {
        "Transaction_Type": "Signing",
        "TRANSACTION_DATE": "2026-10-02T00:00:00",
        "TRANSACTION_DESCRIPTION": "New York Knicks signed guard Jaylen Brown.",
        "TEAM_ID": float(NYK),
        "PLAYER_ID": float(BROWN),
        "GroupSort": "Signing 1",
    }
    return {**row, **fields}


MOVES = movement(
    move(),
    move(
        Transaction_Type="Waive",
        TRANSACTION_DATE="2026-10-05T00:00:00",
        TRANSACTION_DESCRIPTION="New York Knicks waived center Sam Doe.",
        PLAYER_ID=1999999.0,
        GroupSort="Waive 1",
    ),
    move(
        Transaction_Type="Signing",
        TRANSACTION_DATE="2025-07-10T00:00:00",
        TRANSACTION_DESCRIPTION="Boston Celtics signed forward Pat Roe.",
        TEAM_ID=1610612738.0,
        PLAYER_ID=1888888.0,
        GroupSort="Signing 2",
    ),
)
REPORT = report_pdf(SAMPLE, carried_over=SAMPLE_CARRIED)
REPORT_NAME = "Injury-Report_2026-10-21_05_30PM.pdf"


class FakeGet:
    """Answers each address with a status and a body; anything else is a 404. Keeps every
    request with its headers."""

    def __init__(self, answers: Mapping[str, tuple[int, bytes] | Exception] | None = None) -> None:
        self.answers = dict(answers or {})
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        self.requests.append((url, dict(headers)))
        answer = self.answers.get(url, (404, b""))
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def urls(self) -> list[str]:
        return [url for url, _ in self.requests]


def league_files(*, moves: dict = MOVES, report: bytes | None = REPORT) -> FakeGet:
    """The player-movement file, and one injury report published at 5:30 PM Eastern on
    2026-10-21."""
    answers: dict[str, tuple[int, bytes] | Exception] = {
        PLAYER_MOVEMENT_URL: (200, json.dumps(moves).encode())
    }
    if report is not None:
        answers[INJURY_REPORT_BASE + REPORT_NAME] = (200, report)
    return FakeGet(answers)


REPORT_PUBLISHED = datetime(2026, 10, 21, 21, 30, tzinfo=UTC)
"""5:30 PM Eastern (daylight time) on 2026-10-21, in UTC."""


def fixture_game_logs(season_type: str, games: int) -> dict[str, Any]:
    """The first ``games`` games of the fixture's real 2025-26 logs for a phase, as a
    payload of the 2026-27 season: new game ids, the same box scores."""
    (path,) = (FIXTURE_LOGS / "season=2025-26" / f"season_type={season_type}").glob("*.json.gz")
    payload = json.loads(gzip.decompress(path.read_bytes()))["payload"]
    result = payload["resultSets"][0]
    headers = result["headers"]
    game, season = headers.index("GAME_ID"), headers.index("SEASON_ID")
    kept: list[list] = []
    chosen: list[str] = []
    for row in result["rowSet"]:
        if row[game] not in chosen:
            if len(chosen) == games:
                continue
            chosen.append(row[game])
        moved = list(row)
        moved[game] = "00226" + str(row[game])[5:]
        moved[season] = str(row[season])[:1] + "2026"
        kept.append(moved)
    parameters = {**payload["parameters"], "Season": "2026-27"}
    return {**payload, "parameters": parameters, "resultSets": [{**result, "rowSet": kept}]}


class FakeStats:
    """A stats.nba.com provider that serves game logs, by phase; a phase it has none for
    answers as the league does before a season - the headers and no rows."""

    def __init__(
        self,
        logs: Mapping[str, dict] | None = None,
        *,
        fail: bool = False,
        clock: Callable[[], datetime] = lambda: datetime(2026, 11, 1, 12, tzinfo=UTC),
    ) -> None:
        self.logs = dict(logs or {})
        self.fail = fail
        self.clock = clock
        self.calls: list[dict[str, str]] = []

    def fetch(
        self,
        dataset: NbaStatsDataset,
        *,
        season: Season | None = None,
        season_type: SeasonType | None = None,
        team_id: int | None = None,
        reference_season: Season | None = None,
    ) -> Snapshot:
        partition = partition_for(dataset, season=season, season_type=season_type, team_id=team_id)
        self.calls.append(partition)
        if self.fail:
            raise ProviderError("stats.nba.com timed out")
        phase = season_type.value if season_type else ""
        payload = self.logs.get(phase) or fixture_game_logs(phase, 0)
        return Snapshot(NBA_STATS, dataset.value, partition, self.clock(), payload)
