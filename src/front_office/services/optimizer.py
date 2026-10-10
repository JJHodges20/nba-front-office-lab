"""The roster optimizer for the workbench: the pool it chooses from, the budget it is held
to, the rosters it finds, and saving one as a Team Builder roster.

It assembles what other services already give - the value model's projections for the
season ahead, the contract file's salaries for that season, the roles and groups of the
latest season played - and hands the search to the modeling layer. It scores nothing
itself, and the roadmap's caution stands over all of it: the rosters are estimates built
on a model's projections, several are shown because any one "best" rests on
assumptions, and nothing here is a recommendation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from front_office.analytics.finance import PayrollSummary, payroll_summary
from front_office.domain.cap_rules import PayrollLine, SeasonRules
from front_office.domain.optimizer import (
    BudgetMode,
    OptimizerOutcome,
    OptimizerRequest,
    RosterSolution,
)
from front_office.domain.tables.rosters import ROSTER_SLOTS, STARTING_SLOTS
from front_office.modeling.fit import fills_column
from front_office.modeling.optimizer import GROUPS, REQUIRED_COLUMNS, solve
from front_office.services.builder import RosterError
from front_office.services.lab import Lab
from front_office.storage import StorageError

PLAN_COLUMNS = (
    "player_name",
    "team",
    "position",
    "age",
    "salary",
    "years_remaining",
    "projected_impact",
    "projected_share",
    "projected_wins",
    "projection_reliability",
    "role",
    "roles",
)
GROUP_COLUMNS = tuple(f"in_{group}" for group in GROUPS)
EXAMPLE_ROLES = {
    "primary_creator": 2,
    "floor_spacer": 4,
    "perimeter_defender": 2,
    "rim_protector": 1,
}
"""The roadmap's own example of minimum requirements, offered as the form's starting
point. A requirement is the user's, never the lab's."""
EXAMPLE_BIGS = 2
"""The example's "backup center": two big men."""
DEFAULT_PLAYERS = (13, 15)
"""The roster size to start from where no cap rules say what a team carries."""
BENCH = ROSTER_SLOTS[-1]
SLOT_PREFERENCE = {"guards": ("PG", "SG"), "wings": ("SF", "PF"), "bigs": ("C", "PF")}


class OptimizerError(ValueError):
    """The request cannot be run as asked; the message says why."""


@dataclass(frozen=True, slots=True)
class OptimizerStatus:
    payroll_season: str | None
    """The season being built for: the one the value model looks ahead to."""
    stats_season: str | None
    """The latest season played: where the roles and groups come from."""
    has_rules: bool
    """Whether that season has cap rules, so the cap lines can be budgets."""
    projected: int
    priced: int
    pool: int
    """Players with both a projection and a salary: what the optimizer chooses from."""
    reason: str | None
    """Why the optimizer cannot run; ``None`` when it can."""

    @property
    def is_available(self) -> bool:
        return self.reason is None


@dataclass(frozen=True, slots=True)
class RosterPlan:
    """One roster the optimizer found, with who the players are."""

    solution: RosterSolution
    players: pd.DataFrame
    """Indexed by ``player_id``, the largest projected share first: :data:`PLAN_COLUMNS`."""
    payroll: PayrollSummary | None
    """The payroll against the season's lines; ``None`` without cap rules."""
    room: int
    """Dollars left under the budget."""
    added: tuple[str, ...]
    """Players this roster holds that the first does not."""
    removed: tuple[str, ...]
    """Players the first roster holds that this one does not."""

    @property
    def number(self) -> int:
        return self.solution.number


@dataclass(frozen=True, slots=True)
class OptimizerReport:
    request: OptimizerRequest
    budget: int
    outcome: OptimizerOutcome
    plans: tuple[RosterPlan, ...]
    pool_size: int
    error: float | None
    """What the value model's prediction of a team missed by, out of sample (RMSE)."""

    @property
    def found(self) -> bool:
        return bool(self.plans)


class OptimizerService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    # --- what there is to work with ---------------------------------------------------

    def status(self) -> OptimizerStatus:
        value = self._lab.value.status()
        upcoming = value.upcoming
        stats = value.seasons[0] if value.seasons else None
        projected = 0 if upcoming is None else len(self._lab.value.projections())
        priced = 0
        if upcoming is not None and self._lab.contracts.available:
            priced = len(self._lab.contracts.salaries(upcoming))
        pool = len(self.pool()) if projected and priced and stats else 0
        if upcoming is None or stats is None:
            reason = (
                "no season is being looked ahead to: the value model has to be fitted and "
                "applied first (fol value fit --write, then fol build)."
            )
        elif projected == 0:
            reason = f"no player has a projection for {upcoming}."
        elif priced == 0:
            reason = (
                f"no salaries for {upcoming} are on file. The optimizer builds under a payroll, "
                "so it needs a contract file with that season's salaries."
            )
        elif pool == 0:
            reason = f"no projected player has a salary on file for {upcoming}."
        else:
            reason = None
        return OptimizerStatus(
            payroll_season=upcoming,
            stats_season=stats,
            has_rules=upcoming is not None and self._lab.rules(upcoming) is not None,
            projected=projected,
            priced=priced,
            pool=pool,
            reason=reason,
        )

    def pool(self) -> pd.DataFrame:
        """Every player with a projection for the season ahead and a salary for it,
        indexed by ``player_id``: :data:`PLAN_COLUMNS`, the groups and the roles filled
        in the latest season, the most projected wins first."""
        value = self._lab.value.status()
        upcoming, seasons = value.upcoming, value.seasons
        columns = [*PLAN_COLUMNS, "team_id", "position_group", *GROUP_COLUMNS]
        if upcoming is None or not seasons or not self._lab.contracts.available:
            return pd.DataFrame(columns=columns).rename_axis("player_id")
        projections = self._lab.value.projections()
        salaries = self._lab.contracts.salaries(upcoming)[["salary", "years_remaining"]]
        frame = projections.join(salaries, how="inner")
        stats = seasons[0]
        profiles = self._lab.fit.profiles(stats)
        archetypes = self._lab.fit.archetypes()
        flags = [*GROUP_COLUMNS, *(fills_column(key) for key in archetypes.keys)]
        for column in flags:
            source = profiles[column] if column in profiles else pd.Series(dtype="bool")
            frame[column] = source.reindex(frame.index).fillna(False).astype(bool)
        roles = self._lab.value.roles(stats)
        frame["role"] = roles["role"].reindex(frame.index)
        frame["roles"] = roles["roles"].reindex(frame.index)
        return frame[[*columns, *flags[len(GROUP_COLUMNS) :]]].sort_values(
            "projected_wins", ascending=False
        )

    def defaults(self) -> OptimizerRequest:
        """A request to start from: the season ahead under its salary cap, a roster of
        the size the rules allow, and the roadmap's example requirements for the roles
        the lab defines."""
        status = self.status()
        season, stats = status.payroll_season or "", status.stats_season or ""
        rules = self._lab.rules(season) if season else None
        archetypes = self._lab.fit.archetypes()
        roles = {key: count for key, count in EXAMPLE_ROLES.items() if key in archetypes.keys}
        if rules is not None:
            return OptimizerRequest(
                payroll_season=season,
                stats_season=stats,
                budget_mode=BudgetMode.SALARY_CAP,
                # The figure an owner-set budget starts from: the cap, until it is changed.
                budget=int(rules.thresholds.salary_cap),
                min_players=rules.roster.min_standard_contracts,
                max_players=rules.roster.max_standard_contracts,
                roles=roles,
                bigs=EXAMPLE_BIGS,
            )
        return OptimizerRequest(
            payroll_season=season,
            stats_season=stats,
            budget_mode=BudgetMode.CUSTOM,
            budget=self._typical_payroll(season),
            min_players=DEFAULT_PLAYERS[0],
            max_players=DEFAULT_PLAYERS[1],
            roles=roles,
            bigs=EXAMPLE_BIGS,
        )

    def budget_for(self, request: OptimizerRequest) -> int:
        """The payroll ceiling a request asks for, in dollars."""
        if request.budget_mode is BudgetMode.CUSTOM:
            return int(request.budget or 0)
        rules = self._lab.rules(request.payroll_season)
        if rules is None:
            raise OptimizerError(
                f"no cap rules are configured for {request.payroll_season}, so "
                f"{request.budget_mode.title.lower()} is not a figure the lab knows; choose "
                "an owner's budget instead."
            )
        return int(rules.line(PayrollLine(request.budget_mode.value)))

    # --- running it -----------------------------------------------------------------

    def solve(self, request: OptimizerRequest) -> OptimizerReport:
        """Run the request against the pool and dress the rosters found with names."""
        status = self.status()
        if not status.is_available:
            raise OptimizerError(status.reason or "the optimizer cannot run")
        if (request.payroll_season, request.stats_season) != (
            status.payroll_season,
            status.stats_season,
        ):
            raise OptimizerError(
                f"rosters are built for {status.payroll_season} from the roles of "
                f"{status.stats_season}; the request asks for {request.payroll_season} and "
                f"{request.stats_season}."
            )
        pool = self.pool()
        budget = self.budget_for(request)
        rules = self._lab.rules(request.payroll_season)
        minimum = None if rules is None else int(rules.thresholds.minimum_team_salary)
        model = self._lab.value.model()
        if model is None:
            raise OptimizerError("the value model is no longer on file; fit it again")
        columns = [*REQUIRED_COLUMNS, *[c for c in pool.columns if c.startswith("fills_")]]
        outcome = solve(
            pool[columns],
            request,
            budget=budget,
            minimum_salary=minimum,
            replacement=model.replacement_level,
        )
        plans = []
        first: tuple[int, ...] = ()
        for solution in outcome.solutions:
            if not first:
                first = solution.player_ids
            plans.append(self._plan(solution, pool, rules, budget, first))
        return OptimizerReport(
            request=request,
            budget=budget,
            outcome=outcome,
            plans=tuple(plans),
            pool_size=len(pool),
            # A forecast projects minutes, so it carries the error of the test that did too.
            error=(model.validation.projected or model.validation.net).rmse,
        )

    def slots(
        self, player_ids: Sequence[int], pool: pd.DataFrame | None = None
    ) -> tuple[tuple[int, str], ...]:
        """Where a saved roster puts each player, the largest projected share first: the
        five largest start, each in a slot that suits their group, and everyone else is
        on the bench. The Team Builder can move them."""
        pool = self.pool() if pool is None else pool
        chosen = pool.loc[[int(player) for player in player_ids]].sort_values(
            "projected_share", ascending=False
        )
        free = list(STARTING_SLOTS)
        placed = []
        for player_id, row in chosen.iterrows():
            slot = BENCH
            if free:
                wanted = [
                    s for g in GROUPS if row[f"in_{g}"] for s in SLOT_PREFERENCE[g] if s in free
                ]
                slot = wanted[0] if wanted else free[0]
                free.remove(slot)
            placed.append((int(player_id), slot))
        return tuple(placed)

    def save(
        self,
        player_ids: Sequence[int],
        name: str,
        request: OptimizerRequest,
        *,
        notes: str | None = None,
    ) -> int:
        """Create a Team Builder roster from a solution's players and return its id, in
        one transaction: the roster is saved whole or not at all (decision 0018, A5).
        Players are placed as :meth:`slots` says."""
        try:
            return self._lab.rosters.create_with_players(
                name,
                stats_season=request.stats_season,
                payroll_season=request.payroll_season,
                players=self.slots(player_ids),
                notes=notes,
            )
        except StorageError as error:
            raise RosterError(str(error)) from error

    # --- assembly -----------------------------------------------------------------------

    def _plan(
        self,
        solution: RosterSolution,
        pool: pd.DataFrame,
        rules: SeasonRules | None,
        budget: int,
        first: tuple[int, ...],
    ) -> RosterPlan:
        players = pool.loc[list(solution.player_ids), list(PLAN_COLUMNS)].sort_values(
            "projected_share", ascending=False
        )
        names = pool["player_name"]
        added = tuple(str(names[p]) for p in solution.player_ids if p not in first)
        removed = tuple(str(names[p]) for p in first if p not in solution.player_ids)
        return RosterPlan(
            solution=solution,
            players=players,
            payroll=None if rules is None else payroll_summary(solution.payroll, rules),
            room=budget - solution.payroll,
            added=added,
            removed=removed,
        )

    def _typical_payroll(self, season: str) -> int:
        """An owner's budget to start from where no cap line can be: the median team
        payroll on file for the season or, failing that, a roster of median salaries.
        A starting figure, never a finding; the form is there to change it."""
        if season and self._lab.contracts.available:
            payrolls = self._lab.contracts.team_payrolls(season)
            if not payrolls.empty and "team_salary" in payrolls:
                return max(
                    1, int(round(float(payrolls["team_salary"].median()) / 1_000_000) * 1_000_000)
                )
        pool = self.pool()
        if pool.empty:
            return 1
        return max(1, int(round(float(pool["salary"].median()) * DEFAULT_PLAYERS[0])))
