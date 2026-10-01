"""Service layer: the read-side API the workbench and CLI call.

Combines repositories with analytics and hands back display-ready results. The user
interface depends on this layer only. May import: domain, config, storage, analytics,
quality.
"""

from front_office.analytics.comparison import Qualification
from front_office.services.lab import Lab, LabNotBuilt, LabStatus
from front_office.services.players import (
    DEFAULT_QUALIFICATION,
    PlayerProfile,
    PlayerService,
    PlayerTable,
    Window,
)

__all__ = [
    "DEFAULT_QUALIFICATION",
    "Lab",
    "LabNotBuilt",
    "LabStatus",
    "PlayerProfile",
    "PlayerService",
    "PlayerTable",
    "Qualification",
    "Window",
]
