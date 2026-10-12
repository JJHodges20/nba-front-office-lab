"""The roster optimizer: exact on pools small enough to enumerate, and every requirement."""

from __future__ import annotations

import threading
from itertools import combinations

import pandas as pd
import pytest

from front_office.domain.optimizer import ON_COURT, BudgetMode, OptimizerRequest
from front_office.modeling import optimizer
from front_office.modeling.optimizer import (
    INFEASIBLE,
    NO_POOL,
    OPTIMAL,
    SALARY_TIE_BREAK,
    eligible,
    quality,
    rating,
    solve,
)

REPLACEMENT = -2.0
ROLES = ("primary_creator", "floor_spacer", "rim_protector")
M = 1_000_000


def player(
    player_id: int,
    salary: float,
    impact: float,
    share: float,
    *,
    age: int = 27,
    group: str = "wings",
    roles: tuple[str, ...] = (),
) -> dict:
    row = {
        "player_id": player_id,
        "salary": salary * M,
        "projected_impact": impact,
        "projected_share": share,
        "age": age,
        "in_guards": group == "guards",
        "in_wings": group == "wings",
        "in_bigs": group == "bigs",
    }
    row.update({f"fills_{role}": role in roles for role in ROLES})
    return row


def pool_of(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows)).set_index("player_id")


TEN = pool_of(
    player(1, 40, 6.0, 0.55, group="guards", roles=("primary_creator",)),
    player(2, 35, 5.0, 0.50, group="wings", roles=("primary_creator", "floor_spacer")),
    player(3, 30, 4.0, 0.52, group="bigs", roles=("rim_protector",)),
    player(4, 20, 2.5, 0.45, group="guards", roles=("floor_spacer",)),
    player(5, 15, 2.0, 0.40, group="wings", roles=("floor_spacer",)),
    player(6, 12, 1.0, 0.35, group="bigs", roles=("rim_protector",), age=34),
    player(7, 8, 0.5, 0.30, group="guards", age=22),
    player(8, 5, 0.0, 0.25, group="wings", roles=("floor_spacer",), age=21),
    player(9, 3, -1.0, 0.20, group="bigs", age=36),
    player(10, 2, -2.5, 0.15, group="guards", age=20),
)


def request(**overrides: object) -> OptimizerRequest:
    settings = {
        "payroll_season": "2026-27",
        "stats_season": "2025-26",
        "budget_mode": BudgetMode.CUSTOM,
        "budget": 100 * M,
        "min_players": 5,
        "max_players": 6,
        "solutions": 1,
    }
    settings.update(overrides)
    return OptimizerRequest(**settings)


def by_force(
    pool: pd.DataFrame, asked: OptimizerRequest, budget: float
) -> tuple[float, tuple[int, ...]]:
    """The best roster by trying every one: the objective and the players."""
    worth = quality(pool, REPLACEMENT)
    best: tuple[float, tuple[int, ...]] | None = None
    candidates = eligible(pool, asked)
    for size in range(asked.min_players, asked.max_players + 1):
        for combo in combinations(candidates.index, size):
            rows = candidates.loc[list(combo)]
            if rows["salary"].sum() > budget:
                continue
            if rows["projected_share"].sum() > ON_COURT * (1 + asked.minutes_slack):
                continue
            if any(rows[f"fills_{key}"].sum() < count for key, count in asked.roles.items()):
                continue
            if any(
                rows[f"in_{group}"].sum() < getattr(asked, group)
                for group in ("guards", "wings", "bigs")
            ):
                continue
            if not set(asked.locked) <= set(combo):
                continue
            value = worth.loc[list(combo)].sum() - SALARY_TIE_BREAK * rows["salary"].sum()
            if (
                asked.min_rating is not None
                and ON_COURT * REPLACEMENT + worth.loc[list(combo)].sum() < asked.min_rating
            ):
                continue
            if best is None or value > best[0] + 1e-12:
                best = (float(value), tuple(sorted(combo)))
    assert best is not None, "the brute force found nothing"
    return best


def found(outcome, number: int = 0):  # type: ignore[no-untyped-def]
    return outcome.solutions[number]


class TestTheArithmetic:
    def test_quality_is_what_a_player_adds_above_replacement_for_the_minutes(self) -> None:
        worth = quality(TEN, REPLACEMENT)
        assert worth[1] == pytest.approx((6.0 + 2.0) * 0.55)
        assert worth[10] == pytest.approx((-2.5 + 2.0) * 0.15)

    def test_a_rating_is_five_replacement_slots_plus_the_players_scaled_to_a_season(self) -> None:
        assert rating(10.0, 4.0, REPLACEMENT) == pytest.approx(-10.0 + 10.0)
        assert rating(10.0, 6.0, REPLACEMENT) == pytest.approx(-10.0 + 10.0 * 5 / 6)
        assert rating(0.0, 0.0, REPLACEMENT) == pytest.approx(-10.0)


class TestTheBestRoster:
    @pytest.mark.parametrize("budget", [60, 80, 100, 130])
    def test_it_is_the_best_by_brute_force(self, budget: int) -> None:
        asked = request(budget=budget * M)
        outcome = solve(TEN, asked, budget=budget * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.status == OPTIMAL and outcome.reasons == ()
        best_value, best_players = by_force(TEN, asked, budget * M)
        roster = found(outcome)
        assert tuple(sorted(roster.player_ids)) == best_players
        assert roster.payroll <= budget * M
        assert roster.rating_unscaled == pytest.approx(
            ON_COURT * REPLACEMENT + quality(TEN, REPLACEMENT)[list(roster.player_ids)].sum()
        )

    def test_a_bigger_budget_never_projects_worse(self) -> None:
        ratings = []
        for budget in (50, 75, 100, 150):
            outcome = solve(
                TEN,
                request(budget=budget * M),
                budget=budget * M,
                minimum_salary=None,
                replacement=REPLACEMENT,
            )
            ratings.append(found(outcome).rating_unscaled)
        assert ratings == sorted(ratings)
        assert ratings[0] < ratings[-1]

    def test_among_equals_the_cheaper(self) -> None:
        twins = pool_of(
            player(1, 20, 3.0, 0.5),
            player(2, 10, 3.0, 0.5),
            player(3, 1, 0.0, 0.2),
            player(4, 1, 0.0, 0.2),
            player(5, 1, 0.0, 0.2),
            player(6, 1, 0.0, 0.2),
        )
        asked = request(budget=30 * M, min_players=5, max_players=5)
        outcome = solve(twins, asked, budget=30 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert 2 in found(outcome).player_ids and 1 not in found(outcome).player_ids


class TestTheTwoBudgets:
    def test_the_payroll_binds(self) -> None:
        asked = request(budget=45 * M, solutions=3)
        outcome = solve(TEN, asked, budget=45 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert all(roster.payroll <= 45 * M for roster in outcome.solutions)
        assert 1 not in found(outcome).player_ids  # too expensive on its own with three more

    def test_the_minutes_bind_and_the_rating_says_so(self) -> None:
        stars = pool_of(*(player(n, 10, 5.0, 0.9) for n in range(1, 8)))
        tight = request(budget=200 * M, min_players=5, max_players=6, minutes_slack=0.0)
        outcome = solve(stars, tight, budget=200 * M, minimum_salary=None, replacement=REPLACEMENT)
        roster = found(outcome)
        assert roster.players == 5 and roster.shares == pytest.approx(4.5)
        assert roster.rating == pytest.approx(roster.rating_unscaled)
        loose = request(budget=200 * M, min_players=5, max_players=6, minutes_slack=0.2)
        outcome = solve(stars, loose, budget=200 * M, minimum_salary=None, replacement=REPLACEMENT)
        roster = found(outcome)
        assert roster.players == 6 and roster.shares == pytest.approx(5.4)
        assert roster.rating == pytest.approx(ON_COURT * REPLACEMENT + 6 * 7.0 * 0.9 * (5 / 5.4))
        assert roster.rating < roster.rating_unscaled

    def test_the_floor_is_enforced_only_when_asked(self) -> None:
        asked = request(budget=100 * M)
        without = solve(TEN, asked, budget=100 * M, minimum_salary=99 * M, replacement=REPLACEMENT)
        assert found(without).payroll < 99 * M
        asked = request(budget=100 * M, enforce_minimum_salary=True)
        with_floor = solve(
            TEN, asked, budget=100 * M, minimum_salary=99 * M, replacement=REPLACEMENT
        )
        assert 99 * M <= found(with_floor).payroll <= 100 * M


class TestRequirements:
    def test_roles_and_groups_are_met(self) -> None:
        asked = request(roles={"rim_protector": 2, "floor_spacer": 2}, guards=1, solutions=2)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        for roster in outcome.solutions:
            assert roster.roles == {
                "rim_protector": roster.roles["rim_protector"],
                "floor_spacer": roster.roles["floor_spacer"],
            }
            assert roster.roles["rim_protector"] >= 2 and roster.roles["floor_spacer"] >= 2
            assert roster.guards >= 1 and roster.bigs >= 2
        best_value, best_players = by_force(TEN, asked, 100 * M)
        assert tuple(sorted(found(outcome).player_ids)) == best_players

    def test_locked_players_are_always_in_and_excluded_never(self) -> None:
        asked = request(locked=(9,), excluded=(1, 2), solutions=3)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        for roster in outcome.solutions:
            assert 9 in roster.player_ids and not {1, 2} & set(roster.player_ids)
        best_value, best_players = by_force(TEN, asked, 100 * M)
        assert tuple(sorted(found(outcome).player_ids)) == best_players

    def test_age_and_salary_limits_narrow_the_pool_but_not_a_locked_player(self) -> None:
        asked = request(min_age=22, max_age=36, max_salary=20 * M, locked=(1,))
        candidates = eligible(TEN, asked)
        assert set(candidates.index) == {1, 4, 5, 6, 7, 9}
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        roster = found(outcome)
        assert set(roster.player_ids) <= {1, 4, 5, 6, 7, 9} and 1 in roster.player_ids
        best_value, best_players = by_force(TEN, asked, 100 * M)
        assert tuple(sorted(roster.player_ids)) == best_players

    def test_a_least_rating_is_met_or_dropped_with_a_reason(self) -> None:
        asked = request(min_rating=0.0, solutions=2)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert not outcome.relaxed_rating and all(
            r.rating_unscaled >= 0.0 for r in outcome.solutions
        )
        best_value, best_players = by_force(TEN, asked, 100 * M)
        assert tuple(sorted(found(outcome).player_ids)) == best_players
        asked = request(min_rating=50.0)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.relaxed_rating and outcome.found
        assert outcome.reasons[0].startswith("no roster reaches a projected rating of +50.0")
        assert f"the best reaches {found(outcome).rating:+.1f}" in outcome.reasons[0]


class TestSeveralRosters:
    def test_each_roster_differs_from_every_earlier_one(self) -> None:
        asked = request(solutions=4, distinct_by=2)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        rosters = outcome.solutions
        assert len(rosters) == 4 and [r.number for r in rosters] == [1, 2, 3, 4]
        for earlier, later in combinations(rosters, 2):
            shared = len(set(earlier.player_ids) & set(later.player_ids))
            assert shared <= earlier.players - 2
        objective = [r.rating_unscaled - SALARY_TIE_BREAK * r.payroll for r in rosters]
        assert all(a >= b - 1e-6 for a, b in zip(objective, objective[1:], strict=False))

    def test_a_pool_that_cannot_give_more_gives_fewer(self) -> None:
        asked = request(solutions=5, distinct_by=4, min_players=5, max_players=5)
        outcome = solve(TEN, asked, budget=300 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert 1 < len(outcome.solutions) < 5
        assert outcome.status == OPTIMAL

    def test_the_second_roster_is_the_best_of_the_rest(self) -> None:
        asked = request(solutions=2, distinct_by=1)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        first, second = outcome.solutions
        worth = quality(TEN, REPLACEMENT)
        best_other = None
        for size in range(5, 7):
            for combo in combinations(TEN.index, size):
                if (
                    set(combo) == set(first.player_ids)
                    or TEN.loc[list(combo), "salary"].sum() > 100 * M
                ):
                    continue
                if TEN.loc[list(combo), "projected_share"].sum() > ON_COURT * 1.1:
                    continue
                value = worth.loc[list(combo)].sum()
                if best_other is None or value > best_other + 1e-9:
                    best_other = value
        assert worth.loc[list(second.player_ids)].sum() == pytest.approx(best_other)


class TestWhyNot:
    def test_too_few_players_and_too_dear(self) -> None:
        asked = request(min_players=12, max_players=15)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.status == INFEASIBLE and not outcome.found
        assert outcome.reasons[0] == "only 10 players are available and a roster needs at least 12."
        asked = request(budget=5 * M)
        outcome = solve(TEN, asked, budget=5 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.reasons == (
            "the 5 cheapest available players already cost $30,000,000, more than the budget of $5,000,000.",
        )

    def test_locked_players_beyond_the_budget_or_the_minutes(self) -> None:
        asked = request(locked=(1, 2, 3), budget=90 * M)
        outcome = solve(TEN, asked, budget=90 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert "the locked players alone cost $105,000,000" in outcome.reasons[0]
        stars = pool_of(*(player(n, 1, 5.0, 0.9) for n in range(1, 8)))
        asked = request(
            locked=(1, 2, 3, 4, 5, 6, 7), min_players=5, max_players=7, minutes_slack=0.0
        )
        outcome = solve(stars, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.reasons == (
            "the locked players' projected minutes alone add up to more than a season allows (126% of one).",
        )

    def test_roles_and_groups_the_pool_cannot_supply(self) -> None:
        asked = request(roles={"rim_protector": 4}, bigs=5)
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.reasons == (
            "only 2 available players fill the rim protector role and 4 are required.",
            "only 3 available players are bigs and 5 are required.",
        )

    def test_requirements_that_clash_only_together(self) -> None:
        # Two rim protectors and two primary creators within four players under a tight cap.
        asked = request(
            roles={"rim_protector": 2, "primary_creator": 2},
            budget=60 * M,
            min_players=5,
            max_players=5,
        )
        outcome = solve(TEN, asked, budget=60 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.status == INFEASIBLE
        assert outcome.reasons == (
            "no roster satisfies the requirements together within the budget.",
        )

    def test_a_locked_player_outside_the_pool(self) -> None:
        asked = request(locked=(99,))
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert (
            outcome.status == INFEASIBLE
            and "1 locked player(s) are not in the pool" in outcome.reasons[0]
        )

    def test_nobody_left_and_a_pool_missing_a_column(self) -> None:
        asked = request(excluded=tuple(TEN.index))
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.status == NO_POOL and outcome.reasons == (
            "no player is left to choose from.",
        )
        with pytest.raises(ValueError, match=r"the pool lacks \['projected_share'\]"):
            solve(
                TEN.drop(columns="projected_share"),
                request(),
                budget=100 * M,
                minimum_salary=None,
                replacement=REPLACEMENT,
            )

    def test_a_role_the_pool_has_no_column_for_counts_nobody(self) -> None:
        asked = request(roles={"connector": 1})
        outcome = solve(TEN, asked, budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)
        assert outcome.reasons == (
            "only 0 available players fill the connector role and 1 are required.",
        )


class TestTheRequest:
    def test_what_a_request_refuses(self) -> None:
        with pytest.raises(ValueError, match="max_players must be at least min_players"):
            request(min_players=10, max_players=8)
        with pytest.raises(ValueError, match="a custom budget needs an amount"):
            OptimizerRequest(
                payroll_season="2026-27", stats_season="2025-26", budget_mode=BudgetMode.CUSTOM
            )
        with pytest.raises(ValueError, match="both locked in and excluded"):
            request(locked=(1,), excluded=(1,))
        with pytest.raises(ValueError, match="more players are locked in than the roster may hold"):
            request(locked=tuple(range(1, 8)), max_players=5)
        with pytest.raises(ValueError, match="max_age must be at least min_age"):
            request(min_age=30, max_age=25)

    def test_what_a_request_says(self) -> None:
        assert request().players_range == "5 to 6"
        assert request(min_players=5, max_players=5).players_range == "5"
        assert (
            BudgetMode.FIRST_APRON.title == "First apron"
            and BudgetMode.CUSTOM.title == "Owner's budget"
        )
        asked = request()
        assert asked.budget_mode is BudgetMode.CUSTOM and asked.solutions == 1
        assert (
            OptimizerRequest(payroll_season="a", stats_season="b").budget_mode
            is BudgetMode.SALARY_CAP
        )


class TestOneSolverThread:
    """A9: HiGHS, called from one thread and then another, hung or crashed - in the test
    suite, a page's run solving and then the test itself. Every solve runs on one thread."""

    def ask(self) -> object:
        return solve(TEN, request(), budget=100 * M, minimum_salary=None, replacement=REPLACEMENT)

    def test_every_solve_runs_on_the_one_thread_whoever_asks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[int] = []
        real = optimizer.milp

        def recorded(*args: object, **kwargs: object) -> object:
            seen.append(threading.get_ident())
            return real(*args, **kwargs)

        monkeypatch.setattr(optimizer, "milp", recorded)
        self.ask()
        asker = threading.Thread(target=self.ask)
        asker.start()
        asker.join()
        assert len(seen) >= 2 and len(set(seen)) == 1
        assert seen[0] not in (threading.get_ident(), asker.ident)

    def test_threads_taking_turns_always_get_an_answer(self) -> None:
        """The pattern that hung at A9, forty times over: a new thread solves, then this one."""
        answers: list[object] = []
        for _ in range(40):
            asker = threading.Thread(target=lambda: answers.append(self.ask()), daemon=True)
            asker.start()
            asker.join(timeout=60)
            assert not asker.is_alive(), "a solve asked from a new thread never came back"
            answers.append(self.ask())
        assert len(answers) == 80
        assert all(found(outcome).player_ids == found(answers[0]).player_ids for outcome in answers)
