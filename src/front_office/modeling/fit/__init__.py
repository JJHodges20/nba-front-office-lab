"""Roster fit: a roster described in the roadmap's areas of fit, and whether that
description says anything the sum of its players' impacts does not."""

from front_office.modeling.fit.catalog import AREAS, FIT_METRICS
from front_office.modeling.fit.evidence import (
    LAG,
    TESTED,
    NotEnoughEvidence,
    adjustment,
    fit_evidence,
)
from front_office.modeling.fit.profile import (
    FILLS,
    PROFILE_COLUMNS,
    TEAM_COLUMNS,
    fills_column,
    player_profiles,
    rotation_profile,
    team_profiles,
)

__all__ = [
    "AREAS",
    "FILLS",
    "FIT_METRICS",
    "LAG",
    "TESTED",
    "NotEnoughEvidence",
    "adjustment",
    "fit_evidence",
    "PROFILE_COLUMNS",
    "TEAM_COLUMNS",
    "fills_column",
    "player_profiles",
    "rotation_profile",
    "team_profiles",
]
