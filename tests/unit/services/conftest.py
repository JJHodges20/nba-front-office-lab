"""Labs shared by the service tests.

``lab``, ``priced_lab`` and ``contract_lab`` are opened once and only ever read from.
A test that changes anything takes ``scratch_lab``, a private copy.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from front_office.config import Settings, load_settings
from front_office.services import Lab
from tests.conftest import with_contracts
from tests.helpers import (  # noqa: F401  (re-exported for the tests in this directory)
    ABDELNABY,
    ANUNOBY,
    BOS,
    BRIDGES,
    BROWN,
    BRUNSON,
    CONTRACT_FILE,
    HART,
    NYK,
    PRITCHARD,
    TATUM,
    TOWNS,
    VUCEVIC,
    WHITE,
)


@pytest.fixture(scope="session")
def lab(built_readonly: Settings) -> Iterator[Lab]:
    """The lab built from the fixture store, without contracts."""
    with Lab(built_readonly) as opened:
        yield opened


@pytest.fixture(scope="session")
def priced_lab(built_template, tmp_path_factory) -> Iterator[Lab]:
    """A built project with a small invented contract file imported and built in."""
    contract_file = (
        "player_id,team,status,2026-27,2027-28\n"
        f"{TATUM},BOS,,40000000,44000000 PO\n"
        f"{BROWN},BOS,,30000000,\n"
        # Money a team still owes a player it waived is not that player's salary.
        f"{BROWN},NYK,dead,2000000,\n"
        f"{VUCEVIC},NYK,dead,5000000,\n"
    )
    root = tmp_path_factory.mktemp("priced") / "lab"
    with Lab(with_contracts(built_template[0], root, contract_file)) as opened:
        yield opened


@pytest.fixture(scope="session")
def contract_lab(contract_template: Path) -> Iterator[Lab]:
    """The lab with ``CONTRACT_FILE`` built in. Read from it; never write to it."""
    with Lab(load_settings(contract_template)) as opened:
        yield opened


@pytest.fixture
def scratch_lab(contract_template: Path, tmp_path: Path) -> Iterator[Lab]:
    """A private copy of the lab with contracts, for tests that change something."""
    target = tmp_path / "scratch"
    shutil.copytree(contract_template, target)
    with Lab(load_settings(target)) as opened:
        yield opened


@pytest.fixture(scope="session")
def value_lab(value_home: Path) -> Iterator[Lab]:
    """The invented league valued by planted weights. Read from it; never write to it."""
    with Lab(load_settings(value_home)) as opened:
        yield opened
