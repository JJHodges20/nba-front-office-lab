"""The current-data tools: fetched when due, dated, and never "healthy" for "not listed"."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from front_office.assistant import tools as t
from front_office.assistant.current_tools import current_handlers
from front_office.config import Settings
from front_office.domain.assistant import EvidenceKind, ResultStatus
from front_office.pipelines.current import refresh_current
from front_office.providers.nba_current import (
    INJURY_REPORT_BASE,
    PLAYER_MOVEMENT_URL,
    CurrentProvider,
)
from front_office.services import Lab
from tests.current_fakes import FakeGet, FakeStats, fixture_game_logs, league_files
from tests.helpers import BOS, BROWN, NYK, PRITCHARD

GAME_DAY = datetime(2026, 10, 21, 21, 50)
NOW = datetime(2026, 10, 9, 16, 0)


class Refresher:
    """Refreshes from the fakes, as at a fixed moment, and counts what it was asked for."""

    def __init__(
        self, settings: Settings, get: FakeGet | None = None, *, force: bool = False, **logs: dict
    ) -> None:
        self.settings = settings
        self.get = get or league_files()
        self.force = force
        self.logs = logs
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, sources: Sequence[str]) -> object:
        self.asked.append(tuple(sources))
        provider = CurrentProvider(
            get=self.get, now=lambda: GAME_DAY.replace(tzinfo=UTC), sleep=lambda _: None
        )
        return refresh_current(
            self.settings,
            sources=sources,
            now=lambda: GAME_DAY,
            provider=provider,
            stats=FakeStats(self.logs),
            force=self.force,
        )


def tools(refresh: object) -> dict:
    return current_handlers(refresh, now=lambda: NOW)  # type: ignore[arg-type]


class TestTheInjuryReport:
    def test_a_player_on_the_report_with_its_time(self, scratch: Lab) -> None:
        refresher = Refresher(scratch.settings)
        found = tools(refresher)["injury_report"](scratch, t.InjuryReport(player_id=BROWN))
        assert refresher.asked == [("injuries",)]
        assert found.status is ResultStatus.OK
        assert "the report of 2026-10-21 05:30 PM Eastern" in found.text
        assert (
            "| Brown, Jaylen | Questionable | Injury/Illness - Left Knee; Soreness |" in found.text
        )
        (evidence,) = found.evidence
        assert evidence.kind is EvidenceKind.CURRENT
        assert evidence.location.endswith("Injury-Report_2026-10-21_05_30PM.pdf")
        assert evidence.published_at == datetime(2026, 10, 21, 21, 30)
        assert evidence.effective_at == date(2026, 10, 21)

    def test_a_player_not_on_it_is_not_called_healthy(self, scratch: Lab) -> None:
        found = tools(Refresher(scratch.settings))["injury_report"](
            scratch, t.InjuryReport(player_id=PRITCHARD)
        )
        assert found.status is ResultStatus.OK
        assert found.text.startswith("This player is not on the report of 2026-10-21")
        assert "not the same as healthy" in found.text
        assert "healthy" not in found.text.replace("not the same as healthy", "")

    def test_a_team_shows_its_lines(self, scratch: Lab) -> None:
        found = tools(Refresher(scratch.settings))["injury_report"](
            scratch, t.InjuryReport(team_id=BOS)
        )
        assert "(2 lines)" in found.text
        assert len(found.table) == 2

    def test_a_source_never_reached_is_unavailable(self, scratch: Lab) -> None:
        found = tools(None)["injury_report"](scratch, t.InjuryReport(team_id=NYK))
        assert found.status is ResultStatus.UNAVAILABLE
        assert "could not be read (it has never been fetched)" in found.text

    def test_no_report_published_is_a_dated_answer_with_its_limit(self, scratch: Lab) -> None:
        refresher = Refresher(scratch.settings, league_files(report=None))
        found = tools(refresher)["injury_report"](scratch, t.InjuryReport(team_id=NYK))
        assert found.status is ResultStatus.OK
        (limit,) = found.limits
        assert limit.startswith("There is no injury report to read (no report published")
        assert "not the same as healthy" in limit
        (evidence,) = found.evidence
        assert evidence.location == INJURY_REPORT_BASE and evidence.retrieved_at == GAME_DAY


class TestTransactions:
    def test_a_teams_moves_dated_newest_first(self, scratch: Lab) -> None:
        found = tools(Refresher(scratch.settings))["transactions"](
            scratch, t.Transactions(team_id=NYK)
        )
        assert found.status is ResultStatus.OK
        lines = [line for line in found.text.splitlines() if line.startswith("| 20")]
        assert lines[0].startswith("| 2026-10-05 | Waive | NYK |")
        assert lines[1].startswith("| 2026-10-02 | Signing | NYK |")
        # The fixture build is of 2026-10-01: both moves came after it.
        assert "2 of them dated after the lab's data build of 2026-10-01" in found.text
        assert all(line.endswith("| yes |") for line in lines)
        moves, build = found.evidence
        assert moves.location == PLAYER_MOVEMENT_URL
        assert moves.effective_at == date(2026, 10, 5)
        assert moves.retrieved_at == GAME_DAY
        assert build.build_id == 1, "the comparison with the build rests on the build"
        assert found.limits == ()

    def test_no_move_in_the_window_is_a_dated_answer_with_its_limit(self, scratch: Lab) -> None:
        found = tools(Refresher(scratch.settings))["transactions"](
            scratch, t.Transactions(team_id=BOS, since=date(2026, 10, 1))
        )
        assert found.status is ResultStatus.OK and found.table.empty
        (limit,) = found.limits
        assert limit.startswith("The league's file lists no move for this since 2026-10-01")
        assert "The lab's data build is of 2026-10-01." in found.text

    def test_with_nothing_named_the_last_two_weeks(self, scratch: Lab) -> None:
        found = tools(Refresher(scratch.settings))["transactions"](scratch, t.Transactions())
        assert "2 moves since 2026-09-25" in found.text
        assert "Pat Roe" not in found.text

    def test_a_refresh_that_cannot_run_falls_back_to_the_last_copy(self, scratch: Lab) -> None:
        Refresher(scratch.settings)(["transactions"])

        def broken(sources: Sequence[str]) -> object:
            raise OSError("the network is down")

        found = tools(broken)["transactions"](scratch, t.Transactions(team_id=NYK))
        assert found.status is ResultStatus.OK
        assert found.warnings == (
            "The transactions could not be refreshed (the network is down); the last copy is used.",
        )

    def test_a_failed_fetch_is_noted_with_the_date_of_the_copy_used(self, scratch: Lab) -> None:
        Refresher(scratch.settings)(["transactions"])
        failing = Refresher(
            scratch.settings, FakeGet({PLAYER_MOVEMENT_URL: (503, b"")}), force=True
        )
        found = tools(failing)["transactions"](scratch, t.Transactions(team_id=NYK))
        assert found.status is ResultStatus.OK
        (note,) = found.warnings
        assert note.startswith("The last attempt to fetch the transactions failed")
        assert "answered 503" in note and "the copy of 2026-10-21 21:50 UTC is used" in note


class TestTheGames:
    def test_none_yet_says_so_and_that_preseason_is_not_held(self, scratch: Lab) -> None:
        found = tools(Refresher(scratch.settings))["current_games"](scratch, t.CurrentGames())
        assert found.status is ResultStatus.OK and found.table.empty
        (limit,) = found.limits
        assert "no 2026-27 games played yet" in limit
        assert "Preseason games are not part of the lab's data" in limit
        assert found.evidence[0].location == "stats.nba.com LeagueGameLog"

    def test_games_newer_than_the_build_are_counted(self, scratch: Lab) -> None:
        refresher = Refresher(scratch.settings, regular=fixture_game_logs("regular", 2))
        found = tools(refresher)["current_games"](scratch, t.CurrentGames())
        assert found.status is ResultStatus.OK
        assert found.text.startswith("2026-27: 2 games, as fetched 2026-10-21 21:50 UTC")
        assert "2 of them newer than the lab's data build" in found.text
        rows = [line for line in found.text.splitlines() if line.startswith("| 20")]
        assert len(rows) == 2, "each game once when no team is named"

    def test_a_teams_games_from_its_side(self, scratch: Lab) -> None:
        refresher = Refresher(scratch.settings, regular=fixture_game_logs("regular", 2))
        everything = tools(refresher)["current_games"](scratch, t.CurrentGames())
        team = int(everything.table["team_id"].iloc[0])
        found = tools(None)["current_games"](scratch, t.CurrentGames(team_id=team))
        assert found.status is ResultStatus.OK
        assert "| Opponent | Result | Score |" in found.text


def test_the_tools_are_the_registrys(tmp_path: Path) -> None:
    assert set(tools(None)) == {"current_games", "transactions", "injury_report"}
