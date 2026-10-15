from __future__ import annotations

import shutil
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from front_office import __version__
from front_office.config.settings import ENV_DATA_DIR, ENV_HOME
from front_office.interfaces.cli import app as cli
from front_office.interfaces.cli.app import app, money
from front_office.pipelines import rag as rag_pipeline
from front_office.pipelines.ingest import Ingestor, RefreshPolicy
from front_office.providers.ollama import OllamaProvider
from front_office.rawstore import RawStore
from tests.conftest import FIXTURE_RAW
from tests.helpers import FETCHED_AT, Clock, D, FakeProvider
from tests.ollama_fakes import ScriptedOllama
from tests.rag_fakes import ollama as rag_ollama
from tests.rag_fakes import write_documents

runner = CliRunner()

# An hour after the fixture store was fetched: inside its refresh window, whatever the
# day the tests run on.
NOW = FETCHED_AT + timedelta(hours=1)


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
    assert "152 metrics" in result.output
    written = (project / "docs" / "METRICS.md").read_text(encoding="utf-8")
    assert written.startswith("# Metric Glossary")
    assert "\r" not in written


class TestIngest:
    """The ingest command, with stats.nba.com replaced by a fake provider."""

    @pytest.fixture
    def provider(self, project: Path, monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
        clock = Clock(NOW)
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
        # League-wide player statistics for every season of history ...
        with_players = {p["season"] for p in self.requested(provider, "player_season_base")}
        assert with_players == set(standings)
        # ... and team-by-team detail for the current league year and three before it.
        with_detail = {p["season"] for p in self.requested(provider, "team_roster")}
        assert len(with_detail) == 4 and max(with_detail) == standings[-1]
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
        assert "warning  player_game_logs.points_sum_to_team_points" in result.output
        assert "error  player_game_logs.points_close_to_team_points" in result.output
        assert "5 with warnings, 2 with errors; 0 table parts not built" in result.output

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

    def test_a_preview_compares_flags_and_stores_nothing(
        self, tmp_path: Path, project: Path
    ) -> None:
        """A7: what a candidate changes, what to check, and the import left to the user."""
        first = self.contract_file(tmp_path, "player,team,2026-27\nJayson Tatum,BOS,40000000\n")
        runner.invoke(
            app,
            ["contracts", "import", str(first), "--source", "invented", "--as-of", "2026-10-01"],
        )
        candidate = tmp_path / "newer.csv"
        candidate.write_text("player,team,2026-27\nJayson Tatum,BOS,42000000\n", encoding="utf-8")
        snapshots = list((project / "data" / "raw").rglob("*contract*"))
        result = runner.invoke(
            app,
            [
                "contracts",
                "preview",
                str(candidate),
                "--source",
                "[a new site]",
                "--as-of",
                "2026-10-09",
            ],
        )
        assert result.exit_code == 0, result.output
        output = " ".join(result.output.split())
        assert "In use: contracts.csv (invented), as of 2026-10-01" in output
        assert "Against it: 0 new, 1 changed, 0 gone, and 0 the same" in output
        assert "2026-27 Jayson Tatum (BOS): $40,000,000 to $42,000,000" in output
        assert "“[a new site]” has not been imported before" in output, "never read as markup"
        assert f'fol contracts import "{candidate}" --source "[a new site]"' in output
        assert list((project / "data" / "raw").rglob("*contract*")) == snapshots

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

    @pytest.mark.parametrize("command", ["build", "check"])
    def test_a_project_without_its_archetypes_is_told_not_shown_a_traceback(
        self, project: Path, command: str
    ) -> None:
        (project / "configs" / "archetypes.yaml").unlink()
        result = runner.invoke(app, [command])
        assert result.exit_code == 1
        # The console folds a long path at its width, so compare without the line breaks.
        said = " ".join(result.output.split())
        assert "Error: configuration file not found" in said and "Traceback" not in said
        assert "archetypes.yaml" in said.replace(" ", "")

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
        assert "2 check errors, 5 check warnings" in result.output
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

        clock = Clock(NOW)
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
        clock = Clock(NOW)
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
        clock = Clock(NOW)
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


class TestApi:
    """The command that starts the HTTP API, with the server itself replaced."""

    @pytest.fixture
    def launched(self, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
        calls: list[dict] = []

        def run(command, *, cwd, env, check):
            calls.append({"command": command, "cwd": cwd, "env": env})
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cli.subprocess, "run", run)
        return calls

    def test_starts_uvicorn_on_the_app_factory_on_this_machine_only(
        self, project: Path, launched: list[dict]
    ) -> None:
        result = runner.invoke(app, ["api"])
        assert result.exit_code == 0, result.output
        assert "http://localhost:8000" in result.output
        assert "/docs" in result.output
        call = launched[0]
        assert call["command"][1:] == [
            "-m",
            "uvicorn",
            "front_office.server.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
        assert call["cwd"] == project
        assert call["env"][ENV_HOME] == str(project)

    def test_the_port_can_be_chosen(self, launched: list[dict]) -> None:
        result = runner.invoke(app, ["api", "--port", "8100"])
        assert result.exit_code == 0, result.output
        assert launched[0]["command"][-1] == "8100"

    def test_broken_settings_are_reported_before_anything_starts(
        self, project: Path, launched: list[dict]
    ) -> None:
        (project / "configs" / "api.yaml").write_text("version: 1\nkey: x\n", encoding="utf-8")
        result = runner.invoke(app, ["api"])
        assert result.exit_code == 1
        assert "invalid API settings" in result.output
        assert launched == []

    def test_a_failed_start_is_reported_through_the_exit_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=3)
        )
        assert runner.invoke(app, ["api"]).exit_code == 3


class TestRag:
    """fol rag: the documents' vector index (decision 0019), with Ollama scripted."""

    @pytest.fixture
    def documented(self, project: Path) -> Path:
        write_documents(project)
        return project

    def ollama_is(self, monkeypatch: pytest.MonkeyPatch, transport: ScriptedOllama) -> None:
        monkeypatch.setattr(
            rag_pipeline,
            "OllamaProvider",
            lambda host, timeout: OllamaProvider(transport=transport),
        )

    def test_status_before_a_build(self, documented: Path) -> None:
        result = runner.invoke(app, ["rag", "status"])
        assert result.exit_code == 0, result.output
        assert "Not built yet" in result.output
        assert "fol rag index" in result.output
        assert not (documented / "data" / "rag").exists()

    def test_index_builds_then_leaves_a_matching_index_alone(
        self, documented: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.ollama_is(monkeypatch, rag_ollama())
        result = runner.invoke(app, ["rag", "index"])
        assert result.exit_code == 0, result.output
        assert "Indexed 5 passages with nomic-embed-text" in result.output
        again = runner.invoke(app, ["rag", "index"])
        assert again.exit_code == 0, again.output
        assert "already matches the documents" in again.output
        status = runner.invoke(app, ["rag", "status"])
        assert "It matches the documents as they are now." in status.output

    def test_ollama_not_running_says_what_to_do(
        self, documented: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.ollama_is(monkeypatch, ScriptedOllama(down=True))
        result = runner.invoke(app, ["rag", "index"])
        assert result.exit_code == 1
        assert "Ollama is not answering" in result.output


class TestValueCommands:
    """fol value fit and fol value show, on the invented league."""

    SPEC_FILE = 'first_test_season: "2004-05"\nresamples: 100\n'

    @pytest.fixture
    def model_file(self, project: Path) -> Path:
        return project / "configs" / "models" / "player_value.json"

    @pytest.fixture
    def league_lab(self, project: Path, model_file: Path) -> None:
        """The invented league in the database, a specification that fits it, no model."""
        from front_office.domain.value_model import ValueSpec
        from tests.synthetic_lab import write_lab
        from tests.value_reference import planted_league

        (project / "configs" / "models" / "player_value.yaml").write_text(
            self.SPEC_FILE, encoding="utf-8"
        )
        model_file.unlink()
        write_lab(project, planted_league(ValueSpec(first_test_season="2004-05")))

    def test_show_prints_the_shipped_model_and_its_evidence(self) -> None:
        result = runner.invoke(app, ["value", "show"])
        assert result.exit_code == 0, result.output
        assert "Revision " in result.output and "Fitted on " in result.output
        assert "each predicted from the seasons before it" in result.output
        for heading in (
            "Predicting a team's net rating, out of sample",
            "The value model with one part left out",
            "Weights, with 95% intervals from resampling seasons",
        ):
            assert heading in result.output
        for row in ("Value model", "Players' PIE", "Team results", "score_eff", "new_player"):
            assert row in result.output, row
        assert "Replacement level -" in result.output
        assert "Next season's share of team minutes: RMSE" in result.output

    def test_show_without_a_model_says_how_to_fit_one(self, model_file: Path) -> None:
        model_file.unlink()
        result = runner.invoke(app, ["value", "show"])
        assert result.exit_code == 1
        assert "No value model has been fitted" in result.output
        assert "Run: fol value fit --write" in result.output

    def test_fit_shows_the_model_and_saves_nothing_unless_asked(
        self, league_lab: None, model_file: Path
    ) -> None:
        result = runner.invoke(app, ["value", "fit"])
        assert result.exit_code == 0, result.output
        # 110 players a season for nine seasons, less the one a season with nothing counted.
        assert (
            "Fitted on 80 team-seasons and 981 player-seasons, 2000-01 to 2008-09." in result.output
        )
        assert "Tested on 50 team-seasons, 2004-05 to 2008-09" in result.output
        assert "Not saved. To save it as revision 1: fol value fit --write" in result.output
        assert not model_file.exists()

    def test_fit_write_saves_the_model_and_says_how_to_apply_it(
        self, league_lab: None, model_file: Path
    ) -> None:
        result = runner.invoke(app, ["value", "fit", "--write"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "(revision 1). To apply it: fol build" in flat
        assert model_file.is_file()
        shown = runner.invoke(app, ["value", "show"])
        assert shown.exit_code == 0 and "Revision 1, fitted " in shown.output

    def test_fitting_again_without_a_change_writes_nothing(
        self, league_lab: None, model_file: Path
    ) -> None:
        assert runner.invoke(app, ["value", "fit", "--write"]).exit_code == 0
        written = model_file.read_text(encoding="utf-8")
        result = runner.invoke(app, ["value", "fit", "--write"])
        assert result.exit_code == 0, result.output
        assert "The same as revision 1, already on file. Nothing to write." in result.output
        assert model_file.read_text(encoding="utf-8") == written

    def test_a_changed_specification_becomes_the_next_revision(
        self, league_lab: None, project: Path, model_file: Path
    ) -> None:
        assert runner.invoke(app, ["value", "fit", "--write"]).exit_code == 0
        (project / "configs" / "models" / "player_value.yaml").write_text(
            self.SPEC_FILE + "ballast_minutes: 1500\n", encoding="utf-8"
        )
        preview = runner.invoke(app, ["value", "fit"])
        assert "Not saved. To save it as revision 2" in preview.output
        assert '"revision": 1' in model_file.read_text(encoding="utf-8")
        result = runner.invoke(app, ["value", "fit", "--write"])
        assert "(revision 2)" in " ".join(result.output.split())
        assert '"revision": 2' in model_file.read_text(encoding="utf-8")

    def test_fit_before_anything_is_built_says_so_and_creates_nothing(self, project: Path) -> None:
        result = runner.invoke(app, ["value", "fit"])
        assert result.exit_code == 1
        assert "Error: the database has not been built; run: fol refresh" in result.output
        assert not (project / "data" / "front_office.sqlite").exists()

    def test_fit_on_data_that_cannot_support_it_says_what_is_missing(
        self, project: Path, built_template
    ) -> None:
        (project / "data").mkdir(exist_ok=True)
        for path in (built_template[0] / "data").glob("front_office.sqlite*"):
            shutil.copy(path, project / "data" / path.name)
        result = runner.invoke(app, ["value", "fit", "--write"])
        assert result.exit_code == 1
        assert "Error: the value model is tested from 2006-07 and needs at least 3" in " ".join(
            result.output.split()
        )

    def test_an_invalid_specification_is_reported(self, league_lab: None, project: Path) -> None:
        (project / "configs" / "models" / "player_value.yaml").write_text(
            "ballast_minutes: 0\n", encoding="utf-8"
        )
        result = runner.invoke(app, ["value", "fit"])
        assert result.exit_code == 1
        assert "invalid value model specification" in result.output

    def test_value_alone_lists_its_commands(self) -> None:
        result = runner.invoke(app, ["value"])
        assert "fit" in result.output and "show" in result.output and "report" in result.output

    def test_report_prints_the_write_up(self, project: Path, built_template) -> None:
        (project / "data").mkdir(exist_ok=True)
        for path in (built_template[0] / "data").glob("front_office.sqlite*"):
            shutil.copy(path, project / "data" / path.name)
        result = runner.invoke(app, ["value", "report"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("# What a Player Is Worth")
        assert "## The test" in result.output and "## What it cannot tell you" in result.output
        assert not (project / "docs" / "research" / "PLAYER_VALUE.md").exists()

    def test_report_write_creates_the_document(self, project: Path, built_template) -> None:
        (project / "data").mkdir(exist_ok=True)
        for path in (built_template[0] / "data").glob("front_office.sqlite*"):
            shutil.copy(path, project / "data" / path.name)
        result = runner.invoke(app, ["value", "report", "--write"])
        assert result.exit_code == 0, result.output
        written = (project / "docs" / "research" / "PLAYER_VALUE.md").read_text(encoding="utf-8")
        assert written.startswith("# What a Player Is Worth") and "\r" not in written
        assert "of the value model)" in " ".join(result.output.split())

    def test_report_before_anything_is_built_creates_nothing(self, project: Path) -> None:
        result = runner.invoke(app, ["value", "report"])
        assert result.exit_code == 1
        assert "no data has been built yet; run: fol refresh" in result.output
        assert not (project / "data" / "front_office.sqlite").exists()

    def test_report_without_a_model_says_how_to_get_one(self, league_lab: None) -> None:
        result = runner.invoke(app, ["value", "report"])
        assert result.exit_code == 1
        assert "no player values to report" in " ".join(result.output.split())
        assert "fol value fit --write, then fol build" in " ".join(result.output.split())


class TestFitCommands:
    """fol fit test and fol fit show."""

    @pytest.fixture
    def evidence_file(self, project: Path) -> Path:
        return project / "configs" / "models" / "roster_fit.json"

    @pytest.fixture
    def fitted(self, project: Path, fitted_home: Path, evidence_file: Path) -> None:
        """The invented league with a fitted value model and no fit evidence yet."""
        shutil.copytree(fitted_home, project, dirs_exist_ok=True)
        evidence_file.unlink()  # the shipped evidence came with the copied configs

    def test_show_prints_the_shipped_evidence(self) -> None:
        result = runner.invoke(app, ["fit", "show"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "Revision 2, gathered " in flat
        assert "each corrected with weights fitted to the seasons before it" in flat
        for heading in (
            "Each measure alone, correcting the sum of the parts",
            "Every measure together",
            "The combined correction with one area left out",
        ):
            assert heading in flat, heading
        for row in (
            "Floor spacers",
            "Rim protectors",
            "Usage on the floor",
            "Sum of the parts alone",
        ):
            assert row in flat, row
        assert "No correction is applied to rosters" in flat

    def test_show_without_evidence_says_how_to_gather_it(self, evidence_file: Path) -> None:
        evidence_file.unlink()
        result = runner.invoke(app, ["fit", "show"])
        assert result.exit_code == 1
        assert "No roster fit evidence has been gathered" in result.output
        assert "Run: fol fit test --write" in result.output

    def test_test_shows_the_evidence_and_saves_nothing_unless_asked(
        self, fitted: None, evidence_file: Path
    ) -> None:
        result = runner.invoke(app, ["fit", "test"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "Tested on 30 team-seasons, 2006-07 to 2008-09" in flat
        assert "Not saved. To save it as revision 1: fol fit test --write" in flat
        assert not evidence_file.exists()

    def test_test_write_saves_and_a_second_run_writes_nothing(
        self, fitted: None, evidence_file: Path
    ) -> None:
        result = runner.invoke(app, ["fit", "test", "--write"])
        assert result.exit_code == 0, result.output
        assert "(revision 1)." in " ".join(result.output.split())
        assert evidence_file.is_file()
        again = runner.invoke(app, ["fit", "test", "--write"])
        assert again.exit_code == 0, again.output
        assert "The same as revision 1, already on file. Nothing to write." in " ".join(
            again.output.split()
        )
        shown = runner.invoke(app, ["fit", "show"])
        assert shown.exit_code == 0 and "Revision 1, gathered " in shown.output

    def test_test_without_a_database_says_so(self) -> None:
        result = runner.invoke(app, ["fit", "test"])
        assert result.exit_code == 1
        assert "Error: the database has not been built" in result.output


class TestPlayoffsCommands:
    """fol playoffs fit, show and report."""

    @pytest.fixture
    def model_file(self, project: Path) -> Path:
        return project / "configs" / "models" / "postseason.json"

    @pytest.fixture
    def played(self, project: Path, postseason_home: Path, model_file: Path) -> None:
        """The invented league with its playoffs and the value model on file, and no
        postseason model yet."""
        shutil.copytree(postseason_home, project, dirs_exist_ok=True)
        model_file.unlink()

    @pytest.fixture
    def prebuilt(self, project: Path, built_template) -> None:  # type: ignore[no-untyped-def]
        """The fixture store's database in place, as if `fol build` had been run."""
        (project / "data").mkdir(exist_ok=True)
        for path in (built_template[0] / "data").glob("front_office.sqlite*"):
            shutil.copy(path, project / "data" / path.name)

    def test_playoffs_alone_lists_its_commands(self) -> None:
        result = runner.invoke(app, ["playoffs"])
        assert "fit" in result.output and "show" in result.output and "report" in result.output

    def test_show_prints_the_shipped_model_and_how_it_did(self) -> None:
        result = runner.invoke(app, ["playoffs", "show"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "Revision 2, fitted " in flat
        assert "Series model: home advantage" in flat
        assert "Out of sample, 2006-07 to " in flat and "Through the bracket:" in flat
        assert "Tried beside the series model" in flat
        assert "Winning percentage instead of net rating" in flat

    def test_show_without_a_model_says_how_to_fit_one(self, model_file: Path) -> None:
        model_file.unlink()
        result = runner.invoke(app, ["playoffs", "show"])
        assert result.exit_code == 1
        assert "No postseason model has been fitted" in result.output
        assert "Run: fol playoffs fit --write" in result.output

    def test_fit_shows_the_model_and_saves_nothing_unless_asked(
        self, played: None, model_file: Path
    ) -> None:
        result = runner.invoke(app, ["playoffs", "fit"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "Fitted on " in flat and " series, 2000-01 to 2013-14" in flat
        assert "Not saved. To save it as revision 1: fol playoffs fit --write" in flat
        assert not model_file.exists()

    def test_fit_write_saves_and_a_second_run_writes_nothing(
        self, played: None, model_file: Path
    ) -> None:
        result = runner.invoke(app, ["playoffs", "fit", "--write"])
        assert result.exit_code == 0, result.output
        assert "(revision 1)." in " ".join(result.output.split())
        assert model_file.is_file()
        again = runner.invoke(app, ["playoffs", "fit", "--write"])
        assert again.exit_code == 0, again.output
        assert "The same as revision 1, already on file. Nothing to write." in " ".join(
            again.output.split()
        )
        shown = runner.invoke(app, ["playoffs", "show"])
        assert shown.exit_code == 0 and "Revision 1, fitted " in shown.output

    def test_fit_without_a_database_says_so(self) -> None:
        result = runner.invoke(app, ["playoffs", "fit"])
        assert result.exit_code == 1
        assert "Error: the database has not been built" in result.output

    def test_fit_on_data_that_cannot_support_it_says_what_is_missing(self, prebuilt: None) -> None:
        # The fixture store values two teams of one season: no game has both sides known.
        result = runner.invoke(app, ["playoffs", "fit"])
        assert result.exit_code == 1
        assert "Error: no decided playoff games and series with the inputs known" in result.output

    def test_report_prints_the_write_up(self, project: Path, prebuilt: None) -> None:
        result = runner.invoke(app, ["playoffs", "report"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("# How Far Can a Team Go?")
        assert "## How it was tested" in result.output
        assert "## What this does not say" in result.output
        assert not (project / "docs" / "research" / "POSTSEASON.md").exists()

    def test_report_write_creates_the_document(self, project: Path, prebuilt: None) -> None:
        result = runner.invoke(app, ["playoffs", "report", "--write"])
        assert result.exit_code == 0, result.output
        written = (project / "docs" / "research" / "POSTSEASON.md").read_text(encoding="utf-8")
        assert written.startswith("# How Far Can a Team Go?") and "\r" not in written
        assert "of the postseason model)" in " ".join(result.output.split())

    def test_report_before_anything_is_built_creates_nothing(self, project: Path) -> None:
        result = runner.invoke(app, ["playoffs", "report"])
        assert result.exit_code == 1
        assert "no data has been built yet; run: fol refresh" in result.output
        assert not (project / "data" / "front_office.sqlite").exists()

    def test_report_without_a_model_says_how_to_get_one(
        self, prebuilt: None, model_file: Path
    ) -> None:
        model_file.unlink()
        result = runner.invoke(app, ["playoffs", "report"])
        assert result.exit_code == 1
        assert "no postseason model to report" in " ".join(result.output.split())


class TestCurrent:
    @pytest.fixture
    def prebuilt(self, project: Path, built_template) -> None:  # type: ignore[no-untyped-def]
        """The fixture store's database in place, as if `fol build` had been run."""
        (project / "data").mkdir(exist_ok=True)
        for path in (built_template[0] / "data").glob("front_office.sqlite*"):
            shutil.copy(path, project / "data" / path.name)

    @pytest.fixture
    def asked(self, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
        """Stands in for the refresh: nothing is fetched, and what it was asked is kept."""
        from front_office.pipelines.current import CurrentRefresh, SourceRefresh

        calls: list[dict] = []

        def fake(settings, *, sources, force):  # type: ignore[no-untyped-def]
            calls.append({"sources": tuple(sources), "force": force})
            failed = "transactions" in sources and force
            return CurrentRefresh(
                tuple(
                    SourceRefresh(s, "failed" if failed else "stored", 3, f"[{s}] 3 lines")
                    for s in sources
                )
            )

        monkeypatch.setattr(cli, "refresh_current", fake)
        return calls

    def test_refresh_says_what_happened_to_each_source(self, asked: list[dict]) -> None:
        result = runner.invoke(app, ["current", "refresh"])
        assert result.exit_code == 0, result.output
        assert asked == [
            {"sources": ("games", "transactions", "injuries", "news"), "force": False}
        ], "the news feeds too (A7)"
        assert "injuries: [injuries] 3 lines" in result.output, "data is never read as markup"

    def test_refresh_one_source_by_force_and_a_failure_exits_non_zero(
        self, asked: list[dict]
    ) -> None:
        result = runner.invoke(app, ["current", "refresh", "-s", "transactions", "--force"])
        assert result.exit_code == 1
        assert asked == [{"sources": ("transactions",), "force": True}]
        assert "failed" in result.output

    def test_an_unknown_source_is_an_error_before_anything_is_fetched(self) -> None:
        result = runner.invoke(app, ["current", "refresh", "--source", "rumours"])
        assert result.exit_code == 1
        assert "no current source called ['rumours']" in result.output

    def test_status_before_anything_is_built(self, project: Path) -> None:
        result = runner.invoke(app, ["current", "status"])
        assert result.exit_code == 1
        assert "no data has been built yet" in result.output
        assert not (project / "data" / "front_office.sqlite").exists()

    def test_status_lists_every_source(self, prebuilt: None, project: Path) -> None:
        result = runner.invoke(app, ["current", "status"])
        assert result.exit_code == 0, result.output
        for source in ("games", "transactions", "injuries"):
            assert source in result.output
        assert "Never fetched." in result.output
        assert not (project / "data" / "current.sqlite").exists(), "reading creates nothing"
