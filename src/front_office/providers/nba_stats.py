"""stats.nba.com adapter.

Fetches one dataset per call through the community ``nba_api`` client and returns the
response unchanged as a :class:`Snapshot`. Nothing here renames, filters or interprets
the data.

stats.nba.com is an undocumented public endpoint with no service guarantee, so the
adapter is polite and patient: requests are spaced out and transient failures are
retried with a growing pause.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import requests

from front_office.domain.datasets import NBA_STATS, NbaStatsDataset, partition_for
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.snapshots import Snapshot

LEAGUE_ID = "00"
"""stats.nba.com's id for the NBA (as opposed to the WNBA or G League)."""

_SEASON_TYPE_NAMES = {
    SeasonType.REGULAR: "Regular Season",
    SeasonType.PLAYOFFS: "Playoffs",
    SeasonType.PLAY_IN: "PlayIn",
}


class ProviderError(RuntimeError):
    """The source could not be reached or returned something unusable."""


class Transport(Protocol):
    """Performs one endpoint call and returns the decoded JSON response."""

    def __call__(self, endpoint: str, parameters: Mapping[str, Any], timeout: float) -> Any: ...


def nba_api_transport(endpoint: str, parameters: Mapping[str, Any], timeout: float) -> Any:
    """Call a stats.nba.com endpoint through ``nba_api``."""
    from nba_api.stats import endpoints

    return getattr(endpoints, endpoint)(**parameters, timeout=timeout).get_dict()


def _league_dash(endpoint: str, measure: str, **extra: Any) -> Callable[..., tuple[str, dict]]:
    def build(season: Season, season_type: SeasonType, team_id: int | None) -> tuple[str, dict]:
        return endpoint, {
            "season": season.label,
            "season_type_all_star": _SEASON_TYPE_NAMES[season_type],
            "per_mode_detailed": "Totals",
            "measure_type_detailed_defense": measure,
            "league_id_nullable": LEAGUE_ID,
            **extra,
        }

    return build


def _game_log(player_or_team: str) -> Callable[..., tuple[str, dict]]:
    def build(season: Season, season_type: SeasonType, team_id: int | None) -> tuple[str, dict]:
        return "LeagueGameLog", {
            "season": season.label,
            "season_type_all_star": _SEASON_TYPE_NAMES[season_type],
            "player_or_team_abbreviation": player_or_team,
            "league_id": LEAGUE_ID,
        }

    return build


def _team_years(season: Season | None, season_type: Any, team_id: Any) -> tuple[str, dict]:
    return "CommonTeamYears", {"league_id": LEAGUE_ID}


def _player_index(season: Season | None, season_type: Any, team_id: Any) -> tuple[str, dict]:
    if season is None:
        raise ValueError("player_index needs the current season as a reference point")
    return "PlayerIndex", {
        "season": season.label,
        "league_id": LEAGUE_ID,
        "historical_nullable": 1,
    }


def _standings(season: Season, season_type: Any, team_id: Any) -> tuple[str, dict]:
    return "LeagueStandingsV3", {
        "season": season.label,
        "season_type": _SEASON_TYPE_NAMES[SeasonType.REGULAR],
        "league_id": LEAGUE_ID,
    }


def _team_roster(season: Season, season_type: Any, team_id: int) -> tuple[str, dict]:
    return "CommonTeamRoster", {"team_id": team_id, "season": season.label}


def _team_on_off(season: Season, season_type: SeasonType, team_id: int) -> tuple[str, dict]:
    return "TeamPlayerOnOffSummary", {
        "team_id": team_id,
        "season": season.label,
        "season_type_all_star": _SEASON_TYPE_NAMES[season_type],
        "per_mode_detailed": "Totals",
        "measure_type_detailed_defense": "Advanced",
    }


_REQUESTS: dict[NbaStatsDataset, Callable[..., tuple[str, dict]]] = {
    NbaStatsDataset.TEAM_YEARS: _team_years,
    NbaStatsDataset.PLAYER_INDEX: _player_index,
    NbaStatsDataset.STANDINGS: _standings,
    NbaStatsDataset.TEAM_SEASON_BASE: _league_dash("LeagueDashTeamStats", "Base"),
    NbaStatsDataset.TEAM_SEASON_ADVANCED: _league_dash("LeagueDashTeamStats", "Advanced"),
    NbaStatsDataset.TEAM_SEASON_OPPONENT: _league_dash("LeagueDashTeamStats", "Opponent"),
    NbaStatsDataset.TEAM_GAME_LOGS: _game_log("T"),
    NbaStatsDataset.PLAYER_SEASON_BASE: _league_dash("LeagueDashPlayerStats", "Base"),
    NbaStatsDataset.PLAYER_SEASON_ADVANCED: _league_dash("LeagueDashPlayerStats", "Advanced"),
    NbaStatsDataset.PLAYER_SEASON_STARTERS: _league_dash(
        "LeagueDashPlayerStats", "Base", starter_bench_nullable="Starters"
    ),
    NbaStatsDataset.PLAYER_GAME_LOGS: _game_log("P"),
    NbaStatsDataset.TEAM_ROSTER: _team_roster,
    NbaStatsDataset.TEAM_ON_OFF: _team_on_off,
}


class NbaStatsProvider:
    """Retrieves stats.nba.com datasets as raw snapshots."""

    source = NBA_STATS

    def __init__(
        self,
        *,
        timeout: float = 45.0,
        min_interval: float = 1.2,
        max_retries: int = 3,
        backoff: float = 4.0,
        transport: Transport = nba_api_transport,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._timeout = timeout
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._backoff = backoff
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
        self._last_request: float | None = None

    def fetch(
        self,
        dataset: NbaStatsDataset,
        *,
        season: Season | None = None,
        season_type: SeasonType | None = None,
        team_id: int | None = None,
        reference_season: Season | None = None,
    ) -> Snapshot:
        """Fetch one dataset.

        ``reference_season`` is only for datasets that are not partitioned by season but
        whose endpoint still wants one (the all-time player index).
        """
        partition = partition_for(dataset, season=season, season_type=season_type, team_id=team_id)
        endpoint, parameters = _REQUESTS[dataset](season or reference_season, season_type, team_id)
        payload = self._call(endpoint, parameters)
        return Snapshot(
            source=self.source,
            dataset=dataset.value,
            partition=partition,
            fetched_at=self._now(),
            payload=payload,
            request={"endpoint": endpoint, "parameters": parameters},
        )

    def _call(self, endpoint: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        attempts = self._max_retries + 1
        failure: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._wait_for_turn()
            try:
                payload = self._transport(endpoint, parameters, self._timeout)
            # A timeout, a dropped connection, or an error page where JSON was expected
            # (ValueError from decoding, KeyError from nba_api reading it) may all pass.
            except (requests.RequestException, ValueError, KeyError) as error:
                failure = error
                if attempt < attempts:
                    self._sleep(self._backoff * attempt)
                continue
            if not _looks_like_stats_response(payload):
                raise ProviderError(
                    f"{endpoint} returned an unexpected response shape: {_summarise(payload)}"
                )
            return payload
        raise ProviderError(
            f"{endpoint} failed after {attempts} attempt(s): {type(failure).__name__}: {failure}"
        ) from failure

    def _wait_for_turn(self) -> None:
        current = self._monotonic()
        if self._last_request is not None:
            remaining = self._min_interval - (current - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
                current = self._monotonic()
        self._last_request = current


def _looks_like_stats_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    result_sets = payload.get("resultSets", payload.get("resultSet"))
    return isinstance(result_sets, list | dict)


def _summarise(payload: Any) -> str:
    if isinstance(payload, dict):
        return f"object with keys {sorted(payload)[:8]}"
    return type(payload).__name__
