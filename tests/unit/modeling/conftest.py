"""Leagues and specifications shared by the modeling tests."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from front_office.domain.value_model import ValueModel, ValueSpec
from front_office.modeling.value import fit_value_model
from tests.league import SyntheticLeague
from tests.value_reference import planted_league

FITTED_AT = datetime(2026, 10, 1, 12, 0)


@pytest.fixture(scope="session")
def spec() -> ValueSpec:
    """Tested from the fifth of nine seasons, with few enough resamples to be quick."""
    return ValueSpec(first_test_season="2004-05", resamples=300)


@pytest.fixture(scope="session")
def exact_league(spec: ValueSpec) -> SyntheticLeague:
    """Team ratings follow the planted weights with nothing added. Never changed."""
    return planted_league(spec)


@pytest.fixture(scope="session")
def exact_tables(exact_league: SyntheticLeague) -> dict[str, pd.DataFrame]:
    return exact_league.tables()


@pytest.fixture(scope="session")
def exact_model(exact_tables: dict[str, pd.DataFrame], spec: ValueSpec) -> ValueModel:
    return fit_value_model(exact_tables, spec, revision=1, fitted_at=FITTED_AT)


@pytest.fixture(scope="session")
def noisy_league(spec: ValueSpec) -> SyntheticLeague:
    """The same weights with luck added: 30 teams over 14 seasons."""
    return planted_league(spec, noise=1.5, seed=3, teams=30, seasons=14)


@pytest.fixture(scope="session")
def noisy_model(noisy_league: SyntheticLeague, spec: ValueSpec) -> ValueModel:
    return fit_value_model(noisy_league.tables(), spec, revision=1, fitted_at=FITTED_AT)
