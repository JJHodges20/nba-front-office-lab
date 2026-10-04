"""The roster optimizer: an exact search for the strongest rosters a budget allows.

What is maximised is the value model's projection of the players, each taken alone: a
roster's projected net rating is replacement level for five slots plus what each player
adds above replacement for the share of a season's minutes the player is projected to
play. That is the sum of the parts, and it is all the evidence supports
(``docs/decisions/0012-roster-fit.md``). Roles enter as requirements a front office may
set, never as a score.

Two budgets bind. The payroll may not exceed the line chosen. And the players' projected
minutes may not exceed a season's by more than a little, because a roster of fifteen
players who each expect to play most of every game is not a roster anyone can play:
stars who would sit are worth less than their projection says.

The search is an integer programme solved exactly (HiGHS, through SciPy). After each
roster is found it is cut off - the next may share at most all but a few of its players
- so that several strong rosters come back rather than one. The weights behind any one
"best" roster are assumptions; several make the trade-offs visible.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

from front_office.domain.optimizer import (
    ON_COURT,
    OptimizerOutcome,
    OptimizerRequest,
    RosterSolution,
)

FILLS = "fills_"
GROUPS = ("guards", "wings", "bigs")
REQUIRED_COLUMNS = (
    "salary",
    "projected_impact",
    "projected_share",
    "age",
    "in_guards",
    "in_wings",
    "in_bigs",
)
SALARY_TIE_BREAK = 1e-10
"""Points of rating a dollar costs in the objective: among rosters that project alike,
the cheaper. A hundred million dollars is a hundredth of a point - never a real trade,
and still far above the solver's tolerances."""
OPTIMAL, TIME_LIMIT, INFEASIBLE, NO_POOL = "optimal", "time_limit", "infeasible", "no_pool"
MIP_GAP = 1e-7
"""The relative gap at which the solver may stop: a hundred-thousandth of a point on a
roster worth ten, far below any difference that matters."""


def quality(pool: pd.DataFrame, replacement: float) -> pd.Series:
    """What each player adds above a replacement player, for the minutes projected:
    points of a team's net rating per 100 possessions."""
    impact = pool["projected_impact"].astype("float64")
    share = pool["projected_share"].astype("float64")
    return ((impact - replacement) * share).rename("quality")


def rating(total_quality: float, shares: float, replacement: float) -> float:
    """A roster's projected net rating relative to the league: five replacement slots plus
    what the players add, scaled down where their minutes add up to more than a season."""
    scale = min(1.0, ON_COURT / shares) if shares > 0 else 1.0
    return ON_COURT * replacement + scale * total_quality


def eligible(pool: pd.DataFrame, request: OptimizerRequest) -> pd.DataFrame:
    """The players a roster may hold: the pool less the excluded and those outside the
    age range or above the salary limit. A locked player stays whatever the limits."""
    keep = ~pool.index.isin(request.excluded)
    if request.min_age is not None:
        keep &= pool["age"].ge(request.min_age).to_numpy()
    if request.max_age is not None:
        keep &= pool["age"].le(request.max_age).to_numpy()
    if request.max_salary is not None:
        keep &= pool["salary"].le(request.max_salary).to_numpy()
    keep |= pool.index.isin(request.locked)
    return pool[keep]


def solve(
    pool: pd.DataFrame,
    request: OptimizerRequest,
    *,
    budget: int,
    minimum_salary: int | None,
    replacement: float,
) -> OptimizerOutcome:
    """Find up to ``request.solutions`` rosters, best first.

    ``pool`` is indexed by ``player_id`` with :data:`REQUIRED_COLUMNS` and a boolean
    ``fills_<archetype>`` column per role the request may count. ``budget`` is the
    payroll ceiling in dollars and ``minimum_salary`` the floor, enforced only when the
    request says so.
    """
    missing = [column for column in REQUIRED_COLUMNS if column not in pool.columns]
    if missing:
        raise ValueError(f"the pool lacks {missing}")
    players = eligible(pool, request)
    absent = [player for player in request.locked if player not in players.index]
    if absent:
        return OptimizerOutcome(
            INFEASIBLE,
            (),
            reasons=(
                f"{len(absent)} locked player(s) are not in the pool: a player needs a salary "
                "for the season and a projection to be placed on a roster.",
            ),
        )
    if players.empty:
        return OptimizerOutcome(NO_POOL, (), reasons=("no player is left to choose from.",))

    problem = _Problem(players, request, budget, minimum_salary, replacement)
    reasons = problem.diagnose()
    if reasons:
        return OptimizerOutcome(INFEASIBLE, (), reasons=reasons)

    solutions: list[RosterSolution] = []
    cuts: list[np.ndarray] = []
    relaxed = False
    status = OPTIMAL
    want_rating = request.min_rating is not None
    for number in range(1, request.solutions + 1):
        found, chosen = problem.run(cuts, with_rating=want_rating)
        if chosen is None and want_rating and number == 1:
            # Nothing reaches the rating asked for: show the best that does not.
            relaxed, want_rating = True, False
            found, chosen = problem.run(cuts, with_rating=False)
        if chosen is None:
            break
        if found == TIME_LIMIT:
            status = TIME_LIMIT
        solutions.append(problem.solution(number, chosen))
        cuts.append(chosen)
    if not solutions:
        return OptimizerOutcome(
            INFEASIBLE,
            (),
            relaxed_rating=relaxed,
            reasons=("no roster satisfies the requirements together within the budget.",),
        )
    reasons = ()
    if relaxed:
        best = solutions[0].rating
        reasons = (
            f"no roster reaches a projected rating of {request.min_rating:+.1f} under these "
            f"requirements; the best reaches {best:+.1f}. The rosters shown ignore that "
            "requirement.",
        )
    return OptimizerOutcome(status, tuple(solutions), relaxed_rating=relaxed, reasons=reasons)


class _Problem:
    """The integer programme, built once and solved as often as rosters are wanted."""

    def __init__(
        self,
        players: pd.DataFrame,
        request: OptimizerRequest,
        budget: int,
        minimum_salary: int | None,
        replacement: float,
    ) -> None:
        self.players = players
        self.request = request
        self.budget = budget
        self.minimum_salary = minimum_salary
        self.replacement = replacement
        self.ids = players.index.to_numpy()
        self.salary = players["salary"].to_numpy(dtype="float64")
        self.share = players["projected_share"].to_numpy(dtype="float64")
        self.quality = quality(players, replacement).to_numpy(dtype="float64")
        self.locked = players.index.isin(request.locked)
        self.roles = {
            key: self._flags(f"{FILLS}{key}") for key, count in request.roles.items() if count > 0
        }
        self.groups = {
            group: self._flags(f"in_{group}") for group in GROUPS if getattr(request, group) > 0
        }

    def _flags(self, column: str) -> np.ndarray:
        if column not in self.players.columns:
            return np.zeros(len(self.players))
        return self.players[column].fillna(False).astype(bool).to_numpy(dtype="float64")

    # --- the constraints ------------------------------------------------------------------

    def constraints(
        self, cuts: Sequence[np.ndarray], *, with_rating: bool
    ) -> list[LinearConstraint]:
        request = self.request
        ones = np.ones(len(self.players))
        rows: list[tuple[np.ndarray, float, float]] = [
            (
                self.salary,
                self.minimum_salary
                if (request.enforce_minimum_salary and self.minimum_salary)
                else -np.inf,
                float(self.budget),
            ),
            (ones, float(request.min_players), float(request.max_players)),
            (self.share, -np.inf, ON_COURT * (1 + request.minutes_slack)),
        ]
        for key, flags in self.roles.items():
            rows.append((flags, float(request.roles[key]), np.inf))
        for group, flags in self.groups.items():
            rows.append((flags, float(getattr(request, group)), np.inf))
        if with_rating and request.min_rating is not None:
            rows.append((self.quality, request.min_rating - ON_COURT * self.replacement, np.inf))
        for chosen in cuts:
            rows.append(
                (chosen.astype("float64"), -np.inf, float(chosen.sum() - request.distinct_by))
            )
        matrix = np.vstack([row for row, _, _ in rows])
        lower = np.array([low for _, low, _ in rows])
        upper = np.array([high for _, _, high in rows])
        return [LinearConstraint(matrix, lower, upper)]

    def run(
        self, cuts: Sequence[np.ndarray], *, with_rating: bool
    ) -> tuple[str, np.ndarray | None]:
        """Solve once: the status and the chosen players as a 0/1 vector, or ``None``."""
        objective = -(self.quality - SALARY_TIE_BREAK * self.salary)
        lower = self.locked.astype("float64")
        result = milp(
            objective,
            constraints=self.constraints(cuts, with_rating=with_rating),
            integrality=np.ones(len(self.players)),
            bounds=Bounds(lower, np.ones(len(self.players))),
            # Tight enough that two rosters a hair apart come back in the right order.
            options={"time_limit": self.request.time_limit, "disp": False, "mip_rel_gap": MIP_GAP},
        )
        if result.x is None:
            return INFEASIBLE, None
        chosen = np.rint(result.x).astype(int)
        return (OPTIMAL if result.status == 0 else TIME_LIMIT), chosen

    def solution(self, number: int, chosen: np.ndarray) -> RosterSolution:
        picked = chosen.astype(bool)
        shares = float(self.share[picked].sum())
        total = float(self.quality[picked].sum())
        return RosterSolution(
            number=number,
            player_ids=tuple(int(player) for player in self.ids[picked]),
            payroll=int(round(self.salary[picked].sum())),
            rating=rating(total, shares, self.replacement),
            rating_unscaled=ON_COURT * self.replacement + total,
            shares=shares,
            roles={key: int(flags[picked].sum()) for key, flags in self.roles.items()},
            guards=int(self._flags("in_guards")[picked].sum()),
            wings=int(self._flags("in_wings")[picked].sum()),
            bigs=int(self._flags("in_bigs")[picked].sum()),
        )

    # --- why nothing can be found ------------------------------------------------------------

    def diagnose(self) -> tuple[str, ...]:
        """Requirements that cannot be met on their own, before the solver is asked."""
        request = self.request
        reasons = []
        if len(self.players) < request.min_players:
            reasons.append(
                f"only {len(self.players)} players are available and a roster needs at least "
                f"{request.min_players}."
            )
        cheapest = np.sort(self.salary)[: request.min_players].sum()
        if cheapest > self.budget:
            reasons.append(
                f"the {request.min_players} cheapest available players already cost "
                f"${cheapest:,.0f}, more than the budget of ${self.budget:,.0f}."
            )
        if self.locked.any() and self.salary[self.locked].sum() > self.budget:
            reasons.append(
                f"the locked players alone cost ${self.salary[self.locked].sum():,.0f}, more "
                f"than the budget of ${self.budget:,.0f}."
            )
        if self.locked.any() and self.share[self.locked].sum() > ON_COURT * (
            1 + request.minutes_slack
        ):
            reasons.append(
                "the locked players' projected minutes alone add up to more than a season "
                f"allows ({self.share[self.locked].sum() / ON_COURT:.0%} of one)."
            )
        for key, flags in self.roles.items():
            if flags.sum() < request.roles[key]:
                reasons.append(
                    f"only {int(flags.sum())} available players fill the {key.replace('_', ' ')} "
                    f"role and {request.roles[key]} are required."
                )
        for group, flags in self.groups.items():
            if flags.sum() < getattr(request, group):
                reasons.append(
                    f"only {int(flags.sum())} available players are {group} and "
                    f"{getattr(request, group)} are required."
                )
        return tuple(reasons)
