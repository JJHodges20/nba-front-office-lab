from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import requests

from front_office.domain.datasets import DATASET_SPECS, NbaStatsDataset
from front_office.domain.seasons import Season, SeasonType
from front_office.providers.nba_stats import _REQUESTS, NbaStatsProvider, ProviderError
from tests.helpers import stats_payload

D = NbaStatsDataset
SEASON = Season(2025)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
PAYLOAD = stats_payload(["TEAM_ID"], [[1610612738]])


class Clock:
    """A fake monotonic clock that only advances when the provider sleeps."""

    def __init__(self) -> None:
        self.time = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds


class Transport:
    """Replays a scripted list of responses or exceptions."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, dict, float]] = []

    def __call__(self, endpoint: str, parameters: dict, timeout: float) -> Any:
        self.calls.append((endpoint, dict(parameters), timeout))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def provider(transport: Transport, clock: Clock | None = None, **kwargs: Any) -> NbaStatsProvider:
    clock = clock or Clock()
    return NbaStatsProvider(
        transport=transport,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=lambda: NOW,
        **kwargs,
    )


def test_returns_the_payload_unchanged_with_its_provenance() -> None:
    transport = Transport(PAYLOAD)
    snap = provider(transport).fetch(
        D.TEAM_SEASON_ADVANCED, season=SEASON, season_type=SeasonType.REGULAR
    )
    assert snap.payload is PAYLOAD
    assert snap.source == "nba_stats"
    assert snap.dataset == "team_season_advanced"
    assert snap.partition == {"season": "2025-26", "season_type": "regular"}
    assert snap.fetched_at == NOW
    assert snap.request["endpoint"] == "LeagueDashTeamStats"


@pytest.mark.parametrize(
    ("dataset", "kwargs", "endpoint", "expected"),
    [
        (D.TEAM_YEARS, {}, "CommonTeamYears", {"league_id": "00"}),
        (
            D.PLAYER_INDEX,
            {"reference_season": SEASON},
            "PlayerIndex",
            {"season": "2025-26", "historical_nullable": 1},
        ),
        (
            D.STANDINGS,
            {"season": SEASON},
            "LeagueStandingsV3",
            {"season": "2025-26", "season_type": "Regular Season"},
        ),
        (
            D.TEAM_SEASON_OPPONENT,
            {"season": SEASON, "season_type": SeasonType.REGULAR},
            "LeagueDashTeamStats",
            {"measure_type_detailed_defense": "Opponent", "per_mode_detailed": "Totals"},
        ),
        (
            D.TEAM_GAME_LOGS,
            {"season": SEASON, "season_type": SeasonType.PLAY_IN},
            "LeagueGameLog",
            {"player_or_team_abbreviation": "T", "season_type_all_star": "PlayIn"},
        ),
        (
            D.PLAYER_GAME_LOGS,
            {"season": SEASON, "season_type": SeasonType.PLAYOFFS},
            "LeagueGameLog",
            {"player_or_team_abbreviation": "P", "season_type_all_star": "Playoffs"},
        ),
        (
            D.PLAYER_SEASON_ADVANCED,
            {"season": SEASON, "season_type": SeasonType.REGULAR},
            "LeagueDashPlayerStats",
            {"measure_type_detailed_defense": "Advanced", "season": "2025-26"},
        ),
        (
            D.PLAYER_SEASON_STARTERS,
            {"season": SEASON, "season_type": SeasonType.REGULAR},
            "LeagueDashPlayerStats",
            {"starter_bench_nullable": "Starters", "measure_type_detailed_defense": "Base"},
        ),
        (
            D.TEAM_ROSTER,
            {"season": SEASON, "team_id": 1610612738},
            "CommonTeamRoster",
            {"team_id": 1610612738, "season": "2025-26"},
        ),
        (
            D.TEAM_ON_OFF,
            {"season": SEASON, "season_type": SeasonType.REGULAR, "team_id": 1610612738},
            "TeamPlayerOnOffSummary",
            {"team_id": 1610612738, "measure_type_detailed_defense": "Advanced"},
        ),
    ],
)
def test_each_dataset_maps_to_its_endpoint(
    dataset: D, kwargs: dict, endpoint: str, expected: dict
) -> None:
    transport = Transport(PAYLOAD)
    provider(transport).fetch(dataset, **kwargs)
    called, parameters, _ = transport.calls[0]
    assert called == endpoint
    assert expected.items() <= parameters.items()


def test_every_catalogued_dataset_can_be_requested() -> None:
    assert set(_REQUESTS) == set(DATASET_SPECS)


def test_request_parameters_are_accepted_by_the_real_client() -> None:
    """Guard against nba_api renaming a parameter: build each call without sending it."""
    import inspect

    from nba_api.stats import endpoints

    samples = {"season": SEASON, "season_type": SeasonType.REGULAR, "team_id": 1610612738}
    for dataset, build in _REQUESTS.items():
        endpoint, parameters = build(samples["season"], samples["season_type"], samples["team_id"])
        accepted = set(inspect.signature(getattr(endpoints, endpoint).__init__).parameters)
        assert set(parameters) <= accepted, f"{dataset.value}: {set(parameters) - accepted}"
        assert "timeout" in accepted


def test_the_player_index_needs_a_reference_season() -> None:
    with pytest.raises(ValueError, match="reference point"):
        provider(Transport(PAYLOAD)).fetch(D.PLAYER_INDEX)


def test_timeout_is_passed_to_the_transport() -> None:
    transport = Transport(PAYLOAD)
    provider(transport, timeout=7.5).fetch(D.TEAM_YEARS)
    assert transport.calls[0][2] == 7.5


def test_requests_are_spaced_out() -> None:
    clock = Clock()
    nba = provider(Transport(PAYLOAD), clock, min_interval=1.5)
    nba.fetch(D.TEAM_YEARS)
    assert clock.sleeps == []  # the first request goes straight away
    nba.fetch(D.TEAM_YEARS)
    assert clock.sleeps == [1.5]
    clock.time += 10  # a long pause between requests needs no extra wait
    nba.fetch(D.TEAM_YEARS)
    assert clock.sleeps == [1.5]


@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.ReadTimeout("slow"),
        requests.exceptions.ConnectionError("dropped"),
        ValueError("Expecting value: line 1 column 1"),
        KeyError("resultSet"),
    ],
)
def test_transient_failures_are_retried_with_a_growing_pause(failure: Exception) -> None:
    clock = Clock()
    transport = Transport(failure, failure, PAYLOAD)
    snap = provider(transport, clock, min_interval=0, max_retries=3, backoff=4).fetch(D.TEAM_YEARS)
    assert snap.payload is PAYLOAD
    assert len(transport.calls) == 3
    assert clock.sleeps == [4, 8]


def test_gives_up_after_the_configured_retries() -> None:
    clock = Clock()
    transport = Transport(requests.exceptions.ReadTimeout("slow"))
    with pytest.raises(
        ProviderError, match=r"CommonTeamYears failed after 3 attempt\(s\): ReadTimeout"
    ):
        provider(transport, clock, min_interval=0, max_retries=2, backoff=1).fetch(D.TEAM_YEARS)
    assert len(transport.calls) == 3
    assert clock.sleeps == [1, 2]


def test_zero_retries_means_one_attempt() -> None:
    transport = Transport(requests.exceptions.ReadTimeout("slow"))
    with pytest.raises(ProviderError, match="1 attempt"):
        provider(transport, max_retries=0).fetch(D.TEAM_YEARS)
    assert len(transport.calls) == 1


def test_programming_errors_are_not_swallowed() -> None:
    with pytest.raises(TypeError):
        provider(Transport(TypeError("unexpected keyword"))).fetch(D.TEAM_YEARS)


@pytest.mark.parametrize("response", [{"Message": "An error has occurred."}, [], "<html>", None])
def test_a_response_without_result_sets_is_rejected(response: Any) -> None:
    transport = Transport(response)
    with pytest.raises(ProviderError, match="unexpected response shape"):
        provider(transport).fetch(D.TEAM_YEARS)
    assert len(transport.calls) == 1  # a wrong shape is not transient; do not hammer the source


def test_negative_retries_are_rejected() -> None:
    with pytest.raises(ValueError):
        NbaStatsProvider(max_retries=-1)


@pytest.mark.network
def test_live_standings_have_thirty_teams() -> None:
    snap = NbaStatsProvider().fetch(D.STANDINGS, season=SEASON)
    result_set = snap.payload["resultSets"][0]
    assert len(result_set["rowSet"]) == 30
    assert "TeamID" in result_set["headers"]
