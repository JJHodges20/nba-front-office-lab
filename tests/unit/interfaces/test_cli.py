from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from front_office import __version__
from front_office.config.settings import ENV_HOME
from front_office.interfaces.cli.app import app, money

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
