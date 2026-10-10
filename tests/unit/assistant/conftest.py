"""Labs the assistant's tests read from: the fixture build, with and without the invented
contract file, opened once and never written to - and a private copy of the build for the
tests that fetch current information into it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from front_office.config import Settings, load_settings
from front_office.services import Lab


@pytest.fixture(scope="session")
def lab(built_readonly: Settings) -> Iterator[Lab]:
    with Lab(built_readonly) as opened:
        yield opened


@pytest.fixture(scope="session")
def contract_lab(contract_template: Path) -> Iterator[Lab]:
    with Lab(load_settings(contract_template)) as opened:
        yield opened


@pytest.fixture
def scratch(built_lab: Settings) -> Iterator[Lab]:
    """A private copy of the fixture build: its current-information cache may be filled."""
    with Lab(built_lab) as opened:
        yield opened
