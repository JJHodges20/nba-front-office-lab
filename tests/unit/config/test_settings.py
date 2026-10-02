from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config.settings import (
    ENV_DATA_DIR,
    ENV_HOME,
    ConfigError,
    find_project_root,
    load_settings,
)


def write_base(project: Path, text: str) -> None:
    (project / "configs" / "base.yaml").write_text(text, encoding="utf-8")


def test_paths_resolve_against_the_project_root(project: Path) -> None:
    settings = load_settings(project)
    assert settings.project_root == project.resolve()
    assert settings.config_dir == project.resolve() / "configs"
    assert settings.data_dir == project.resolve() / "data"
    assert settings.raw_dir == settings.data_dir / "raw"
    assert settings.imports_dir == settings.data_dir / "imports"
    assert settings.exports_dir == settings.data_dir / "exports"
    assert settings.database_path == settings.data_dir / "front_office.sqlite"
    assert settings.season_rules_dir == settings.config_dir / "seasons"


def test_shipped_defaults(project: Path) -> None:
    settings = load_settings(project)
    assert settings.history_start.label == "1996-97"
    assert settings.player_history_start.label == "1996-97"
    assert settings.seasons.player_detail_seasons == 3


def test_player_history_follows_team_history_unless_it_starts_later(project: Path) -> None:
    write_base(project, "seasons:\n  history_start: '2010-11'\n")
    assert load_settings(project).player_history_start.label == "2010-11"
    write_base(project, "seasons:\n  history_start: '2010-11'\n  player_history_start: '2015-16'\n")
    settings = load_settings(project)
    assert (settings.history_start.label, settings.player_history_start.label) == (
        "2010-11",
        "2015-16",
    )


def test_data_dir_can_be_overridden_by_environment(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv(ENV_DATA_DIR, str(elsewhere))
    assert load_settings(project).data_dir == elsewhere.resolve()


def test_absolute_data_dir_is_kept(project: Path, tmp_path: Path) -> None:
    target = (tmp_path / "abs-data").resolve()
    write_base(project, f"paths:\n  data_dir: '{target.as_posix()}'\n")
    assert load_settings(project).data_dir == target


def test_an_empty_base_file_uses_defaults(project: Path) -> None:
    write_base(project, "")
    settings = load_settings(project)
    assert settings.data_dir == project.resolve() / "data"
    assert settings.seasons.history_start == "1996-97"


@pytest.mark.parametrize(
    "text",
    [
        "paths:\n  data_dirr: data\n",  # misspelt key
        "seasons:\n  history_start: '1996'\n",  # not a season label
        "seasons:\n  player_detail_seasons: 0\n",
        "seasons:\n  player_history_start: '1990-91'\n",  # before the teams' history
        "seasons:\n  player_history_start: 'recent'\n",
        "- just\n- a list\n",
        "paths: [unclosed\n",
    ],
)
def test_invalid_base_files_are_rejected(project: Path, text: str) -> None:
    write_base(project, text)
    with pytest.raises(ConfigError):
        load_settings(project)


def test_a_missing_base_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path)


def test_project_root_is_found_from_a_nested_directory(project: Path) -> None:
    nested = project / "src" / "deep" / "down"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == project.resolve()


def test_environment_home_takes_precedence(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_HOME, str(project))
    assert find_project_root(tmp_path / "unrelated") == project.resolve()


def test_environment_home_must_hold_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    with pytest.raises(ConfigError, match=ENV_HOME):
        find_project_root()


def test_falls_back_to_the_source_checkout(tmp_path: Path, repo_root: Path) -> None:
    # tmp_path has no configs/ above it, so discovery falls back to this repository.
    assert find_project_root(tmp_path) == repo_root
