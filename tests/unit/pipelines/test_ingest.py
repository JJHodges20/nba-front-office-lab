from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from front_office.config import Settings
from front_office.domain.datasets import NBA_STATS, NbaStatsDataset
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.snapshots import Snapshot
from front_office.pipelines.ingest import (
    FetchRequest,
    FetchStatus,
    Ingestor,
    RefreshPolicy,
    default_plan,
    global_requests,
    league_requests,
    team_requests,
)
from front_office.pipelines.inventory import store_inventory
from front_office.rawstore import RawStore
from tests.helpers import TEAMS, Clock, FakeProvider, stats_payload

D = NbaStatsDataset
REGULAR, PLAYOFFS, PLAY_IN = SeasonType.REGULAR, SeasonType.PLAYOFFS, SeasonType.PLAY_IN


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "raw")


def ingestor(provider: FakeProvider, store: RawStore, clock: Clock, **policy) -> Ingestor:
    policy.setdefault("refresh_after", timedelta(hours=12))
    return Ingestor(provider, store, RefreshPolicy(**policy), now=clock.now)


def statuses(outcomes) -> dict[str, FetchStatus]:
    return {outcome.request.describe(): outcome.status for outcome in outcomes}


class TestRequests:
    def test_team_level_season(self) -> None:
        requests = league_requests(Season(2025), players=False)
        assert [(r.dataset, r.season_type) for r in requests] == [
            (D.STANDINGS, None),
            (D.TEAM_SEASON_BASE, REGULAR),
            (D.TEAM_SEASON_ADVANCED, REGULAR),
            (D.TEAM_SEASON_OPPONENT, REGULAR),
            (D.TEAM_GAME_LOGS, REGULAR),
            (D.TEAM_GAME_LOGS, PLAYOFFS),
            (D.TEAM_GAME_LOGS, PLAY_IN),
        ]
        assert all(request.season == Season(2025) for request in requests)

    def test_play_in_is_not_requested_before_it_existed(self) -> None:
        def play_in(season: int) -> bool:
            return any(
                r.season_type is PLAY_IN for r in league_requests(Season(season), players=False)
            )

        assert not play_in(2018)
        assert play_in(2019)
        assert play_in(2020)

    def test_player_level_adds_regular_and_playoff_datasets(self) -> None:
        team_only = league_requests(Season(2025), players=False)
        with_players = league_requests(Season(2025), players=True)
        added = [(r.dataset, r.season_type) for r in with_players[len(team_only) :]]
        assert with_players[: len(team_only)] == team_only
        assert added == [
            (dataset, season_type)
            for season_type in (REGULAR, PLAYOFFS)
            for dataset in (
                D.PLAYER_SEASON_BASE,
                D.PLAYER_SEASON_ADVANCED,
                D.PLAYER_SEASON_STARTERS,
                D.PLAYER_GAME_LOGS,
            )
        ]

    def test_team_requests_cover_each_team(self) -> None:
        requests = team_requests(Season(2025), TEAMS, on_off=True)
        assert [(r.dataset, r.team_id) for r in requests] == [
            (D.TEAM_ROSTER, TEAMS[0]),
            (D.TEAM_ON_OFF, TEAMS[0]),
            (D.TEAM_ROSTER, TEAMS[1]),
            (D.TEAM_ON_OFF, TEAMS[1]),
        ]
        rosters_only = team_requests(Season(2026), TEAMS, on_off=False)
        assert {r.dataset for r in rosters_only} == {D.TEAM_ROSTER}

    def test_global_requests(self) -> None:
        requests = global_requests(Season(2026))
        assert [r.dataset for r in requests] == [D.TEAM_YEARS, D.PLAYER_INDEX]
        assert requests[1].reference_season == Season(2026)
        assert requests[1].partition == {}

    def test_request_description(self) -> None:
        request = FetchRequest(D.TEAM_ON_OFF, Season(2025), REGULAR, TEAMS[0])
        assert request.describe() == (
            "team_on_off/season=2025-26/season_type=regular/team_id=1610612738"
        )


class TestDefaultPlan:
    def test_history_runs_to_the_current_league_year(self, settings: Settings) -> None:
        plan = default_plan(settings, date(2026, 10, 1))
        assert plan.current == Season(2026)
        assert plan.seasons[0] == Season(1996)
        assert plan.seasons[-1] == Season(2026)
        assert len(plan.seasons) == 31

    def test_player_statistics_cover_the_whole_history(self, settings: Settings) -> None:
        plan = default_plan(settings, date(2026, 10, 1))
        assert plan.player_stats == frozenset(plan.seasons)
        assert plan.player_detail < plan.player_stats

    def test_player_statistics_can_start_later_than_team_history(self, project: Path) -> None:
        from front_office.config import load_settings

        (project / "configs" / "base.yaml").write_text(
            "seasons:\n  player_history_start: '2020-21'\n", encoding="utf-8"
        )
        plan = default_plan(load_settings(project), date(2026, 10, 1))
        assert plan.seasons[0] == Season(1996)
        assert min(plan.player_stats) == Season(2020) and len(plan.player_stats) == 7
        assert min(plan.player_detail) == Season(2023)

    def test_player_statistics_that_start_in_the_future_are_none_yet(self, project: Path) -> None:
        from front_office.config import load_settings

        (project / "configs" / "base.yaml").write_text(
            "seasons:\n  player_history_start: '2030-31'\n", encoding="utf-8"
        )
        plan = default_plan(load_settings(project), date(2026, 10, 1))
        assert plan.player_stats == frozenset() and plan.player_detail == frozenset()
        assert len(plan.seasons) == 31

    def test_player_detail_covers_the_current_year_and_the_configured_seasons_before_it(
        self, settings: Settings
    ) -> None:
        plan = default_plan(settings, date(2026, 10, 1))
        assert sorted(s.label for s in plan.player_detail) == [
            "2023-24",
            "2024-25",
            "2025-26",
            "2026-27",
        ]

    def test_the_league_year_has_not_rolled_over_in_june(self, settings: Settings) -> None:
        assert default_plan(settings, date(2026, 6, 15)).current == Season(2025)

    def test_player_detail_never_starts_before_history(self, project: Path) -> None:
        from front_office.config import load_settings

        (project / "configs" / "base.yaml").write_text(
            "seasons:\n  history_start: '2025-26'\n  player_detail_seasons: 5\n", encoding="utf-8"
        )
        plan = default_plan(load_settings(project), date(2026, 10, 1))
        assert sorted(s.label for s in plan.player_detail) == ["2025-26", "2026-27"]


class TestRefreshPolicy:
    def stored(self, store: RawStore, request: FetchRequest, fetched_at: datetime):
        snapshot = Snapshot(
            NBA_STATS,
            request.dataset.value,
            request.partition,
            fetched_at,
            stats_payload(["A"], []),
        )
        return store.save(snapshot).stored

    def test_never_fetched_is_due(self, clock: Clock) -> None:
        policy = RefreshPolicy(timedelta(hours=12))
        assert policy.is_due(FetchRequest(D.STANDINGS, Season(2025)), None, clock.now())

    def test_a_finished_season_fetched_after_it_ended_is_final(self, store, clock) -> None:
        request = FetchRequest(D.STANDINGS, Season(2025))
        newest = self.stored(store, request, datetime(2026, 7, 2, tzinfo=UTC))
        policy = RefreshPolicy(timedelta(hours=12))
        assert not policy.is_due(request, newest, clock.now() + timedelta(days=900))

    def test_a_snapshot_taken_mid_season_is_refetched_once_the_season_is_over(
        self, store, clock
    ) -> None:
        request = FetchRequest(D.STANDINGS, Season(2025))
        newest = self.stored(store, request, datetime(2026, 3, 1, tzinfo=UTC))
        policy = RefreshPolicy(timedelta(hours=12))
        assert policy.is_due(request, newest, datetime(2026, 8, 1, tzinfo=UTC))

    def test_a_season_in_progress_follows_the_refresh_interval(self, store, clock) -> None:
        request = FetchRequest(D.STANDINGS, Season(2026))
        newest = self.stored(store, request, clock.now())
        policy = RefreshPolicy(timedelta(hours=12))
        assert not policy.is_due(request, newest, clock.now() + timedelta(hours=11))
        assert policy.is_due(request, newest, clock.now() + timedelta(hours=12))

    def test_global_datasets_follow_the_refresh_interval(self, store, clock) -> None:
        request = FetchRequest(D.TEAM_YEARS)
        newest = self.stored(store, request, clock.now())
        policy = RefreshPolicy(timedelta(hours=12))
        assert not policy.is_due(request, newest, clock.now() + timedelta(hours=1))
        assert policy.is_due(request, newest, clock.now() + timedelta(days=2))

    def test_force_always_fetches(self, store, clock) -> None:
        request = FetchRequest(D.STANDINGS, Season(2025))
        newest = self.stored(store, request, datetime(2026, 7, 2, tzinfo=UTC))
        assert RefreshPolicy(timedelta(hours=12), force=True).is_due(request, newest, clock.now())


class TestIngestor:
    def test_team_level_season_is_stored(self, store: RawStore, clock: Clock) -> None:
        provider = FakeProvider(clock=clock)
        outcomes = ingestor(provider, store, clock).ingest_season(Season(2025), players=False)
        assert len(outcomes) == 7
        assert {outcome.status for outcome in outcomes} == {FetchStatus.STORED}
        assert all(outcome.stored is not None for outcome in outcomes)
        assert outcomes[1].rows == 1
        assert not any(dataset == "team_roster" for dataset, _ in provider.calls)

    def test_player_level_season_fetches_each_team_from_the_standings(
        self, store: RawStore, clock: Clock
    ) -> None:
        provider = FakeProvider(clock=clock)
        outcomes = ingestor(provider, store, clock).ingest_season(Season(2025), players=True)
        per_team = [o.request for o in outcomes if o.request.team_id is not None]
        assert [(r.dataset, r.team_id) for r in per_team] == [
            (D.TEAM_ROSTER, TEAMS[0]),
            (D.TEAM_ON_OFF, TEAMS[0]),
            (D.TEAM_ROSTER, TEAMS[1]),
            (D.TEAM_ON_OFF, TEAMS[1]),
        ]
        assert {outcome.status for outcome in outcomes} == {FetchStatus.STORED}

    def test_player_statistics_without_the_team_by_team_detail(
        self, store: RawStore, clock: Clock
    ) -> None:
        provider = FakeProvider(clock=clock)
        outcomes = ingestor(provider, store, clock).ingest_season(
            Season(2010), players=True, detail=False
        )
        fetched = {outcome.request.dataset for outcome in outcomes}
        assert {D.PLAYER_SEASON_BASE, D.PLAYER_SEASON_ADVANCED, D.PLAYER_GAME_LOGS} <= fetched
        assert not {D.TEAM_ROSTER, D.TEAM_ON_OFF} & fetched
        assert not [o for o in outcomes if o.request.team_id is not None]
        assert len(outcomes) == 6 + 8  # team data, then four player datasets in two phases

    def test_detail_needs_player_statistics(self, store: RawStore, clock: Clock) -> None:
        provider = FakeProvider(clock=clock)
        outcomes = ingestor(provider, store, clock).ingest_season(
            Season(2025), players=False, detail=True
        )
        assert not [o for o in outcomes if o.request.team_id is not None]

    def test_on_off_is_not_requested_before_games_are_played(
        self, store: RawStore, clock: Clock
    ) -> None:
        provider = FakeProvider(clock=clock, games_played=False)
        outcomes = ingestor(provider, store, clock).ingest_season(Season(2026), players=True)
        per_team = {o.request.dataset for o in outcomes if o.request.team_id is not None}
        assert per_team == {D.TEAM_ROSTER}

    def test_a_finished_season_is_skipped_on_the_next_run(self, store, clock) -> None:
        provider = FakeProvider(clock=clock)
        runner = ingestor(provider, store, clock)
        runner.ingest_season(Season(2025), players=False)
        calls_after_first = len(provider.calls)
        clock.advance(days=30)
        outcomes = runner.ingest_season(Season(2025), players=False)
        assert {outcome.status for outcome in outcomes} == {FetchStatus.SKIPPED}
        assert len(provider.calls) == calls_after_first
        assert all(outcome.stored is not None for outcome in outcomes)

    def test_a_season_in_progress_is_refetched_and_deduplicated(self, store, clock) -> None:
        provider = FakeProvider(clock=clock)
        runner = ingestor(provider, store, clock)
        runner.ingest_season(Season(2026), players=False)
        clock.advance(hours=13)
        unchanged = runner.ingest_season(Season(2026), players=False)
        assert {outcome.status for outcome in unchanged} == {FetchStatus.UNCHANGED}

        clock.advance(hours=13)
        provider.revision = 1  # the source now reports different numbers
        changed = statuses(runner.ingest_season(Season(2026), players=False))
        assert changed["standings/season=2026-27"] is FetchStatus.UNCHANGED
        assert changed["team_season_base/season=2026-27/season_type=regular"] is FetchStatus.STORED

    def test_one_failure_does_not_stop_the_run(self, store: RawStore, clock: Clock) -> None:
        provider = FakeProvider(clock=clock)
        provider.fail = {D.TEAM_SEASON_ADVANCED}
        outcomes = ingestor(provider, store, clock).ingest_season(Season(2025), players=False)
        by_request = statuses(outcomes)
        failed = [o for o in outcomes if o.status is FetchStatus.FAILED]
        assert len(failed) == 1
        assert failed[0].request.dataset is D.TEAM_SEASON_ADVANCED
        assert "is down" in failed[0].error
        assert (
            by_request["team_game_logs/season=2025-26/season_type=playoffs"] is FetchStatus.STORED
        )

    def test_a_failed_request_is_retried_on_the_next_run(self, store, clock) -> None:
        provider = FakeProvider(clock=clock)
        provider.fail = {D.TEAM_SEASON_ADVANCED}
        runner = ingestor(provider, store, clock)
        runner.ingest_season(Season(2025), players=False)
        provider.fail = set()
        retried = statuses(runner.ingest_season(Season(2025), players=False))
        assert (
            retried["team_season_advanced/season=2025-26/season_type=regular"] is FetchStatus.STORED
        )
        assert retried["standings/season=2025-26"] is FetchStatus.SKIPPED

    def test_team_datasets_wait_for_standings(self, store: RawStore, clock: Clock) -> None:
        provider = FakeProvider(clock=clock)
        provider.fail = {D.STANDINGS}
        outcomes = ingestor(provider, store, clock).ingest_season(Season(2025), players=True)
        assert not [o for o in outcomes if o.request.team_id is not None]
        assert statuses(outcomes)["standings/season=2025-26"] is FetchStatus.FAILED

    def test_force_refetches_final_data(self, store: RawStore, clock: Clock) -> None:
        provider = FakeProvider(clock=clock)
        ingestor(provider, store, clock).ingest_season(Season(2025), players=False)
        clock.advance(days=1)
        forced = ingestor(provider, store, clock, force=True).ingest_season(
            Season(2025), players=False
        )
        assert {outcome.status for outcome in forced} == {FetchStatus.UNCHANGED}

    def test_globals_are_fetched_with_the_current_season_as_reference(self, store, clock) -> None:
        provider = FakeProvider(clock=clock)
        outcomes = ingestor(provider, store, clock).ingest_globals(Season(2026))
        assert [o.request.dataset for o in outcomes] == [D.TEAM_YEARS, D.PLAYER_INDEX]
        assert store.latest(NBA_STATS, "player_index", {}) is not None

    def test_outcomes_are_reported_as_they_happen(self, store: RawStore, clock: Clock) -> None:
        seen = []
        runner = Ingestor(
            FakeProvider(clock=clock),
            store,
            RefreshPolicy(timedelta(hours=12)),
            now=clock.now,
            on_outcome=seen.append,
        )
        outcomes = runner.ingest_season(Season(2025), players=False)
        assert seen == outcomes


def test_inventory_summarises_the_store(store: RawStore, clock: Clock) -> None:
    runner = ingestor(FakeProvider(clock=clock), store, clock)
    runner.ingest_globals(Season(2026))
    runner.ingest_season(Season(2024), players=False)
    runner.ingest_season(Season(2025), players=True)

    inventory = {entry.dataset: entry for entry in store_inventory(store)}
    assert inventory["standings"].partitions == 2
    assert (inventory["standings"].first_season, inventory["standings"].last_season) == (
        "2024-25",
        "2025-26",
    )
    assert inventory["team_roster"].partitions == 2
    assert inventory["team_years"].first_season is None
    assert inventory["team_game_logs"].snapshots == 6
    assert inventory["standings"].newest_fetch == clock.now()


def test_inventory_of_an_empty_store(store: RawStore) -> None:
    assert store_inventory(store) == []
