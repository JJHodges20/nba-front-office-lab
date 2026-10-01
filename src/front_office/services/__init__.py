"""Service layer: the read-side API the workbench and CLI call.

Combines repositories with analytics and hands back display-ready results. The user
interface depends on this layer only. May import: domain, config, storage, analytics,
quality.
"""

from front_office.analytics.comparison import Qualification
from front_office.services.glossary import METRIC_CATALOGS, metric_glossary
from front_office.services.lab import Lab, LabNotBuilt, LabStatus
from front_office.services.league import LeagueService
from front_office.services.players import (
    DEFAULT_QUALIFICATION,
    PlayerProfile,
    PlayerService,
    PlayerTable,
)
from front_office.services.teams import TeamProfile, TeamService, TeamTable
from front_office.services.window import Window

__all__ = [
    "DEFAULT_QUALIFICATION",
    "METRIC_CATALOGS",
    "Lab",
    "LabNotBuilt",
    "LabStatus",
    "LeagueService",
    "PlayerProfile",
    "PlayerService",
    "PlayerTable",
    "Qualification",
    "TeamProfile",
    "TeamService",
    "TeamTable",
    "Window",
    "metric_glossary",
]
