"""Domain layer: the lab's shared vocabulary.

Seasons, cap rules and data contracts. Pure definitions and validation with no I/O;
every other layer may depend on this one and it depends on none of them.
"""

from front_office.domain.cap_rules import (
    CapThresholds,
    MaximumSalaries,
    PayrollLine,
    RosterLimits,
    RulesStatus,
    SalaryExceptions,
    SeasonRules,
    SourceReference,
)
from front_office.domain.schema import (
    ContractViolationError,
    DType,
    Field,
    Provenance,
    TableContract,
    Violation,
    conform_frame,
    validate_frame,
)
from front_office.domain.seasons import Season, SeasonType

__all__ = [
    "CapThresholds",
    "ContractViolationError",
    "DType",
    "Field",
    "MaximumSalaries",
    "PayrollLine",
    "Provenance",
    "RosterLimits",
    "RulesStatus",
    "SalaryExceptions",
    "Season",
    "SeasonRules",
    "SeasonType",
    "SourceReference",
    "TableContract",
    "Violation",
    "conform_frame",
    "validate_frame",
]
