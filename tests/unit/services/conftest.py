"""Labs shared by the service tests: opened once, and only ever read from."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import date

import pytest

from front_office.config import Settings, load_settings
from front_office.pipelines.build import build_database
from front_office.pipelines.contracts import import_contract_file
from front_office.services import Lab

TATUM, BROWN, VUCEVIC = 1628369, 1627759, 202696


@pytest.fixture(scope="session")
def lab(built_readonly: Settings) -> Iterator[Lab]:
    """The lab built from the fixture store, without contracts."""
    with Lab(built_readonly) as opened:
        yield opened


@pytest.fixture(scope="session")
def priced_lab(built_template, tmp_path_factory) -> Iterator[Lab]:
    """A built project with an invented contract file imported and built in."""
    root = tmp_path_factory.mktemp("priced") / "lab"
    shutil.copytree(built_template[0], root)
    settings = load_settings(root)
    path = root / "contracts.csv"
    path.write_text(
        "player_id,team,status,2026-27,2027-28\n"
        f"{TATUM},BOS,,40000000,44000000 PO\n"
        f"{BROWN},BOS,,30000000,\n"
        # Money a team still owes a player it waived is not that player's salary.
        f"{BROWN},NYK,dead,2000000,\n"
        f"{VUCEVIC},NYK,dead,5000000,\n",
        encoding="utf-8",
    )
    import_contract_file(settings, path, source_label="invented for tests", as_of=date(2026, 10, 1))
    assert build_database(settings).loaded
    with Lab(settings) as opened:
        yield opened
