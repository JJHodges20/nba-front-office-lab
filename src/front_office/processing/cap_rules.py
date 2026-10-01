"""Tabulate season rules into the ``salary_cap_rules`` table."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from front_office.domain.cap_rules import PayrollLine, SeasonRules
from front_office.domain.schema import conform_frame
from front_office.domain.tables.finance import SALARY_CAP_RULES


def cap_rules_frame(rules: Iterable[SeasonRules]) -> pd.DataFrame:
    """One row per season, oldest first, satisfying the ``salary_cap_rules`` contract."""
    rows = [_row(season_rules) for season_rules in sorted(rules, key=lambda r: r.season_id)]
    frame = pd.DataFrame(rows, columns=list(SALARY_CAP_RULES.column_names))
    return conform_frame(frame, SALARY_CAP_RULES)


def _row(rules: SeasonRules) -> dict[str, object]:
    exceptions = rules.exceptions
    maximums = rules.maximum_salaries
    return {
        "season": rules.season,
        "status": rules.status.value,
        **{line.value: rules.line(line) for line in PayrollLine},
        "non_taxpayer_mid_level": exceptions.non_taxpayer_mid_level if exceptions else None,
        "taxpayer_mid_level": exceptions.taxpayer_mid_level if exceptions else None,
        "room_mid_level": exceptions.room_mid_level if exceptions else None,
        "bi_annual": exceptions.bi_annual if exceptions else None,
        "max_salary_0_to_6_years": maximums.service_0_to_6_years if maximums else None,
        "max_salary_7_to_9_years": maximums.service_7_to_9_years if maximums else None,
        "max_salary_10_plus_years": maximums.service_10_plus_years if maximums else None,
        "max_standard_contracts": rules.roster.max_standard_contracts,
        "min_standard_contracts": rules.roster.min_standard_contracts,
        "max_two_way_contracts": rules.roster.max_two_way_contracts,
        "offseason_max_players": rules.roster.offseason_max_players,
        "source_urls": "\n".join(source.url for source in rules.sources),
        "rules_version": rules.version,
    }
