"""A lab whose database holds the invented league instead of a build from the raw store.

For anything that reads the database and needs many seasons of every team: fitting a
model from it, or showing what a fitted model says. The fixture store cannot supply
that; see ``tests.league``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from front_office import __version__
from front_office.config import Settings, load_all_season_rules, load_archetypes, load_settings
from front_office.domain.archetypes import ArchetypeSet
from front_office.domain.schema import conform_frame
from front_office.domain.tables import REBUILT_TABLES
from front_office.domain.tables.value import PLAYER_ARCHETYPES, PLAYER_VALUE_SCORES
from front_office.domain.value_model import ValueModel
from front_office.modeling.archetypes import assign_archetypes
from front_office.modeling.value import score_players
from front_office.processing.cap_rules import cap_rules_frame
from front_office.storage import Database, OperationsLog, Warehouse
from tests.league import SyntheticLeague

BUILT_AT = datetime(2026, 10, 1, 12, 0, 0)


def league_frames(
    league: SyntheticLeague,
    model: ValueModel | None = None,
    archetypes: ArchetypeSet | None = None,
) -> dict[str, pd.DataFrame]:
    """Every rebuilt table for the league: the ones it has, and the rest empty.

    With ``model`` the players are valued by it; with ``archetypes`` they are given roles.
    """
    frames = {contract.name: contract.empty_frame() for contract in REBUILT_TABLES}
    frames.update(league.reference_tables())
    frames.update(league.tables())
    if model is not None:
        frames[PLAYER_VALUE_SCORES.name] = conform_frame(
            score_players(frames, model), PLAYER_VALUE_SCORES
        )
    if archetypes is not None:
        frames[PLAYER_ARCHETYPES.name] = conform_frame(
            assign_archetypes(frames, archetypes), PLAYER_ARCHETYPES
        )
    return frames


def write_lab(root: Path, league: SyntheticLeague, model: ValueModel | None = None) -> Settings:
    """Load the league into the database of the project at ``root``, as one build.

    ``root`` must already hold ``configs``. With ``model``, players are valued by it and
    given roles by the archetypes in those ``configs``.
    """
    settings = load_settings(root)
    archetypes = None if model is None else load_archetypes(settings.config_dir)
    frames = league_frames(league, model, archetypes)
    rules = list(load_all_season_rules(settings.season_rules_dir).values())
    frames["salary_cap_rules"] = cap_rules_frame(rules)
    with Database(settings.database_path) as database:
        with database.begin() as connection:
            rows = Warehouse(database).replace(connection, frames)
            OperationsLog(database).record_build(
                connection,
                {
                    "started_at": BUILT_AT,
                    "finished_at": BUILT_AT,
                    "lab_version": __version__,
                    "schema_fingerprint": database.current_fingerprint,
                    "status": "ok",
                    "rows_loaded": rows,
                    "build_errors": 0,
                    "build_notes": 0,
                    "check_errors": 0,
                    "check_warnings": 0,
                },
            )
    return settings
