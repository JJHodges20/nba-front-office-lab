"""Shared fixtures."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from front_office.config import Settings, load_all_season_rules, load_settings
from front_office.config.settings import ENV_DATA_DIR, ENV_HOME
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.datasets import NBA_STATS, partition_for
from front_office.domain.snapshots import Snapshot
from front_office.pipelines.normalize import NormalizedTables, normalize
from front_office.rawstore import RawStore

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


FIXTURE_RAW = REPO_ROOT / "tests" / "fixtures" / "raw"


@pytest.fixture(scope="session")
def fixture_store() -> RawStore:
    """The miniature raw store built by scripts/make_fixtures.py from real responses."""
    return RawStore(FIXTURE_RAW)


@pytest.fixture(scope="session")
def raw(fixture_store: RawStore) -> Callable[..., Snapshot]:
    """Fetch one fixture snapshot: ``raw(D.STANDINGS, Season(2025))``."""

    def fetch(dataset, season=None, season_type=None, team_id=None) -> Snapshot:
        partition = partition_for(dataset, season=season, season_type=season_type, team_id=team_id)
        snapshot = fixture_store.latest(NBA_STATS, dataset.value, partition)
        assert snapshot is not None, f"fixture missing: {dataset.value} {partition}"
        return snapshot

    return fetch


@pytest.fixture(scope="session")
def season_rules() -> list[SeasonRules]:
    """The cap rules shipped in configs/seasons."""
    return list(load_all_season_rules(REPO_ROOT / "configs" / "seasons").values())


@pytest.fixture(scope="session")
def normalized(fixture_store: RawStore, season_rules: list[SeasonRules]) -> NormalizedTables:
    """Every table built from the fixture store. Shared: copy a frame before changing it."""
    return normalize(fixture_store, season_rules=season_rules)


@pytest.fixture
def tables(normalized: NormalizedTables) -> dict[str, pd.DataFrame]:
    """A private copy of the normalised fixture tables that a test may freely break."""
    return {name: frame.copy() for name, frame in normalized.frames.items()}
