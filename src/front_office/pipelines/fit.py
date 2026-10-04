"""Roster fit in the pipeline: every real team-season profiled, for reference.

Nothing is fitted here. The profiles rest on the value table and the archetype table, so
they are computed after both; where there is no value model the impact measures are
missing and the rest stands.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from front_office.config.archetypes import load_archetypes
from front_office.config.models import (
    load_fit_evidence,
    load_fit_spec,
    load_value_model,
    save_fit_evidence,
)
from front_office.config.settings import Settings
from front_office.domain.archetypes import ArchetypeSet
from front_office.domain.fit import COVERAGE_ROLES
from front_office.domain.fit_model import FitEvidence
from front_office.domain.schema import ContractViolationError, conform_frame
from front_office.domain.tables.fit import TEAM_FIT_PROFILES
from front_office.domain.tables.value import PLAYER_VALUE_SCORES
from front_office.modeling.fit import NotEnoughEvidence, fit_evidence, team_profiles
from front_office.pipelines.normalize import (
    ALL_SEASONS,
    BuildIssue,
    IssueSeverity,
    NormalizedTables,
)
from front_office.pipelines.value import utc_now
from front_office.storage import Database, StorageError, Warehouse

TABLE = TEAM_FIT_PROFILES.name
FIT_TEST_COMMAND = "fol fit test --write"
TESTED_FROM = (
    "player_seasons",
    "player_game_logs",
    "team_seasons",
    "players",
    "player_value_scores",
    "player_archetypes",
)


def fit_profiles(frames: dict[str, pd.DataFrame], archetypes: ArchetypeSet) -> pd.DataFrame:
    """Every row of ``team_fit_profiles`` the tables support, stamped with the versions
    of the rules and the model the profiles rest on."""
    profiles = team_profiles(frames, archetypes)
    versions = frames[PLAYER_VALUE_SCORES.name]["model_version"].dropna().unique()
    profiles["archetype_version"] = archetypes.label
    profiles["model_version"] = versions[0] if len(versions) else None
    return conform_frame(profiles, TEAM_FIT_PROFILES)


def add_fit_tables(tables: NormalizedTables, archetypes: ArchetypeSet | None) -> None:
    """Profile every team-season, adding the table and anything to report.

    Called after the value and archetype tables. Without archetype definitions the table
    is empty; with definitions that lack a role the counts refer to, a note says which.
    """
    frames = tables.frames
    frames[TABLE] = TEAM_FIT_PROFILES.empty_frame()
    if archetypes is None:
        return
    try:
        frames[TABLE] = fit_profiles(frames, archetypes)
    except ContractViolationError as error:
        tables.issues.append(BuildIssue(ALL_SEASONS, TABLE, str(error)))
        return
    missing = [role for role in COVERAGE_ROLES if role not in archetypes.keys]
    if missing and not frames[TABLE].empty:
        tables.issues.append(
            BuildIssue(
                ALL_SEASONS,
                TABLE,
                f"the fit measures count players filling {', '.join(missing)}, and the "
                "archetypes on file define no such role, so those counts are zero. Rename "
                "the role in configs/archetypes.yaml or add it back.",
                IssueSeverity.NOTE,
            )
        )


# --- the evidence, gathered on request -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FitTestReport:
    evidence: FitEvidence
    previous: FitEvidence | None
    """The evidence already on file, if there is any."""

    @property
    def changed(self) -> bool:
        """Whether this evidence differs from the file in anything but its stamp."""
        if self.previous is None:
            return True
        stamp = {"revision", "fitted_at"}
        return self.evidence.model_dump(exclude=stamp) != self.previous.model_dump(exclude=stamp)


class FitTestError(RuntimeError):
    """The fit evidence could not be gathered; the message says what is missing."""


def gather_fit_evidence(
    settings: Settings, *, now: Callable[[], datetime] = utc_now
) -> FitTestReport:
    """Gather the roster fit evidence on the built database, as ``configs/models``
    specifies it. Nothing is written."""
    spec = load_fit_spec(settings.config_dir)
    previous = load_fit_evidence(settings.config_dir)
    model = load_value_model(settings.config_dir)
    archetypes = load_archetypes(settings.config_dir)
    if model is None:
        raise FitTestError(
            "fit is measured beyond the value model's predictions, and no value model has "
            "been fitted; run: fol value fit --write, then fol build"
        )
    if not settings.database_path.is_file():
        raise FitTestError("the database has not been built; run: fol refresh")
    try:
        with Database(settings.database_path) as database:
            warehouse = Warehouse(database)
            tables = {name: warehouse.read(name) for name in TESTED_FROM}
        revision = 1 if previous is None else previous.revision + 1
        evidence = fit_evidence(tables, model, archetypes, spec, revision=revision, fitted_at=now())
    except (StorageError, NotEnoughEvidence) as error:
        raise FitTestError(str(error)) from error
    return FitTestReport(evidence, previous)


def write_fit_evidence(settings: Settings, evidence: FitEvidence) -> Path:
    return save_fit_evidence(settings.config_dir, evidence)
