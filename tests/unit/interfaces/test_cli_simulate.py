"""fol simulate fit, show and report."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from front_office.config.settings import ENV_HOME
from front_office.interfaces.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _use_throwaway_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_HOME, str(project))
    monkeypatch.setenv("COLUMNS", "200")


@pytest.fixture
def model_file(project: Path) -> Path:
    return project / "configs" / "models" / "simulator.json"


@pytest.fixture
def played(project: Path, simulator_home: Path, model_file: Path) -> None:
    """The invented league with its playoffs and the value and postseason models on file,
    and no simulator parameters yet."""
    shutil.copytree(simulator_home, project, dirs_exist_ok=True)
    model_file.unlink()


@pytest.fixture
def prebuilt(project: Path, built_template) -> None:  # type: ignore[no-untyped-def]
    """The fixture store's database in place, as if `fol build` had been run."""
    (project / "data").mkdir(exist_ok=True)
    for path in (built_template[0] / "data").glob("front_office.sqlite*"):
        shutil.copy(path, project / "data" / path.name)


def test_simulate_alone_lists_its_commands() -> None:
    result = runner.invoke(app, ["simulate"])
    assert "fit" in result.output and "show" in result.output and "report" in result.output


def test_show_prints_the_shipped_parameters_and_the_wins_test() -> None:
    result = runner.invoke(app, ["simulate", "show"])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "Revision 2, measured " in flat
    assert "against value model r2 and postseason model p2" in flat
    assert "Wins test on 600 team-seasons, 2006-07 to 2025-26" in flat
    assert "the 80% interval held" in flat


def test_show_without_parameters_says_how_to_measure_them(model_file: Path) -> None:
    model_file.unlink()
    result = runner.invoke(app, ["simulate", "show"])
    assert result.exit_code == 1
    assert "No simulator parameters have been measured" in result.output
    assert "Run: fol simulate fit --write" in result.output


def test_fit_shows_the_parameters_and_saves_nothing_unless_asked(
    played: None, model_file: Path
) -> None:
    result = runner.invoke(app, ["simulate", "fit"])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "Measured on 420 team-seasons" in flat and "2000-01 to 2013-14" in flat
    assert "Not saved. To save it as revision 1: fol simulate fit --write" in flat
    assert not model_file.exists()


def test_fit_write_saves_and_a_second_run_writes_nothing(played: None, model_file: Path) -> None:
    result = runner.invoke(app, ["simulate", "fit", "--write"])
    assert result.exit_code == 0, result.output
    assert "(revision 1)." in " ".join(result.output.split())
    assert model_file.is_file()
    again = runner.invoke(app, ["simulate", "fit", "--write"])
    assert again.exit_code == 0, again.output
    assert "The same as revision 1, already on file. Nothing to write." in " ".join(
        again.output.split()
    )
    shown = runner.invoke(app, ["simulate", "show"])
    assert shown.exit_code == 0 and "Revision 1, measured " in shown.output


def test_fit_without_a_database_says_so() -> None:
    result = runner.invoke(app, ["simulate", "fit"])
    assert result.exit_code == 1
    assert "Error: the database has not been built" in result.output


def test_fit_measures_the_fixture_store_and_saves_nothing(project: Path, prebuilt: None) -> None:
    on_file = project / "configs" / "models" / "simulator.json"
    shipped = on_file.read_bytes()
    result = runner.invoke(app, ["simulate", "fit"])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "Measured on" in flat and "Wins test on" in flat
    assert "Not saved. To save it as revision 3: fol simulate fit --write" in flat
    assert on_file.read_bytes() == shipped


def test_report_prints_the_write_up(project: Path, prebuilt: None) -> None:
    result = runner.invoke(app, ["simulate", "report"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("# What a Season Could Bring")
    assert "## The wins test" in result.output
    assert "## The season ahead, as drawn: 2026-27" in result.output
    assert not (project / "docs" / "research" / "SIMULATOR.md").exists()


def test_report_write_creates_the_document(project: Path, prebuilt: None) -> None:
    result = runner.invoke(app, ["simulate", "report", "--write"])
    assert result.exit_code == 0, result.output
    written = (project / "docs" / "research" / "SIMULATOR.md").read_text(encoding="utf-8")
    assert written.startswith("# What a Season Could Bring") and "\r" not in written
    assert "of the simulator)" in " ".join(result.output.split())


def test_report_before_anything_is_built_creates_nothing(project: Path) -> None:
    result = runner.invoke(app, ["simulate", "report"])
    assert result.exit_code == 1
    assert "no data has been built yet; run: fol refresh" in result.output
    assert not (project / "data" / "front_office.sqlite").exists()


def test_report_without_parameters_says_how_to_get_them(prebuilt: None, model_file: Path) -> None:
    model_file.unlink()
    result = runner.invoke(app, ["simulate", "report"])
    assert result.exit_code == 1
    assert "no simulator to report" in " ".join(result.output.split())
