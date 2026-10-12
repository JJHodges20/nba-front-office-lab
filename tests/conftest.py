"""Shared fixtures."""

from __future__ import annotations

import ipaddress
import logging
import shutil
import socket
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from front_office.config import (
    Settings,
    fit_evidence_path,
    fit_spec_path,
    load_all_season_rules,
    load_settings,
    postseason_model_path,
    postseason_spec_path,
    save_value_model,
    simulator_model_path,
    simulator_spec_path,
)
from front_office.config.settings import ENV_DATA_DIR, ENV_HOME
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.datasets import NBA_STATS, partition_for
from front_office.domain.snapshots import Snapshot
from front_office.domain.value_model import ValueModel, ValueSpec
from front_office.pipelines.build import BuildReport, build_database
from front_office.pipelines.contracts import import_contract_file
from front_office.pipelines.normalize import NormalizedTables, normalize
from front_office.providers.web import KEY_VARIABLE
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


LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
"""Where a test may connect: this machine - asyncio's own pipes, a test's local server."""


class NetworkReached(Exception):
    """Not an ``OSError``: no provider may take it for a failed fetch and carry on."""


@pytest.fixture(autouse=True)
def _no_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[str]]:
    """Nothing in the suite reaches the network outside the ``network`` and ``ollama``
    markers (A9 network audit): a connection anywhere but this machine, or a name looked up,
    fails the test that made it - even where the code under test caught the error."""
    if request.node.get_closest_marker("network") or request.node.get_closest_marker("ollama"):
        yield []
        return
    reached: list[str] = []
    connect, connect_ex, lookup = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
    )

    def outside(host: object) -> bool:
        if not isinstance(host, str) or host in LOOPBACK:
            return False
        try:
            return not ipaddress.ip_address(host.split("%")[0]).is_loopback
        except ValueError:
            return True  # a name: looking it up asks the network

    def refuse(what: object, opened: socket.socket | None = None) -> NetworkReached:
        reached.append(repr(what))
        if opened is not None:
            opened.close()  # the caller expected an OSError, and would leave it open
        return NetworkReached(f"a test reached the network: {what!r}")

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if isinstance(address, tuple) and outside(address[0]):
            raise refuse(address, self)
        return connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        if isinstance(address, tuple) and outside(address[0]):
            raise refuse(address, self)
        return connect_ex(self, address)

    def guarded_lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else host
        if outside(name):
            try:
                ipaddress.ip_address(name.split("%")[0])  # an address is looked up nowhere
            except ValueError:
                raise refuse(host) from None
        return lookup(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_lookup)
    yield reached
    assert not reached, f"the test reached the network: {', '.join(reached)}"


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's own FOL_* variables from steering a test - the web search key
    among them: no test may search the web with the user's account."""
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_DATA_DIR, raising=False)
    monkeypatch.delenv(KEY_VARIABLE, raising=False)


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


PRICED_CONTRACT_FILE = REPO_ROOT / "tests" / "assistant" / "fixtures" / "priced_contracts.csv"
"""An invented 2026-27 salary for every player the fixture build projects into that season:
about $1.25M, plus $6M for each projected win, plus a quarter of a million times the
player id's remainder after dividing by 7, rounded to $10,000. With every projected player
priced, the optimizer can build whole rosters (decision 0018, A5)."""


@pytest.fixture(scope="session")
def priced_template(
    built_template: tuple[Path, BuildReport], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """A built project holding the priced contract file. Never written to: copy it."""
    root = tmp_path_factory.mktemp("priced") / "lab"
    with_contracts(built_template[0], root, PRICED_CONTRACT_FILE.read_text(encoding="utf-8"))
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


QUICK_POSTSEASON_SPEC = 'first_test_season: "2006-07"\nmin_training_seasons: 3\nresamples: 100\nkept_draws: 40\nformats: []\n'
"""A postseason specification that tests eight seasons of the invented league quickly."""


@pytest.fixture(scope="session")
def postseason_league():  # type: ignore[no-untyped-def]
    """A thirty-team invented league whose playoffs were played by a planted series model:
    the league, the planted value model it is valued by, and the frames a build would hold."""
    from tests.postseason_reference import postseason_league

    return postseason_league(VALUE_SPEC)


@pytest.fixture(scope="session")
def postseason_home(postseason_league, tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """A project whose database is the thirty-team league with its playoffs, valued by the
    planted model, with the postseason model fitted on it and on file under the quick
    specification. Read from it; never write to it."""
    from front_office.pipelines.postseason import fit_postseason, write_postseason_model
    from tests.synthetic_lab import write_lab

    league, model, _ = postseason_league
    home = tmp_path_factory.mktemp("postseason") / "lab"
    shutil.copytree(REPO_ROOT / "configs", home / "configs")
    save_value_model(home / "configs", model)
    postseason_spec_path(home / "configs").write_text(QUICK_POSTSEASON_SPEC, encoding="utf-8")
    postseason_model_path(home / "configs").unlink()
    settings = write_lab(home, league, model)
    report = fit_postseason(settings, now=lambda: datetime(2026, 10, 5, 12, 0))
    write_postseason_model(settings, report.model)
    return home


QUICK_SIMULATOR_SPEC = "noise_seasons: 5\ntest_simulations: 200\nsimulations: 2000\n"
"""A simulator specification that measures and tests quickly on the invented league."""


@pytest.fixture(scope="session")
def simulator_home(postseason_home: Path, tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """A copy of the postseason project with the simulator parameters measured on it and
    on file under the quick specification. Read from it; never write to it."""
    from front_office.pipelines.simulator import fit_simulator, write_simulator_model

    home = tmp_path_factory.mktemp("simulator") / "lab"
    shutil.copytree(postseason_home, home)
    simulator_spec_path(home / "configs").write_text(QUICK_SIMULATOR_SPEC, encoding="utf-8")
    simulator_model_path(home / "configs").unlink()
    settings = load_settings(home)
    report = fit_simulator(settings, now=lambda: datetime(2026, 10, 5, 12, 0))
    write_simulator_model(settings, report.model)
    return home
