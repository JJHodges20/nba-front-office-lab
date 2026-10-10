"""Service layer: the read-side API the workbench and CLI call.

Combines repositories with analytics and hands back display-ready results. The user
interface depends on this layer only. May import: domain, config, storage, analytics,
quality, modeling.
"""

from front_office.analytics.comparison import Qualification
from front_office.analytics.teams import POSTSEASON_RESULTS
from front_office.domain.eras import Era
from front_office.services.benchmarks import (
    MEASURES,
    BenchmarkService,
    EraView,
    Floor,
    Measure,
    StageSummary,
    floor,
)
from front_office.services.builder import (
    BuilderService,
    RosterCheck,
    RosterError,
    RosterSummary,
)
from front_office.services.contracts import ContractService
from front_office.services.current import CurrentDataService, CurrentSource
from front_office.services.explore import Relationship, relationship
from front_office.services.fit import FitReport, FitService, FitStatus, SumOfParts
from front_office.services.glossary import METRIC_CATALOGS, metric_glossary
from front_office.services.health import Gap, HealthService, SourceStatus
from front_office.services.lab import Lab, LabNotBuilt, LabStatus
from front_office.services.league import LeagueService
from front_office.services.optimizer import (
    OptimizerError,
    OptimizerReport,
    OptimizerService,
    OptimizerStatus,
    RosterPlan,
)
from front_office.services.players import (
    DEFAULT_QUALIFICATION,
    PlayerProfile,
    PlayerService,
    PlayerTable,
)
from front_office.services.postseason import (
    BracketReport,
    Outlook,
    PostseasonError,
    PostseasonService,
    PostseasonStatus,
    SubjectOutlook,
    probability_key,
)
from front_office.services.simulator import (
    Outcome,
    ScenarioReport,
    SimulatorError,
    SimulatorService,
    SimulatorStatus,
)
from front_office.services.teams import TeamProfile, TeamService, TeamTable
from front_office.services.value import ModelCard, ValueForMoney, ValueService, ValueStatus
from front_office.services.window import Window
from front_office.storage import RosterNotFound

__all__ = [
    "DEFAULT_QUALIFICATION",
    "MEASURES",
    "METRIC_CATALOGS",
    "POSTSEASON_RESULTS",
    "BenchmarkService",
    "BracketReport",
    "BuilderService",
    "ContractService",
    "CurrentDataService",
    "CurrentSource",
    "Era",
    "EraView",
    "FitReport",
    "FitService",
    "FitStatus",
    "Floor",
    "Gap",
    "HealthService",
    "Lab",
    "LabNotBuilt",
    "LabStatus",
    "LeagueService",
    "Measure",
    "ModelCard",
    "OptimizerError",
    "OptimizerReport",
    "OptimizerService",
    "OptimizerStatus",
    "Outcome",
    "Outlook",
    "PlayerProfile",
    "PlayerService",
    "PlayerTable",
    "PostseasonError",
    "PostseasonService",
    "PostseasonStatus",
    "Qualification",
    "Relationship",
    "RosterCheck",
    "RosterError",
    "RosterNotFound",
    "RosterPlan",
    "RosterSummary",
    "ScenarioReport",
    "SimulatorError",
    "SimulatorService",
    "SimulatorStatus",
    "SourceStatus",
    "StageSummary",
    "SubjectOutlook",
    "SumOfParts",
    "TeamProfile",
    "TeamService",
    "TeamTable",
    "ValueForMoney",
    "ValueService",
    "ValueStatus",
    "Window",
    "floor",
    "metric_glossary",
    "probability_key",
    "relationship",
]
