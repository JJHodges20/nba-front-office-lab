"""Validate the raw store: normalise it and run every data-quality check.

Nothing is written. This is the gate that answers "can the stored data be trusted?"
before it is loaded anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from front_office.config.models import load_value_model
from front_office.config.season_rules import load_all_season_rules
from front_office.config.settings import Settings
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.tables import MODELED_TABLES
from front_office.domain.value_model import ValueModel
from front_office.pipelines.normalize import BUILT_TABLES, NormalizedTables, normalize
from front_office.pipelines.value import add_value_tables
from front_office.quality import CheckResult, Severity, all_checks, run_checks
from front_office.rawstore import RawStore

# Re-exported so the command line can style results without importing the quality layer.
CheckSeverity = Severity


@dataclass(frozen=True, slots=True)
class DataReport:
    tables: NormalizedTables
    checks: list[CheckResult]

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.passed]

    @property
    def check_errors(self) -> list[CheckResult]:
        return [check for check in self.failed_checks if check.severity is Severity.ERROR]

    @property
    def check_warnings(self) -> list[CheckResult]:
        return [check for check in self.failed_checks if check.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """True when every table was built and no check found a contradiction."""
        return not self.tables.errors and not self.check_errors


CHECKED_TABLES = (*BUILT_TABLES, *MODELED_TABLES)
"""Every table a build produces from the raw store, modeled ones last."""


def check_store(
    store: RawStore,
    season_rules: Sequence[SeasonRules] = (),
    value_model: ValueModel | None = None,
) -> DataReport:
    """Normalise ``store``, apply the fitted models, and check all of it."""
    tables = normalize(store, season_rules=season_rules)
    add_value_tables(tables, value_model)
    return DataReport(tables, run_checks(tables.frames, all_checks(CHECKED_TABLES)))


def check_raw_data(settings: Settings) -> DataReport:
    """Normalise the project's raw store and run the quality checks on the result."""
    season_rules = list(load_all_season_rules(settings.season_rules_dir).values())
    value_model = load_value_model(settings.config_dir)
    return check_store(RawStore(settings.raw_dir), season_rules, value_model)
