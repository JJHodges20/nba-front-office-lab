"""Build the test fixtures: a miniature raw store cut from real stats.nba.com responses.

Run from the project root after ``fol ingest``:

    .venv\\Scripts\\python.exe scripts\\make_fixtures.py

The fixture store (``tests/fixtures/raw``) has the same layout as the real one, so tests
exercise the same code paths as production. It holds:

* 1996-97, team level - the oldest season: sequential playoff game ids, best-of-five
  first rounds, and the one team-season whose published totals are fractional.
* 2012-13, team level - the season with a scheduled game that was never played.
* 2025-26, team level in full, and player level for everyone who appeared for two teams.
* 2026-27, the league year before any game: empty statistics, current rosters.

Team-level datasets are kept whole. Player-level datasets are cut down to the chosen
players so the fixtures stay small; every remaining row is exactly as the source sent it.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from front_office.config import load_settings
from front_office.domain.datasets import NBA_STATS, NbaStatsDataset, partition_for
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.snapshots import Snapshot
from front_office.rawstore import RawStore

D = NbaStatsDataset
REGULAR, PLAYOFFS, PLAY_IN = SeasonType.REGULAR, SeasonType.PLAYOFFS, SeasonType.PLAY_IN

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "raw"
TEAM_ONLY_SEASONS = (Season(1996), Season(2012))
PLAYER_SEASON = Season(2025)
UNSTARTED_SEASON = Season(2026)
PLAYER_TEAMS = (1610612738, 1610612752)  # Boston Celtics, New York Knicks
EXTRA_INDEX_ROWS = 25  # a few retired players, so the index is not only current ones

RowFilter = Callable[[dict], bool]


def main() -> int:
    source = RawStore(load_settings().raw_dir)
    if FIXTURE_ROOT.exists():
        shutil.rmtree(FIXTURE_ROOT)
    target = RawStore(FIXTURE_ROOT)

    def fetch(dataset: D, season=None, season_type=None, team_id=None) -> Snapshot:
        partition = partition_for(dataset, season=season, season_type=season_type, team_id=team_id)
        snapshot = source.latest(NBA_STATS, dataset.value, partition)
        if snapshot is None:
            raise SystemExit(f"missing from the raw store: {dataset.value} {partition}")
        return snapshot

    def copy(snapshot: Snapshot, keep: RowFilter | None = None, note: str | None = None) -> None:
        payload = snapshot.payload if keep is None else filter_rows(snapshot.payload, keep)
        request = dict(snapshot.request)
        if note:
            request["fixture"] = note
        target.save(
            Snapshot(
                snapshot.source,
                snapshot.dataset,
                snapshot.partition,
                snapshot.fetched_at,
                payload,
                request,
            )
        )

    def team_level(season: Season, *, play_in: bool) -> None:
        copy(fetch(D.STANDINGS, season))
        for dataset in (D.TEAM_SEASON_BASE, D.TEAM_SEASON_ADVANCED, D.TEAM_SEASON_OPPONENT):
            copy(fetch(dataset, season, REGULAR))
        copy(fetch(D.TEAM_GAME_LOGS, season, REGULAR))
        copy(fetch(D.TEAM_GAME_LOGS, season, PLAYOFFS))
        if play_in:
            copy(fetch(D.TEAM_GAME_LOGS, season, PLAY_IN))

    copy(fetch(D.TEAM_YEARS))
    for season in TEAM_ONLY_SEASONS:
        team_level(season, play_in=False)
    team_level(PLAYER_SEASON, play_in=True)
    team_level(UNSTARTED_SEASON, play_in=True)

    # Everyone who appeared for the chosen teams, in either the regular season or playoffs.
    players: set[int] = set()
    for season_type in (REGULAR, PLAYOFFS):
        for row in rows_of(fetch(D.PLAYER_GAME_LOGS, PLAYER_SEASON, season_type).payload):
            if row["TEAM_ID"] in PLAYER_TEAMS:
                players.add(row["PLAYER_ID"])
    note = f"rows kept for the {len(players)} players who appeared for teams {PLAYER_TEAMS}"

    for season_type in (REGULAR, PLAYOFFS):
        for dataset in (
            D.PLAYER_SEASON_BASE,
            D.PLAYER_SEASON_ADVANCED,
            D.PLAYER_SEASON_STARTERS,
            D.PLAYER_GAME_LOGS,
        ):
            copy(
                fetch(dataset, PLAYER_SEASON, season_type),
                lambda row: row["PLAYER_ID"] in players,
                note,
            )

    rostered: set[int] = set()
    for season in (PLAYER_SEASON, UNSTARTED_SEASON):
        for team_id in PLAYER_TEAMS:
            roster = fetch(D.TEAM_ROSTER, season, team_id=team_id)
            copy(roster)
            rostered.update(row["PLAYER_ID"] for row in rows_of(roster.payload))
    for team_id in PLAYER_TEAMS:
        copy(fetch(D.TEAM_ON_OFF, PLAYER_SEASON, REGULAR, team_id))

    wanted = players | rostered
    index = fetch(D.PLAYER_INDEX)
    retired = [row["PERSON_ID"] for row in rows_of(index.payload) if row["ROSTER_STATUS"] is None]
    wanted.update(retired[:EXTRA_INDEX_ROWS])
    # Everyone the on/off data mentions must be findable too.
    for team_id in PLAYER_TEAMS:
        on_off = fetch(D.TEAM_ON_OFF, PLAYER_SEASON, REGULAR, team_id).payload
        for result_set in on_off["resultSets"][1:]:
            position = result_set["headers"].index("VS_PLAYER_ID")
            wanted.update(row[position] for row in result_set["rowSet"])
    copy(
        index,
        lambda row: row["PERSON_ID"] in wanted,
        f"rows kept for {len(wanted)} players: the fixture's players plus a few retired ones",
    )

    size = sum(path.stat().st_size for path in FIXTURE_ROOT.rglob("*.json.gz"))
    count = sum(1 for _ in FIXTURE_ROOT.rglob("*.json.gz"))
    print(f"wrote {count} snapshots, {size / 1024:.0f} KB, to {FIXTURE_ROOT}")
    return 0


def rows_of(payload: dict) -> list[dict]:
    result_set = payload["resultSets"][0]
    return [dict(zip(result_set["headers"], row, strict=True)) for row in result_set["rowSet"]]


def filter_rows(payload: dict, keep: RowFilter) -> dict:
    """The payload with only the first result set's matching rows; everything else as it was."""
    first, *rest = payload["resultSets"]
    headers = first["headers"]
    rows = [row for row in first["rowSet"] if keep(dict(zip(headers, row, strict=True)))]
    return {**payload, "resultSets": [{**first, "rowSet": rows}, *rest]}


if __name__ == "__main__":
    sys.exit(main())
