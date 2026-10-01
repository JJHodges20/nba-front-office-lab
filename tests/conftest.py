"""Shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.config import Settings, load_settings
from front_office.config.settings import ENV_DATA_DIR, ENV_HOME

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's own FOL_* variables from steering a test."""
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_DATA_DIR, raising=False)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway project root holding a copy of the real ``configs`` directory."""
    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    return tmp_path


@pytest.fixture
def settings(project: Path) -> Settings:
    """Settings for the throwaway project, so nothing touches the real data directory."""
    return load_settings(project)
