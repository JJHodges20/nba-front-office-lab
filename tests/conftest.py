"""Shared fixtures."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from front_office.config import (
    Settings,
    fit_evidence_path,
    fit_spec_path,
    load_all_season_rules,
    load_settings,
    save_value_model,
)
from front_office.config.settings import ENV_DATA_DIR, ENV_HOME
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.datasets import NBA_STATS, partition_for
from front_office.domain.snapshots import Snapshot
from front_office.domain.value_model import ValueModel, ValueSpec
from front_office.pipelines.build import BuildReport, build_database
from front_office.pipelines.contracts import import_contract_file
from front_office.pipelines.normalize import NormalizedTables, normalize
from front_office.rawstore import RawStore
from tests.helpers import CONTRACT_FILE

REPO_ROOT = Path(__file__).resolve().parents[1]

# Outside a running server Streamlit logs these two warnings again and again: when a
# cached function is defined or its cache cleared, and when one is called. They say
# nothing about the workbench and bury the test output. Installed here, before anything
# imports the workbench, because the first of them fires at import.
BARE_MODE_NOISE = {
    "streamlit.runtime.caching.cache_data_api": "No runtime found",
    "streamlit.runtime.scriptrunner_utils.script_run_context": "missing ScriptRunContext",
}
for _logger, _phrase in BARE_MODE_NOISE.items():
    logging.getLogger(_logger).addFilter(
        lambda record, phrase=_phrase: phrase not in record.getMessage()
    )


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


BUILT_AT = datetime(2026, 10, 1, 12, 0, 0)
BUILD_TOOK = timedelta(seconds=9)


@pytest.fixture(scope="session")
def built_template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, BuildReport]:
    """A project built once from the fixture store, with the report of that build.

    Building takes a couple of seconds, so it is done once per test run. Tests that only
    read use ``built_readonly``; tests that change anything take a copy with
    ``built_lab``.
    """
    root = tmp_path_factory.mktemp("built-lab")
    shutil.copytree(REPO_ROOT / "configs", root / "configs")
    shutil.copytree(FIXTURE_RAW, root / "data" / "raw")
    moments = iter([BUILT_AT, BUILT_AT + BUILD_TOOK])
    report = build_database(load_settings(root), now=lambda: next(moments))
    assert report.loaded
    return root, report


@pytest.fixture(scope="session")
def built_readonly(built_template: tuple[Path, BuildReport]) -> Settings:
    """The shared built project. Read from it; never write to it."""
    return load_settings(built_template[0])


@pytest.fixture(scope="session")
def first_build_report(built_template: tuple[Path, BuildReport]) -> BuildReport:
    return built_template[1]


@pytest.fixture
def built_lab(built_template: tuple[Path, BuildReport], tmp_path: Path) -> Settings:
    """A private copy of the built project that a test may change freely."""
    target = tmp_path / "built"
    shutil.copytree(built_template[0], target)
    return load_settings(target)


def with_contracts(template: Path, target: Path, contract_file: str) -> Settings:
    """Copy a built project, import a contract file into the copy, and rebuild it."""
    shutil.copytree(template, target)
    settings = load_settings(target)
    path = target / "contracts.csv"
    path.write_text(contract_file, encoding="utf-8")
    import_contract_file(settings, path, source_label="invented for tests", as_of=date(2026, 10, 1))
    assert build_database(settings).loaded
    return settings


@pytest.fixture(scope="session")
def contract_template(
    built_template: tuple[Path, BuildReport], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """A built project holding the invented contract file. Never written to: copy it."""
    root = tmp_path_factory.mktemp("contracts") / "lab"
    with_contracts(built_template[0], root, CONTRACT_FILE)
    return root


# --- the invented league, for anything that needs a fitted model's output -----------------

VALUE_SPEC = ValueSpec(first_test_season="2004-05", resamples=100)


@pytest.fixture(scope="session")
def value_league():  # type: ignore[no-untyped-def]
    """The invented league, its team ratings planted by the reference model."""
    from tests.value_reference import planted_league

    return planted_league(VALUE_SPEC)


@pytest.fixture(scope="session")
def value_model() -> ValueModel:
    """The planted weights as a fitted model, with a replacement level of -2."""
    from tests.value_reference import planted_model

    return planted_model(VALUE_SPEC, replacement_level=-2.0)


@pytest.fixture(scope="session")
def value_home(value_league, value_model: ValueModel, tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """A project whose database is the invented league, valued by the planted model,
    which is also the model on file. Read from it; never write to it."""
    from tests.synthetic_lab import write_lab

    home = tmp_path_factory.mktemp("value") / "lab"
    shutil.copytree(REPO_ROOT / "configs", home / "configs")
    save_value_model(home / "configs", value_model)
    write_lab(home, value_league, value_model)
    return home


QUICK_FIT_SPEC = 'first_test_season: "2006-07"\nmin_training_seasons: 2\nresamples: 100\n'
"""A roster fit specification that tests three seasons of the invented league quickly."""


@pytest.fixture(scope="session")
def fitted_home(tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """A project whose database is an invented league with luck in it, valued by a model
    *fitted* on it - so the model carries a test - with a quick fit specification and no
    fit evidence on file. Read from it; never write to it."""
    from datetime import datetime

    from front_office.modeling.value import fit_value_model
    from tests.synthetic_lab import write_lab
    from tests.value_reference import planted_league

    home = tmp_path_factory.mktemp("fitted") / "lab"
    shutil.copytree(REPO_ROOT / "configs", home / "configs")
    league = planted_league(VALUE_SPEC, noise=1.0)
    model = fit_value_model(
        league.tables(), VALUE_SPEC, revision=1, fitted_at=datetime(2026, 10, 1, 12, 0)
    )
    save_value_model(home / "configs", model)
    fit_spec_path(home / "configs").write_text(QUICK_FIT_SPEC, encoding="utf-8")
    fit_evidence_path(home / "configs").unlink()
    write_lab(home, league, model)
    return home


def invented_salary(player_id: int, projected_wins: float) -> int:
    """A salary that follows a player's projection, with a little that does not."""
    worth = max(float(projected_wins), 0.0)
    return 1_500_000 + int(round(7_000_000 * worth)) + (int(player_id) % 7) * 300_000


@pytest.fixture(scope="session")
def optimizer_home(value_home: Path, tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """The invented league valued by the planted model, with every projected player under
    an invented contract for the season ahead. Read from it; never write to it."""
    from front_office.services import Lab
    from tests.synthetic_lab import pay_players

    home = tmp_path_factory.mktemp("optimizer") / "lab"
    shutil.copytree(value_home, home)
    settings = load_settings(home)
    with Lab(settings) as lab:
        ahead = lab.value.projections()
        season = lab.value.status().upcoming
        salaries = {
            int(player): invented_salary(int(player), row["projected_wins"])
            for player, row in ahead.iterrows()
        }
        teams = {int(player): int(team) for player, team in ahead["team_id"].dropna().items()}
    pay_players(settings, season, salaries, teams)
    return home
