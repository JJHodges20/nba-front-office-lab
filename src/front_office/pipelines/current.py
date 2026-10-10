"""Refreshing current information: games, transactions, the injury report (decision 0018).

For each source asked for whose last attempt is older than its interval
(``configs/assistant.yaml``), or every one when forced:

- **games**: the season in progress's league game logs through the stats.nba.com ingest -
  their snapshots go to the raw store, where the next build finds them - then the lab's
  own box-score normaliser, into ``current_games``;
- **transactions**: the league's player-movement file, into ``transactions``, unless it
  has not changed since the last time;
- **injuries**: the latest official report of the last hour or so, into
  ``injury_reports``; when none was published the last one stays.

Every attempt is logged in ``data/current.sqlite``, failures included, and a failure leaves
what was cached in place. Nothing here touches the lab's database or refits anything.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd

from front_office.config.assistant import load_assistant_settings
from front_office.config.settings import Settings
from front_office.domain.datasets import NBA_STATS, NbaStatsDataset
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.tables.current import SOURCES
from front_office.pipelines.build import utc_now
from front_office.pipelines.ingest import (
    FIRST_PLAY_IN_SEASON,
    FetchRequest,
    FetchStatus,
    Ingestor,
    RefreshPolicy,
    SnapshotProvider,
)
from front_office.processing.current import CurrentPayloadError, injury_frame, transactions_frame
from front_office.processing.nba_stats.resultsets import PayloadError
from front_office.processing.nba_stats.teams import build_team_games
from front_office.providers.nba_current import (
    INJURY_REPORT_BASE,
    SLOT_MINUTES,
    CurrentProvider,
    CurrentSourceError,
)
from front_office.providers.nba_stats import NbaStatsProvider, ProviderError
from front_office.rawstore import RawStore
from front_office.storage.current import CurrentStore

FAILURES = (
    CurrentSourceError,
    CurrentPayloadError,
    ProviderError,
    PayloadError,
    json.JSONDecodeError,
)


@dataclass(frozen=True, slots=True)
class SourceRefresh:
    source: str
    status: str
    """stored, unchanged, none, failed - or skipped, when it was fetched recently."""
    rows: int | None
    detail: str
    url: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentRefresh:
    results: tuple[SourceRefresh, ...]

    @property
    def failed(self) -> tuple[SourceRefresh, ...]:
        return tuple(result for result in self.results if result.status == "failed")


def refresh_current(
    settings: Settings,
    *,
    sources: Sequence[str] = SOURCES,
    force: bool = False,
    now: Callable[[], datetime] = utc_now,
    provider: CurrentProvider | None = None,
    stats: SnapshotProvider | None = None,
) -> CurrentRefresh:
    """Fetch what is due of ``sources`` into ``data/current.sqlite``."""
    unknown = sorted(set(sources) - set(SOURCES))
    if unknown:
        raise ValueError(f"no current source called {unknown}; the sources are {SOURCES}")
    limits = load_assistant_settings(settings.config_dir).current
    provider = provider or CurrentProvider(slots=limits.injury_slots)
    results = []
    with CurrentStore(settings.current_path) as store:
        for source in sources:
            moment = now()
            minutes = limits.minutes(source)
            if not force and not _due(store, source, minutes, moment):
                results.append(
                    SourceRefresh(source, "skipped", None, f"fetched in the last {minutes} minutes")
                )
                continue
            try:
                if source == "games":
                    result = _games(settings, store, moment, minutes, stats)
                elif source == "transactions":
                    result = _transactions(store, provider)
                else:
                    result = _injuries(store, provider, limits.injury_slots)
            except FAILURES as error:
                result = SourceRefresh(source, "failed", None, str(error))
            store.record(
                {
                    "source": source,
                    "attempted_at": moment,
                    "status": result.status,
                    "rows": result.rows,
                    "detail": result.detail,
                    "url": result.url,
                    "content_hash": result.content_hash,
                }
            )
            results.append(result)
    return CurrentRefresh(tuple(results))


def _due(store: CurrentStore, source: str, minutes: int, moment: datetime) -> bool:
    attempts = store.refreshes(source)
    if attempts.empty:
        return True
    last = pd.Timestamp(attempts.iloc[0]["attempted_at"]).to_pydatetime()
    return moment - last >= timedelta(minutes=minutes)


def _games(
    settings: Settings,
    store: CurrentStore,
    moment: datetime,
    minutes: int,
    stats: SnapshotProvider | None,
) -> SourceRefresh:
    season = Season.league_year_on(moment.date())
    phases = [SeasonType.REGULAR, SeasonType.PLAYOFFS]
    if season >= FIRST_PLAY_IN_SEASON:
        phases.insert(1, SeasonType.PLAY_IN)
    requests = [FetchRequest(NbaStatsDataset.TEAM_GAME_LOGS, season, phase) for phase in phases]
    if stats is None:
        nba = settings.providers.nba_stats
        stats = NbaStatsProvider(
            timeout=nba.timeout_seconds,
            min_interval=nba.min_interval_seconds,
            max_retries=nba.max_retries,
            backoff=nba.backoff_seconds,
        )
    raw = RawStore(settings.raw_dir)
    policy = RefreshPolicy(refresh_after=timedelta(minutes=minutes))
    ingestor = Ingestor(stats, raw, policy, now=lambda: moment.replace(tzinfo=UTC))
    outcomes = ingestor.run(requests)
    failed = [outcome for outcome in outcomes if outcome.status is FetchStatus.FAILED]
    held = [raw.latest(NBA_STATS, request.dataset.value, request.partition) for request in requests]
    snapshots = [snapshot for snapshot in held if snapshot is not None]
    if failed and not snapshots:
        raise ProviderError(f"the {season.label} game logs could not be fetched: {failed[0].error}")
    frame = build_team_games(snapshots)
    rows = store.replace("current_games", frame)
    detail = (
        f"{rows // 2} games of {season.label} so far"
        if rows
        else f"no {season.label} games played yet"
    )
    if failed:
        detail += (
            f"; {len(failed)} of {len(requests)} phases could not be fetched, the last copies kept"
        )
    return SourceRefresh(
        "games", "stored" if rows else "none", rows, detail, "stats.nba.com LeagueGameLog"
    )


def _transactions(store: CurrentStore, provider: CurrentProvider) -> SourceRefresh:
    fetched = provider.player_movement()
    digest = hashlib.sha256(fetched.content).hexdigest()[:20]
    previous = store.refreshes("transactions")
    stored = previous[previous["status"].isin(["stored", "unchanged"])]
    if not stored.empty and stored.iloc[0]["content_hash"] == digest:
        rows = len(store.read("transactions"))
        return SourceRefresh(
            "transactions", "unchanged", rows, "the file has not changed", fetched.url, digest
        )
    notes: list[str] = []
    frame = transactions_frame(json.loads(fetched.content), fetched.retrieved_at, notes)
    rows = store.replace("transactions", frame)
    newest = frame["transaction_date"].max() if rows else None
    detail = f"{rows} lines, the newest of {newest:%Y-%m-%d}" if newest is not None else "no lines"
    if notes:
        detail += "; " + "; ".join(notes)
    return SourceRefresh("transactions", "stored", rows, detail, fetched.url, digest)


def _injuries(store: CurrentStore, provider: CurrentProvider, slots: int) -> SourceRefresh:
    fetched = provider.injury_report()
    if fetched is None:
        held = len(store.read("injury_reports"))
        kept = "the last one fetched stays" if held else "none is held"
        return SourceRefresh(
            "injuries",
            "none",
            None,
            f"no report published in the last {slots * SLOT_MINUTES} minutes; {kept}",
            INJURY_REPORT_BASE,
        )
    assert fetched.published_at is not None
    frame = injury_frame(
        fetched.content,
        report_time=fetched.published_at,
        url=fetched.url,
        retrieved_at=fetched.retrieved_at,
    )
    rows = store.replace("injury_reports", frame)
    digest = hashlib.sha256(fetched.content).hexdigest()[:20]
    return SourceRefresh("injuries", "stored", rows, f"{rows} lines", fetched.url, digest)
