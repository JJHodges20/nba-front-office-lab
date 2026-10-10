"""Current information since the build: games, transactions, the injury report.

Reads ``data/current.sqlite`` (decision 0018), which ``pipelines.current`` fills; nothing
here fetches. Rows are joined with the lab's names: a game is marked when the build already
holds it, and the injury report's team and player names - written as the league writes
them, "Last, First" - are matched to the lab's ids where exactly one matches. Reading never
creates the file: with nothing fetched yet, every table is empty and the status says so.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from front_office.config.assistant import load_assistant_settings
from front_office.domain.tables import CURRENT_TABLES
from front_office.domain.tables.current import SOURCES
from front_office.services.entities import fold
from front_office.services.lab import Lab
from front_office.storage.current import CurrentStore

_EMPTY = {contract.name: contract for contract in CURRENT_TABLES}
OK, STALE, FAILING, ABSENT = "ok", "stale", "failing", "absent"


@dataclass(frozen=True, slots=True)
class CurrentSource:
    """Where one current source stands."""

    source: str
    state: str
    checked_at: datetime | None
    """The last attempt to fetch it."""
    stored_at: datetime | None
    """The last attempt that worked: what is held was the source's as of then."""
    rows: int
    """Rows held."""
    detail: str
    url: str | None


class CurrentDataService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @contextmanager
    def _store(self) -> Iterator[CurrentStore | None]:
        path = self._lab.settings.current_path
        if not path.exists():
            yield None
            return
        with CurrentStore(path) as store:
            yield store

    def _read(self, table: str) -> pd.DataFrame:
        with self._store() as store:
            return _EMPTY[table].empty_frame() if store is None else store.read(table)

    def status(self, now: datetime | None = None) -> tuple[CurrentSource, ...]:
        moment = now or datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        limits = load_assistant_settings(self._lab.settings.config_dir).current
        with self._store() as store:
            log = pd.DataFrame() if store is None else store.refreshes()
            held = {source: 0 for source in SOURCES}
            if store is not None:
                held = {
                    "games": len(store.read("current_games")),
                    "transactions": len(store.read("transactions")),
                    "injuries": len(store.read("injury_reports")),
                }
        found = []
        for source in SOURCES:
            attempts = log[log["source"] == source] if not log.empty else log
            if attempts.empty:
                found.append(CurrentSource(source, ABSENT, None, None, 0, "Never fetched.", None))
                continue
            last = attempts.iloc[0]
            kept = attempts[attempts["status"].isin(["stored", "unchanged", "none"])]
            stored_at = (
                None if kept.empty else pd.Timestamp(kept.iloc[0]["attempted_at"]).to_pydatetime()
            )
            checked_at = pd.Timestamp(last["attempted_at"]).to_pydatetime()
            if last["status"] == "failed":
                state = FAILING
            elif stored_at is None or moment - stored_at > timedelta(
                minutes=limits.minutes(source)
            ):
                state = STALE
            else:
                state = OK
            found.append(
                CurrentSource(
                    source,
                    state,
                    checked_at,
                    stored_at,
                    held[source],
                    str(last["detail"]) if isinstance(last["detail"], str) else "",
                    last["url"] if isinstance(last["url"], str) else None,
                )
            )
        return tuple(found)

    def games(
        self, team_id: int | None = None, since: date | None = None, until: date | None = None
    ) -> pd.DataFrame:
        """The season in progress's games as last fetched, one row per team, newest first,
        with ``in_build`` for the games the lab's database already holds."""
        games = self._read("current_games")
        if team_id is not None:
            games = games[games["team_id"] == team_id]
        if since is not None:
            games = games[games["game_date"] >= pd.Timestamp(since)]
        if until is not None:
            games = games[games["game_date"] <= pd.Timestamp(until)]
        if games.empty:
            return games.assign(team="", opponent="", in_build=False)
        labels = self._lab.team_labels()["abbreviation"]
        built: set[str] = set()
        for season in games["season"].unique():
            built |= set(self._lab.read("team_games", {"season": season})["game_id"])
        games = games.assign(
            team=games["team_id"].map(labels),
            opponent=games["opponent_team_id"].map(labels),
            in_build=games["game_id"].isin(built),
        )
        return games.sort_values(["game_date", "game_id"], ascending=False).reset_index(drop=True)

    def transactions(
        self, team_id: int | None = None, player_id: int | None = None, since: date | None = None
    ) -> pd.DataFrame:
        """The league's moves as last fetched, newest first."""
        moves = self._read("transactions")
        if team_id is not None:
            moves = moves[moves["team_id"] == team_id]
        if player_id is not None:
            moves = moves[moves["player_id"] == player_id]
        if since is not None:
            moves = moves[moves["transaction_date"] >= pd.Timestamp(since)]
        labels = self._lab.team_labels()["abbreviation"]
        moves = moves.assign(team=moves["team_id"].map(labels))
        return moves.sort_values(
            ["transaction_date", "transaction_key"], ascending=False
        ).reset_index(drop=True)

    def injuries(self, team_id: int | None = None, player_id: int | None = None) -> pd.DataFrame:
        """The latest injury report fetched, with the lab's team and player ids where one
        name matches exactly one."""
        report = self._read("injury_reports")
        if report.empty:
            return report.assign(
                team_id=pd.Series(dtype="Int64"), player_id=pd.Series(dtype="Int64")
            )
        report = report[report["report_time"] == report["report_time"].max()]
        names = self._lab.team_labels()["full_name"]
        by_name = {fold(name): int(team) for team, name in names.items()}
        report = report.assign(
            team_id=report["team_name"].map(lambda name: by_name.get(fold(name)))
        )
        entities = self._lab.entities
        report = report.assign(
            player_id=report["player_name"].map(lambda name: _player(entities, name))
        )
        if team_id is not None:
            report = report[report["team_id"] == team_id]
        if player_id is not None:
            report = report[report["player_id"] == player_id]
        return report.reset_index(drop=True)


def _player(entities: object, written: object) -> int | None:
    """A report's "Last, First" as one of the lab's players, if exactly one has that name."""
    if not isinstance(written, str) or "," not in written:
        return None
    last, first = (part.strip() for part in written.split(",", 1))
    found = entities.find_players(f"{first} {last}")  # type: ignore[attr-defined]
    return int(found[0].id) if len(found) == 1 and found[0].match == "full name" else None
