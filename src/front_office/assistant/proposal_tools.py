"""The roster optimizer as the assistant's ``optimize_roster`` tool (decision 0018, A5).

The tool runs the optimizer the Roster Optimizer page runs, with what the user asked for
- a budget, a roster size, roles and groups, players locked in or left out - and nothing
the user did not ask for: the page's example requirements are a starting point for a form,
not the lab's. Each roster found becomes a proposal the page shows with a *Save approved
roster* button; the tool saves nothing, and its text says so. The rosters are examples the
budget can pay for, never trades or signings the lab has checked are allowed, and options
to compare rather than a recommendation: each rests on the value model's projections. The
text avoids words a model would echo against the rules or the outcome: "the best", which is
a verdict, and "cannot", which reads as part of the question left unanswered.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import (
    DASH,
    Found,
    Handler,
    contract_evidence,
    grid,
    lab_evidence,
    missing,
)
from front_office.assistant.model_tools import MILLION, value_evidence
from front_office.domain.assistant import Chart, Evidence, ResultStatus
from front_office.domain.optimizer import BudgetMode, OptimizerRequest
from front_office.domain.proposals import ProposedPlayer, RosterProposal
from front_office.services import Lab, OptimizerError, OptimizerReport

NOT_A_PLAN = (
    "These are example rosters that fit the budget, built from the value model's forecasts: "
    "options to compare, not a recommendation, and not trades or signings checked against "
    "the league's rules."
)
SAVED_BY_THE_USER = (
    'Only the user\'s own click on "Save approved roster", under each option on the page, '
    "saves one."
)


def optimize_roster(lab: Lab, args: t.OptimizeRoster) -> Found:
    service = lab.optimizer
    status = service.status()
    title = "Roster options"
    if not status.is_available:
        return Found(ResultStatus.UNAVAILABLE, title, f"The optimizer cannot run: {status.reason}")
    roles = {item.key: item.name for item in lab.fit.archetypes()}
    unknown = sorted({item.role for item in args.role_minimums} - set(roles))
    if unknown:
        listed = ", ".join(f"{key} ({name})" for key, name in roles.items())
        return Found(
            ResultStatus.ERROR,
            title,
            f"No role called {', '.join(unknown)}. The roles are: {listed}.",
        )
    base = service.defaults()
    smallest = args.min_players or base.min_players
    try:
        request = OptimizerRequest(
            payroll_season=base.payroll_season,
            stats_season=base.stats_season,
            budget_mode=BudgetMode(args.budget_mode),
            budget=None
            if args.budget_millions is None
            else int(round(args.budget_millions * MILLION)),
            min_players=smallest,
            max_players=args.max_players or max(base.max_players, smallest),
            roles={item.role: item.count for item in args.role_minimums},
            guards=args.min_guards or 0,
            wings=args.min_wings or 0,
            bigs=args.min_bigs or 0,
            locked=tuple(args.lock_player_ids),
            excluded=tuple(args.exclude_player_ids),
            solutions=args.options,
        )
        report = service.solve(request)
    except (ValueError, OptimizerError) as error:
        return Found(ResultStatus.ERROR, title, f"The optimizer cannot run this request: {error}")
    evidence = (
        contract_evidence(lab),
        lab_evidence(lab, "player_value_scores, contract_years"),
        *value_evidence(lab),
    )
    season = request.payroll_season
    title = f"Roster options for {season}"
    if not report.found:
        reasons = " ".join(_sentence(reason) for reason in report.outcome.reasons)
        return missing(
            title,
            f"No roster for {season} meets these requirements under the "
            f"{request.budget_mode.title.lower()} of {_money(report.budget)}. "
            + (reasons or "No set of players meets all of them within the budget."),
            evidence,
        )
    return _options(report, lab.proposals.from_report(report), evidence)


def _sentence(reason: str) -> str:
    """The optimizer's reasons start in lower case, to follow a colon."""
    return reason[:1].upper() + reason[1:]


def _options(
    report: OptimizerReport,
    proposals: tuple[RosterProposal, ...],
    evidence: tuple[Evidence, ...],
) -> Found:
    first = proposals[0]
    season = first.payroll_season
    as_of = first.basis.contract_as_of
    head = (
        f"{len(proposals)} roster options for {season}, each under the "
        f"{first.budget_label.lower()} of {_money(first.budget)}. They are picked from the "
        f"{report.pool_size} players who have both a {season} salary and a forecast, and each "
        f"option differs from the others by at least {report.request.distinct_by} players. "
        f"What was asked for: {'; '.join(first.requirements)}. Salaries come from the contract "
        "file" + (f" as of {as_of:%Y-%m-%d}" if as_of else "") + f". {NOT_A_PLAN}"
    )
    rows = [
        [
            proposal.label,
            _money(proposal.payroll),
            _money(proposal.room),
            f"{proposal.rating:+.1f}",
            str(len(proposal.players)),
            _versus(first, proposal),
        ]
        for proposal in proposals
    ]
    header = [
        "Option",
        "Payroll",
        "Left under the budget",
        "Projected net rating",
        "Players",
        "Against Option A",
    ]
    lines = [head, grid(header, rows, limit=len(rows))]
    if len(proposals) < report.request.solutions:
        lines.append(
            f"{report.request.solutions} options were asked for; only {len(proposals)} meet the "
            f"requirements while differing by at least {report.request.distinct_by} players."
        )
    if first.error is not None:
        lines.append(
            "Projected net rating adds up each player's forecast for the minutes they are "
            "expected to play. For whole teams, these forecasts have typically been off by "
            f"about {first.error:.2f} points."
        )
    lines.append(f"{first.label}: {_paid(first.players)}.")
    others = {
        player.player_id: player
        for proposal in proposals[1:]
        for player in proposal.players
        if player.player_id not in first.player_ids
    }
    if others:
        lines.append(f"In other options but not in {first.label}: {_paid(others.values())}.")
    lines.append(SAVED_BY_THE_USER)
    warnings = tuple(_sentence(reason) for reason in report.outcome.reasons)
    if report.outcome.status == "time_limit":
        warnings += (
            "The optimizer ran out of time on at least one option, so that option may not be "
            "the strongest roster these requirements allow.",
        )
    bars = pd.DataFrame(
        {
            "option": [proposal.label for proposal in proposals],
            "rating": [proposal.rating for proposal in proposals],
            "text": [f"{proposal.rating:+.1f}" for proposal in proposals],
        }
    )
    chart = Chart(
        "bars",
        f"Roster options for {season}: projected net rating",
        bars,
        x="option",
        y="rating",
        text="text",
        y_title="Projected net rating (points per 100 possessions)",
    )
    return Found(
        ResultStatus.OK,
        f"Roster options for {season}",
        "\n".join(lines),
        pd.DataFrame(rows, columns=header),
        evidence,
        warnings,
        # As on the Roster Optimizer page: payrolls are sums, ratings the value model's, and
        # the budget and the requirements the user's.
        ("derived", "modeled", "assumption"),
        charts=(chart,),
        proposals=proposals,
    )


def _versus(first: RosterProposal, proposal: RosterProposal) -> str:
    if proposal is first:
        return DASH
    return (
        f"in: {', '.join(proposal.added) or 'nobody'}; "
        f"out: {', '.join(proposal.removed) or 'nobody'}"
    )


def _paid(players: Iterable[ProposedPlayer]) -> str:
    return ", ".join(f"{player.player_name} ({_money(player.salary)})" for player in players)


def _money(value: int) -> str:
    amount = int(value)
    return f"-${-amount:,}" if amount < 0 else f"${amount:,}"


PROPOSAL_HANDLERS: dict[str, Handler] = {"optimize_roster": optimize_roster}
