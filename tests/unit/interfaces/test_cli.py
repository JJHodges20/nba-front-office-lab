from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from front_office import __version__
from front_office.config.settings import ENV_DATA_DIR, ENV_HOME
from front_office.interfaces.cli import app as cli
from front_office.interfaces.cli.app import app, money
from front_office.pipelines.ingest import Ingestor, RefreshPolicy
from front_office.rawstore import RawStore
from tests.conftest import FIXTURE_RAW
from tests.helpers import Clock, D, FakeProvider

runner = CliRunner()


@pytest.fixture(autouse=True)
def _use_throwaway_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_HOME, str(project))
    monkeypatch.setenv("COLUMNS", "200")


def test_info_reports_version_and_configured_seasons() -> None:
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output
    assert "2024-25, 2025-26, 2026-27" in result.output


def test_seasons_lists_cap_lines_for_each_season() -> None:
    result = runner.invoke(app, ["seasons"])
    assert result.exit_code == 0, result.output
    for expected in ("2024-25", "2026-27", "Salary cap", "$164,961,000", "$221,686,000", "14-15"):
        assert expected in result.output


def test_seasons_table_is_not_truncated_in_a_narrow_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    result = runner.invoke(app, ["seasons"])
    assert result.exit_code == 0, result.output
    for figure in ("$140,588,000", "$154,647,000", "$164,961,000", "Minimum team salary"):
        assert figure in result.output


def test_configuration_errors_exit_non_zero(project: Path) -> None:
    (project / "configs" / "base.yaml").write_text("paths: [broken\n", encoding="utf-8")
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_seasons_without_rule_files_exits_non_zero(project: Path) -> None:
    for path in (project / "configs" / "seasons").glob("*.yaml"):
        path.unlink()
    result = runner.invoke(app, ["seasons"])
    assert result.exit_code == 1
    assert "No season rules" in result.output


def test_money_formatting() -> None:
    assert money(164_961_000) == "$164,961,000"


def test_dictionary_prints_the_registry() -> None:
    result = runner.invoke(app, ["dictionary"])
    assert result.exit_code == 0
    assert result.output.startswith("# Data Dictionary")
    assert "### team_seasons" in result.output


def test_dictionary_write_creates_the_document(project: Path) -> None:
    result = runner.invoke(app, ["dictionary", "--write"])
    assert result.exit_code == 0, result.output
    written = (project / "docs" / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    assert written.startswith("# Data Dictionary")


class TestIngest:
    """The ingest command, with stats.nba.com replaced by a fake provider."""

    @pytest.fixture
    def provider(self, project: Path, monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
        clock = Clock(datetime.now(UTC))
        fake = FakeProvider(clock=clock)

        def build(settings, *, force=False, on_outcome=None) -> Ingestor:
            policy = RefreshPolicy(timedelta(hours=12), force=force)
            return Ingestor(
                fake, RawStore(settings.raw_dir), policy, now=clock.now, on_outcome=on_outcome
            )

        monkeypatch.setattr(cli, "build_ingestor", build)
        return fake

    def requested(self, provider: FakeProvider, dataset: str) -> list[dict[str, str]]:
        return [partition for name, partition in provider.calls if name == dataset]

    def test_a_named_season_is_fetched_with_player_detail(self, provider: FakeProvider) -> None:
        result = runner.invoke(app, ["ingest", "--season", "2024-25"])
        assert result.exit_code == 0, result.output
        assert self.requested(provider, "standings") == [{"season": "2024-25"}]
        assert self.requested(provider, "player_game_logs")
        assert len(self.requested(provider, "team_roster")) == 2
        assert "stored  standings/season=2024-25" in result.output
        assert "requests:" in result.output and "stored" in result.output

    def test_teams_only_skips_player_datasets(self, provider: FakeProvider) -> None:
        result = runner.invoke(app, ["ingest", "-s", "2024-25", "--teams-only"])
        assert result.exit_code == 0, result.output
        assert not self.requested(provider, "player_game_logs")
        assert not self.requested(provider, "team_roster")
        assert self.requested(provider, "team_game_logs")

    def test_several_seasons_may_be_named(self, provider: FakeProvider) -> None:
        result = runner.invoke(app, ["ingest", "-s", "2023-24", "-s", "2024-25", "--teams-only"])
        assert result.exit_code == 0, result.output
        assert self.requested(provider, "standings") == [
            {"season": "2023-24"},
            {"season": "2024-25"},
        ]

    def test_the_default_plan_covers_history_with_recent_player_detail(
        self, provider: FakeProvider
    ) -> None:
        result = runner.invoke(app, ["ingest"])
        assert result.exit_code == 0, result.output
        standings = [partition["season"] for partition in self.requested(provider, "standings")]
        assert standings[0] == "1996-97"
        assert len(standings) >= 31
        with_players = {p["season"] for p in self.requested(provider, "player_season_base")}
        assert len(with_players) == 4  # the current league year and three before it
        assert max(with_players) == standings[-1]
        assert self.requested(provider, "team_years") == [{}]

    def test_a_second_run_skips_what_is_already_stored(self, provider: FakeProvider) -> None:
        runner.invoke(app, ["ingest", "-s", "2024-25", "--teams-only"])
        calls = len(provider.calls)
        result = runner.invoke(app, ["ingest", "-s", "2024-25", "--teams-only"])
        assert result.exit_code == 0, result.output
        assert len(provider.calls) == calls
        assert "skipped" in result.output

    def test_force_refetches(self, provider: FakeProvider) -> None:
        runner.invoke(app, ["ingest", "-s", "2024-25", "--teams-only"])
        calls = len(provider.calls)
        result = runner.invoke(app, ["ingest", "-s", "2024-25", "--teams-only", "--force"])
        assert result.exit_code == 0, result.output
        assert len(provider.calls) == 2 * calls
        assert "unchanged" in result.output

    def test_failures_are_listed_and_exit_non_zero(self, provider: FakeProvider) -> None:
        provider.fail = {D.TEAM_SEASON_ADVANCED}
        result = runner.invoke(app, ["ingest", "-s", "2024-25", "--teams-only"])
        assert result.exit_code == 1
        assert "failed  team_season_advanced/season=2024-25/season_type=regular" in result.output
        assert "is down" in result.output
        assert "1 failed" in result.output

    def test_an_invalid_season_is_rejected_before_any_request(self, provider: FakeProvider) -> None:
        result = runner.invoke(app, ["ingest", "--season", "2024"])
        assert result.exit_code == 1
        assert "not a season label" in result.output
        assert provider.calls == []


class TestRawAndCheck:
    def test_raw_on_an_empty_store(self) -> None:
        result = runner.invoke(app, ["raw"])
        assert result.exit_code == 0
        assert "is empty" in result.output

    def test_raw_lists_stored_datasets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DATA_DIR, str(FIXTURE_RAW.parent))
        result = runner.invoke(app, ["raw"])
        assert result.exit_code == 0, result.output
        for expected in ("team_game_logs", "player_index", "1996-97 to 2026-27", "nba_stats"):
            assert expected in result.output

    def test_check_reports_tables_notes_and_failed_checks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_DATA_DIR, str(FIXTURE_RAW.parent))
        result = runner.invoke(app, ["check"])
        # The fixture store holds player logs for two teams only, which two checks
        # rightly report as errors, so the command exits non-zero.
        assert result.exit_code == 1
        assert "team_seasons" in result.output and "7,792" in result.output
        assert "note  team_games [2012-13]" in result.output
        assert "warning  team_games.points_add_up: 2 of 7,792 failed" in result.output
        assert "error  player_game_logs.points_sum_to_team_points" in result.output
        assert "2 with warnings, 2 with errors; 0 table parts not built" in result.output

    def test_check_on_an_empty_store_reports_what_is_missing(self) -> None:
        result = runner.invoke(app, ["check"])
        assert result.exit_code == 1
        assert "not built" in result.output
        assert "player_index" in result.output

    def test_check_says_when_no_contract_file_has_been_imported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_DATA_DIR, str(FIXTURE_RAW.parent))
        result = runner.invoke(app, ["check"])
        assert "note  contracts [all seasons]: no contract file has been imported" in result.output
        assert "salary_cap_rules" in result.output


class TestContracts:
    """The contracts commands, against a private copy of the fixture store."""

    @pytest.fixture(autouse=True)
    def _lab(self, project: Path) -> None:
        shutil.copytree(FIXTURE_RAW, project / "data" / "raw")

    def contract_file(self, directory: Path, text: str) -> Path:
        path = directory / "contracts.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_template_is_written_to_the_imports_folder(self, project: Path) -> None:
        result = runner.invoke(app, ["contracts", "template"])
        assert result.exit_code == 0, result.output
        template = project / "data" / "imports" / "contract_template.csv"
        assert template.is_file()
        assert "players listed" in result.output
        assert "fol contracts import" in result.output

    def test_template_honours_output_and_seasons(self, tmp_path: Path) -> None:
        target = tmp_path / "mine.csv"
        result = runner.invoke(
            app, ["contracts", "template", "--output", str(target), "--seasons", "2"]
        )
        assert result.exit_code == 0, result.output
        header = target.read_text(encoding="utf-8-sig").splitlines()[0]
        assert header.count("-") == 2  # exactly two season columns

    def test_import_reports_what_was_read(self, tmp_path: Path) -> None:
        path = self.contract_file(
            tmp_path,
            "player,team,2026-27,2027-28\nJayson Tatum,BOS,40000000,44000000 PO\n"
            "Nobody Atall,NYK,1000000,\n",
        )
        result = runner.invoke(
            app, ["contracts", "import", str(path), "--source", "invented for tests"]
        )
        assert result.exit_code == 0, result.output
        assert "Read 2 rows: 1 contracts for 1 players, 2 contract seasons" in result.output
        assert "(2026-27 to 2027-28)" in result.output
        assert "No salary cap is configured for 2027-28" in result.output
        assert "1 row(s) could not be matched" in result.output
        assert "line 3: Nobody Atall (NYK) - no player with this name" in result.output

    def test_importing_twice_says_nothing_new_was_stored(self, tmp_path: Path) -> None:
        path = self.contract_file(tmp_path, "player,team,2026-27\nJayson Tatum,BOS,40000000\n")
        arguments = [
            "contracts",
            "import",
            str(path),
            "--source",
            "invented",
            "--as-of",
            "2026-09-30",
        ]
        assert runner.invoke(app, arguments).exit_code == 0
        again = runner.invoke(app, arguments)
        assert again.exit_code == 0
        assert "identical to the last import" in again.output

    def test_the_source_is_required(self, tmp_path: Path) -> None:
        path = self.contract_file(tmp_path, "player,team,2026-27\nJayson Tatum,BOS,40000000\n")
        result = runner.invoke(app, ["contracts", "import", str(path)])
        assert result.exit_code == 2
        assert "--source" in result.output

    def test_a_bad_file_is_refused_with_the_reason(self, tmp_path: Path) -> None:
        path = self.contract_file(tmp_path, "player,team,2026-2027\nJayson Tatum,BOS,1\n")
        result = runner.invoke(app, ["contracts", "import", str(path), "--source", "invented"])
        assert result.exit_code == 1
        assert "look like seasons" in result.output

    def test_a_bad_date_is_refused(self, tmp_path: Path) -> None:
        path = self.contract_file(tmp_path, "player,team,2026-27\nJayson Tatum,BOS,1000000\n")
        result = runner.invoke(
            app, ["contracts", "import", str(path), "--source", "x", "--as-of", "October 1"]
        )
        assert result.exit_code == 1
        assert "--as-of must be a date like 2026-10-01" in result.output

    def test_imported_contracts_appear_in_check(self, tmp_path: Path) -> None:
        path = self.contract_file(tmp_path, "player,team,2026-27\nJayson Tatum,BOS,40000000\n")
        runner.invoke(app, ["contracts", "import", str(path), "--source", "invented"])
        result = runner.invoke(app, ["check"])
        assert "no contract file has been imported" not in result.output
        assert "contract_years.teams_have_plausible_rosters" in result.output
