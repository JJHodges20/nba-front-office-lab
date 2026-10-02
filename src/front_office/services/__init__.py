"""Service layer: the read-side API the workbench and CLI call.

Combines repositories with analytics and hands back display-ready results. The user
interface depends on this layer only. May import: domain, config, storage, analytics,
quality.
"""

from front_office.analytics.comparison import Qualification
from front_office.analytics.teams import POSTSEASON_RESULTS
from front_office.services.builder import (
    BuilderService,
    RosterCheck,
    RosterError,
    RosterSummary,
)
from front_office.services.contracts import ContractService
from front_office.services.explore import Relationship, relationship
from front_office.services.glossary import METRIC_CATALOGS, metric_glossary
from front_office.services.health import Gap, HealthService, SourceStatus
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
from front_office.storage import RosterNotFound

__all__ = [
    "DEFAULT_QUALIFICATION",
    "METRIC_CATALOGS",
    "POSTSEASON_RESULTS",
    "BuilderService",
    "ContractService",
    "Gap",
    "HealthService",
    "Lab",
    "LabNotBuilt",
    "LabStatus",
    "LeagueService",
    "PlayerProfile",
    "PlayerService",
    "PlayerTable",
    "Qualification",
    "Relationship",
    "RosterCheck",
    "RosterError",
    "RosterNotFound",
    "RosterSummary",
    "SourceStatus",
    "TeamProfile",
    "TeamService",
    "TeamTable",
    "Window",
    "metric_glossary",
    "relationship",
]
