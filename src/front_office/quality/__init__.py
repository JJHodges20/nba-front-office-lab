"""Quality layer: data-quality checks on normalised frames.

Checks report problems; they never repair data. May import: domain.
"""

from front_office.quality.checks import (
    CHECKS,
    Check,
    CheckResult,
    Severity,
    all_checks,
    reference_checks,
    run_checks,
)

__all__ = [
    "CHECKS",
    "Check",
    "CheckResult",
    "Severity",
    "all_checks",
    "reference_checks",
    "run_checks",
]
