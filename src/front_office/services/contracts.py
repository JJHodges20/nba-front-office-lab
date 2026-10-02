"""Contract views for the workbench: who is owed what, and where each payroll stands.

Salaries come only from a contract file the user imported. Until one is imported every
view here is empty, and :attr:`ContractService.available` says so.

This module assembles: it reads tables, calls analytics, and joins the results with
names. It contains no formulas.
"""

from __future__ import annotations

import pandas as pd

from front_office.analytics import finance
from front_office.domain.cap_rules import PayrollLine
from front_office.services.lab import Lab

CONTRACT_COLUMNS = (
    "contract_id",
    "player_id",
    "player_name",
    "position",
    "team",
    "team_name",
    "team_id",
    "contract_type",
    "status",
    "salary",
    "salary_cap_pct",
    "option",
    "guarantee",
    "years_remaining",
    "first_season",
    "last_season",
    "seasons",
    "total_salary",
)
_CONTRACT_DETAILS = [
    "contract_id",
    "player_name",
    "contract_type",
    "status",
    "first_season",
    "last_season",
    "seasons",
    "total_salary",
]
LINE_COLUMNS = tuple(line.value for line in PayrollLine)
SALARY_COLUMNS = ("salary", "salary_cap_pct", "years_remaining", "option", "guarantee")


class ContractService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def available(self) -> bool:
        """Whether any contract data has been imported and built."""
        return bool(self.seasons())

    def seasons(self) -> tuple[str, ...]:
        """Seasons the contract data lists salaries for, oldest first."""
        if not self._lab.warehouse.is_built():
            return ()
        return tuple(self._lab.warehouse.distinct("contract_years", "season"))

    def sources(self) -> pd.DataFrame:
        """Where the salaries came from: one row per source and date, as stated at import."""
        contracts = self._lab.read("contracts")
        grouped = contracts.groupby(["source_label", "as_of_date"], as_index=False)
        return grouped.agg(contracts=("contract_id", "size"), players=("player_id", "nunique"))

    def table(self, season: str) -> pd.DataFrame:
        """Every salary owed in one season, largest first.

        One row per contract: the player, the team that owes the salary, the kind of
        contract, whether the player is still under it or it is dead money, and the
        season's salary with its share of the cap.
        """
        years = self._lab.read("contract_years", {"season": season})
        contracts = self._lab.read("contracts")[_CONTRACT_DETAILS]
        frame = years.merge(contracts, on="contract_id", how="left", validate="many_to_one")
        teams = self._lab.team_labels()
        frame["team"] = frame["team_id"].map(teams["abbreviation"])
        frame["team_name"] = frame["team_id"].map(teams["full_name"])
        frame = self._identified(frame)
        ordered = frame.sort_values(["salary", "player_name"], ascending=[False, True])
        return ordered[list(CONTRACT_COLUMNS)].reset_index(drop=True)

    def salaries(self, season: str) -> pd.DataFrame:
        """Each player's own salary in one season, indexed by ``player_id``.

        Only contracts the player is still under count: money a team still owes a
        player it waived is that team's cost, not the player's salary.
        """
        years = self._lab.read("contract_years", {"season": season})
        contracts = self._lab.read("contracts")[["contract_id", "status"]]
        active = years.merge(contracts, on="contract_id", validate="many_to_one")
        active = active[active["status"] == "active"].drop_duplicates("player_id")
        return active.set_index("player_id")[list(SALARY_COLUMNS)]

    def team_payrolls(self, season: str) -> pd.DataFrame:
        """Each team's payroll in one season against that season's cap lines, largest first.

        Only teams the contract data covers are listed: a team absent from the file has
        an unknown payroll, not an empty one. Where the season has no configured cap
        rules the cap columns are missing.
        """
        payrolls = finance.team_payrolls(self.table(season))
        teams = self._lab.team_labels()
        payrolls.insert(0, "team", payrolls.index.map(teams["abbreviation"]))
        payrolls.insert(1, "team_name", payrolls.index.map(teams["full_name"]))
        rules = self._lab.rules(season)
        if rules is None:
            payrolls["cap_share"] = float("nan")
            for line in PayrollLine:
                payrolls[f"room_{line.value}"] = pd.array([pd.NA] * len(payrolls), dtype="Int64")
            payrolls["highest_line_exceeded"] = pd.Series(pd.NA, index=payrolls.index, dtype="str")
            payrolls["is_below_minimum"] = pd.array([pd.NA] * len(payrolls), dtype="boolean")
        else:
            payrolls = payrolls.join(finance.payroll_positions(payrolls["team_salary"], rules))
        return payrolls.sort_values(["team_salary", "team"], ascending=[False, True])

    def commitments(self, team_id: int) -> pd.DataFrame:
        """What one team owes, contract by contract and season by season.

        One row per contract with the player, the kind of contract and its status, then
        one column per season holding that season's salary (missing where the contract
        does not run), and the total. Largest total first.
        """
        years = self._lab.read("contract_years", {"team_id": int(team_id)})
        contracts = self._lab.read("contracts", {"team_id": int(team_id)})
        leading = ["player_id", "player_name", "contract_type", "status"]
        if years.empty:
            return pd.DataFrame(columns=[*leading, "total_salary"])
        by_season = years.pivot(index="contract_id", columns="season", values="salary")
        by_season = by_season.reindex(columns=sorted(by_season.columns)).astype("Int64")
        contracts = self._identified(contracts)
        details = contracts.set_index("contract_id")[[*leading, "total_salary"]]
        table = details[leading].join(by_season).join(details["total_salary"])
        ordered = table.sort_values(["total_salary", "player_name"], ascending=[False, True])
        return ordered.reset_index(drop=True).rename_axis(columns=None)

    def outlook(self, team_id: int) -> pd.DataFrame:
        """One team's payroll in every season its contracts run, with the cap lines.

        Indexed by season, oldest first: the payroll columns of :meth:`team_payrolls`,
        then the season's thresholds where cap rules are configured.
        """
        years = self._lab.read("contract_years", {"team_id": int(team_id)})
        contracts = self._lab.read("contracts")[["contract_id", "contract_type", "status"]]
        owed = years.merge(contracts, on="contract_id", how="left", validate="many_to_one")
        rows = {}
        for season, season_years in owed.groupby("season"):
            payroll = finance.team_payrolls(season_years).iloc[0].to_dict()
            rules = self._lab.rules(str(season))
            for line in PayrollLine:
                payroll[line.value] = None if rules is None else rules.line(line)
            payroll["cap_share"] = (
                float("nan") if rules is None else rules.cap_share(payroll["team_salary"])
            )
            rows[str(season)] = payroll
        columns = [*finance.TEAM_PAYROLL_COLUMNS, *LINE_COLUMNS, "cap_share"]
        outlook = pd.DataFrame.from_dict(rows, orient="index", columns=columns)
        outlook[list(LINE_COLUMNS)] = outlook[list(LINE_COLUMNS)].astype("Int64")
        return outlook.rename_axis(index="season").sort_index()

    def cap_rules(self) -> pd.DataFrame:
        """The configured cap thresholds, exceptions and roster limits, newest season first."""
        rules = self._lab.read("salary_cap_rules")
        return rules.sort_values("season", ascending=False).reset_index(drop=True)

    def _identified(self, frame: pd.DataFrame) -> pd.DataFrame:
        """``frame`` with each player's listed position and name as the league has them.

        A contract file may name a player differently, or not at all; the row was
        matched to a player id at import, so the league's own name is the reliable one.
        """
        known = self._lab.read("players", {"player_id": frame["player_id"].tolist()})
        known = known.set_index("player_id")
        named = frame.copy()
        named["player_name"] = (
            named["player_id"].map(known["full_name"]).fillna(named["player_name"])
        )
        named["position"] = named["player_id"].map(known["position"])
        return named

    def summary(self, season: str) -> finance.SeasonSalaries:
        """What one season's contract data adds up to."""
        return finance.season_salaries(self.table(season))

    def unassigned(self, season: str) -> int:
        """Salaries in a season that the contract file did not attach to a team."""
        return self.summary(season).unassigned
