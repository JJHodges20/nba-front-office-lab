from __future__ import annotations

import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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


def test_metrics_prints_the_glossary() -> None:
    result = runner.invoke(app, ["metrics"])
    assert result.exit_code == 0
    assert result.output.startswith("# Metric Glossary")
    assert "## Player metrics" in result.output and "## Team metrics" in result.output


def test_metrics_write_creates_the_document(project: Path) -> None:
    result = runner.invoke(app, ["metrics", "--write"])
    assert result.exit_code == 0, result.output
    assert "92 metrics" in result.output
    written = (project / "docs" / "METRICS.md").read_text(encoding="utf-8")
    assert written.startswith("# Metric Glossary")
    assert "\r" not in written


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
        assert "3 with warnings, 2 with errors; 0 table parts not built" in result.output

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


class TestDatabaseCommands:
    """build, refresh and db, against a private copy of the fixture store."""

    @pytest.fixture(autouse=True)
    def _lab(self, project: Path) -> None:
        shutil.copytree(FIXTURE_RAW, project / "data" / "raw")

    def test_db_before_anything_is_built(self, project: Path) -> None:
        result = runner.invoke(app, ["db"])
        assert result.exit_code == 0
        assert "There is no database" in result.output
        assert not (project / "data" / "front_office.sqlite").exists()

    def test_build_loads_the_database_and_reports_it(self, project: Path) -> None:
        result = runner.invoke(app, ["build"])
        # The fixture store fails two checks by construction, so the build loads but
        # the command reports problems.
        assert result.exit_code == 1
        assert "Loaded 10," in result.output and "(build 1)" in result.output
        assert "The build loaded with problems" in result.output
        assert "note  team_games [2012-13]" in result.output
        assert (project / "data" / "front_office.sqlite").is_file()

    @pytest.fixture
    def prebuilt(self, project: Path, built_template) -> None:
        """Put the shared pre-built database in place, as if `fol build` had been run."""
        for path in (built_template[0] / "data").glob("front_office.sqlite*"):
            shutil.copy(path, project / "data" / path.name)

    def test_benchmarks_before_anything_is_built(self, project: Path) -> None:
        result = runner.invoke(app, ["benchmarks"])
        assert result.exit_code == 1
        assert "no data has been built yet; run: fol refresh" in result.output
        assert not (project / "data" / "front_office.sqlite").exists()

    def test_benchmarks_prints_the_research(self, prebuilt: None) -> None:
        result = runner.invoke(app, ["benchmarks"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("# What Contenders Have Looked Like")
        assert "## How far teams went: by record" in result.output
        assert "| All seasons | 1996-97 to 2025-26 (3) | 89 |" in result.output

    def test_benchmarks_write_creates_the_document(self, project: Path, prebuilt: None) -> None:
        result = runner.invoke(app, ["benchmarks", "--write"])
        assert result.exit_code == 0, result.output
        assert "(3 completed seasons)" in result.output
        written = (project / "docs" / "research" / "BENCHMARKS.md").read_bytes()
        assert written.startswith(b"# What Contenders Have Looked Like")
        assert b"\r" not in written

    def test_db_after_a_build(self, prebuilt: None) -> None:
        result = runner.invoke(app, ["db"])
        assert result.exit_code == 0, result.output
        assert "Database: " in result.output
        assert "team_games" in result.output and "7,792" in result.output
        assert "Build 1 finished" in result.output
        assert "(problems)" in result.output
        assert "2 check errors, 3 check warnings" in result.output
        assert "different version" not in result.output

    def test_a_build_that_would_empty_a_table_is_refused(
        self, project: Path, prebuilt: None
    ) -> None:
        shutil.rmtree(project / "data" / "raw" / "nba_stats" / "player_index")
        result = runner.invoke(app, ["build"])
        assert result.exit_code == 1
        assert "would empty players" in result.output
        assert "Loaded" not in result.output
        forced = runner.invoke(app, ["build", "--force"])
        assert "Loaded" in forced.output and "(build 2)" in forced.output

    def test_db_warns_when_built_by_another_version(
        self, monkeypatch: pytest.MonkeyPatch, prebuilt: None
    ) -> None:
        from front_office.storage import database

        monkeypatch.setattr(database, "schema_fingerprint", lambda contracts: "another")
        result = runner.invoke(app, ["db"])
        assert "built by a different version of the lab; run: fol build" in result.output

    def test_ingest_records_its_fetches_in_the_database(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from front_office.storage import Database, OperationsLog

        clock = Clock(datetime.now(UTC))
        fake = FakeProvider(clock=clock)
        fake.fail = {D.TEAM_SEASON_ADVANCED}

        def build(settings, *, force=False, on_outcome=None) -> Ingestor:
            policy = RefreshPolicy(timedelta(hours=12), force=force)
            return Ingestor(
                fake, RawStore(settings.raw_dir), policy, now=clock.now, on_outcome=on_outcome
            )

        monkeypatch.setattr(cli, "build_ingestor", build)
        result = runner.invoke(app, ["ingest", "-s", "2024-25", "--teams-only"])
        assert result.exit_code == 1  # one dataset is down
        with Database(project / "data" / "front_office.sqlite") as opened:
            log = OperationsLog(opened)
            failed = log.fetches(status="failed")
            everything = log.fetches()
        assert failed["dataset"].tolist() == ["team_season_advanced"]
        assert "is down" in failed.iloc[0]["error"]
        # Seven season datasets were requested; the two global ones were already in the
        # copied store and inside their refresh window, so they were skipped, not logged.
        assert len(everything) == 7
        assert set(everything["status"]) == {"stored", "failed"}

    def test_refresh_fetches_then_builds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = Clock(datetime.now(UTC))
        fake = FakeProvider(clock=clock)
        calls: list[str] = []

        def build(settings, *, force=False, on_outcome=None) -> Ingestor:
            calls.append("ingest")
            policy = RefreshPolicy(timedelta(hours=12), force=force)
            return Ingestor(
                fake, RawStore(settings.raw_dir), policy, now=clock.now, on_outcome=on_outcome
            )

        def fake_build(settings, *, force):
            calls.append("build")

        monkeypatch.setattr(cli, "build_ingestor", build)
        monkeypatch.setattr(cli, "_build", fake_build)
        result = runner.invoke(app, ["refresh", "--teams-only"])
        assert result.exit_code == 0, result.output
        assert calls == ["ingest", "build"]
        assert "requests:" in result.output

    def test_refresh_still_builds_when_a_fetch_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = Clock(datetime.now(UTC))
        fake = FakeProvider(clock=clock)
        fake.fail = {D.TEAM_SEASON_OPPONENT}
        built: list[bool] = []

        def build(settings, *, force=False, on_outcome=None) -> Ingestor:
            policy = RefreshPolicy(timedelta(hours=12), force=force)
            return Ingestor(
                fake, RawStore(settings.raw_dir), policy, now=clock.now, on_outcome=on_outcome
            )

        monkeypatch.setattr(cli, "build_ingestor", build)
        monkeypatch.setattr(cli, "_build", lambda settings, *, force: built.append(True))
        result = runner.invoke(app, ["refresh", "--teams-only"])
        assert built == [True]
        assert result.exit_code == 1
        assert "building from what is stored" in result.output


class TestUi:
    """The command that starts the workbench, with the server itself replaced."""

    @pytest.fixture
    def launched(self, project: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
        """A project that has a workbench script, and a record of what would be run."""
        script = project / "apps" / "workbench" / "app.py"
        script.parent.mkdir(parents=True)
        script.write_text("", encoding="utf-8")
        calls: list[dict] = []

        def run(command, *, cwd, env, check):
            calls.append({"command": command, "cwd": cwd, "env": env})
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cli.subprocess, "run", run)
        return calls

    def test_starts_streamlit_on_the_workbench_of_this_project(
        self, project: Path, launched: list[dict]
    ) -> None:
        result = runner.invoke(app, ["ui", "--no-browser"])
        assert result.exit_code == 0, result.output
        assert "http://localhost:8501" in result.output
        call = launched[0]
        assert call["command"][1:4] == ["-m", "streamlit", "run"]
        assert Path(call["command"][4]) == project / "apps" / "workbench" / "app.py"
        assert call["command"][5:] == ["--server.port", "8501"]
        assert call["cwd"] == project
        assert call["env"][ENV_HOME] == str(project)

    def test_a_project_found_from_the_working_directory_is_pinned_for_the_workbench(
        self, project: Path, launched: list[dict], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Streamlit runs the workbench as another process; it must not look again and
        # settle on a different project than the command did.
        monkeypatch.delenv(ENV_HOME)
        monkeypatch.chdir(project)
        result = runner.invoke(app, ["ui", "--no-browser"])
        assert result.exit_code == 0, result.output
        assert Path(launched[0]["env"][ENV_HOME]) == project.resolve()

    def test_the_port_can_be_chosen(self, launched: list[dict]) -> None:
        result = runner.invoke(app, ["ui", "--no-browser", "--port", "8600"])
        assert result.exit_code == 0, result.output
        assert launched[0]["command"][-1] == "8600"
        assert "http://localhost:8600" in result.output

    def test_the_browser_opens_unless_told_not_to(
        self, launched: list[dict], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []
        monkeypatch.setattr(cli, "_open_when_ready", opened.append)
        assert runner.invoke(app, ["ui", "--no-browser"]).exit_code == 0
        assert opened == []
        assert runner.invoke(app, ["ui"]).exit_code == 0
        for _ in range(100):  # the opener runs on its own thread
            if opened:
                break
            time.sleep(0.01)
        assert opened == ["http://localhost:8501"]

    def test_a_failed_start_is_reported_through_the_exit_code(
        self, launched: list[dict], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=3)
        )
        assert runner.invoke(app, ["ui", "--no-browser"]).exit_code == 3

    def test_a_project_without_the_workbench_says_so(self, project: Path) -> None:
        result = runner.invoke(app, ["ui", "--no-browser"])
        assert result.exit_code == 1
        assert "the workbench is missing" in result.output

    def test_the_browser_waits_for_the_server_and_gives_up_quietly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []
        monkeypatch.setattr(cli.webbrowser, "open", opened.append)

        def refused(url, timeout):
            raise OSError("connection refused")

        monkeypatch.setattr(cli.urllib.request, "urlopen", refused)
        assert cli._open_when_ready("http://localhost:1", patience=0.2) is False
        assert opened == []

    def test_the_browser_opens_once_the_server_answers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []
        asked: list[str] = []
        monkeypatch.setattr(cli.webbrowser, "open", opened.append)

        class Answer:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def answering(url, timeout):
            asked.append(url)
            return Answer()

        monkeypatch.setattr(cli.urllib.request, "urlopen", answering)
        assert cli._open_when_ready("http://localhost:8501", patience=1) is True
        assert asked == ["http://localhost:8501/_stcore/health"]
        assert opened == ["http://localhost:8501"]
