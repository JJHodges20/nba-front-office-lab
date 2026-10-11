"""The lab's fitted models as the assistant's tools (docs/AI_ASSISTANT_SPEC.md, A4).

``player_value``, ``roster_fit``, ``postseason_outlook`` and ``simulate_scenario`` call
the services that read the fitted files - the value model, the roster fit evidence, the
postseason model and the simulator's parameters - and nothing else. As with the read
tools, a handler picks the rows a question needs and writes each figure the way the
workbench does; it fits nothing and computes no figure the services do not return.

Every modeled figure goes out with what the lab knows of its error: a chance with its
95% interval and the model's record on seasons it had not seen, read both ways (decision
0014); a projection with how far projections of players that well known have missed; a
simulated season with the interval of the seasons drawn and the wins test. Fit is
description: there is no fit score, and no correction while the evidence does not
support one (decision 0012). Each result names the model files it read, with their
revisions, as its evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import (
    DASH,
    MAX_ROWS,
    Found,
    Handler,
    contract_evidence,
    grid,
    lab_evidence,
    label,
    missing,
    ordinal,
    over_seasons,
    seasons_held,
    shown,
)
from front_office.config.models import (
    fit_evidence_path,
    postseason_model_path,
    simulator_model_path,
    value_model_path,
)
from front_office.domain.assistant import Chart, Evidence, EvidenceKind, ResultStatus
from front_office.domain.postseason import PostseasonModel
from front_office.domain.scenario import (
    Adjustment,
    Availability,
    Development,
    Scenario,
    SubjectKind,
)
from front_office.domain.stages import BRACKET_STAGE_KEYS, stage
from front_office.services import (
    METRIC_CATALOGS,
    Lab,
    ScenarioReport,
    ValueStatus,
    probability_key,
)

CHANCES = METRIC_CATALOGS["Postseason model"]
"""Where a chance's format is defined: a share to one decimal."""
MILLION = 1_000_000
PLAYOFFS = "made_playoffs"
TITLE = "won_championship"
FIELD_NOT_MODELLED = (
    "These chances do not look at the other teams that season: they are the chances of any "
    "team this strong in a typical season."
)
NO_FIT_SCORE = (
    "Fit is described, not scored. The lab tested whether these fit measures make its "
    "predictions of a team any better, and they did not, so it gives no fit score."
)
ROLES_ARE_RULES = (
    "Roles are labels from simple rules on a player's statistics, not measurements of how "
    "they play. What the lab measures is how often a player keeps a role the next season."
)
VALUE_KEYS = (
    "impact",
    "impact_offense",
    "impact_defense",
    "wins_added",
    "minutes_share",
    "reliability",
)
PROJECTED_KEYS = (
    "projected_impact",
    "projected_offense",
    "projected_defense",
    "projected_wins",
    "projected_share",
    "projection_reliability",
)
PROJECTED_LIST_KEYS = (
    "projected_impact",
    "projected_wins",
    "projected_share",
    "projection_reliability",
)
LEADER_KEYS = ("wins_added", "impact", "impact_offense", "impact_defense", "minutes_share")
ROUND_KEYS = ("made_conference_finals", "made_finals", TITLE)


# --- evidence ----------------------------------------------------------------------------


def _file(lab: Lab, path: Path) -> str:
    try:
        return path.relative_to(lab.settings.project_root).as_posix()
    except ValueError:
        return path.name


def value_evidence(lab: Lab) -> tuple[Evidence, ...]:
    model = lab.value.model()
    if model is None:
        return ()
    return (
        Evidence(
            EvidenceKind.MODEL,
            f"Player value model, revision {model.revision}, fitted {model.fitted_at:%Y-%m-%d} "
            f"on seasons {model.fitted_on.first_season} to {model.fitted_on.last_season}",
            location=_file(lab, value_model_path(lab.settings.config_dir)),
            version=model.version,
        ),
    )


def postseason_evidence(lab: Lab, model: PostseasonModel) -> Evidence:
    return Evidence(
        EvidenceKind.MODEL,
        f"Postseason model, revision {model.revision}, fitted {model.fitted_at:%Y-%m-%d} "
        f"on seasons {model.fitted_on.first_season} to {model.fitted_on.last_season}",
        location=_file(lab, postseason_model_path(lab.settings.config_dir)),
        version=model.version,
    )


def simulator_evidence(lab: Lab) -> tuple[Evidence, ...]:
    model = lab.simulator.model()
    if model is None:
        return ()
    return (
        Evidence(
            EvidenceKind.MODEL,
            f"Simulator parameters, revision {model.revision}, measured "
            f"{model.fitted_at:%Y-%m-%d} against value model {model.value_model_version}",
            location=_file(lab, simulator_model_path(lab.settings.config_dir)),
            version=model.version,
        ),
    )


def fit_evidence(lab: Lab) -> tuple[Evidence, ...]:
    evidence = lab.fit.evidence()
    if evidence is None:
        return ()
    return (
        Evidence(
            EvidenceKind.MODEL,
            f"Roster fit evidence, revision {evidence.revision}, gathered "
            f"{evidence.fitted_at:%Y-%m-%d} on {evidence.team_seasons} team-seasons",
            location=_file(lab, fit_evidence_path(lab.settings.config_dir)),
            version=evidence.version,
        ),
    )


def _value_warnings(lab: Lab) -> tuple[str, ...]:
    status = lab.value.status()
    if status.needs_build:
        return (
            f"The value model on file is revision {status.revision}, but the data build applied "
            f"{status.applied_revision}: the figures are the build's until fol build runs again.",
        )
    return ()


def _postseason_warnings(lab: Lab) -> tuple[str, ...]:
    status = lab.postseason.status()
    if status.is_fitted and not status.is_current:
        return (
            f"The postseason model was fitted against value model {status.value_model_version}; "
            f"the database holds {status.applied_value_version}: fit it again "
            "(fol playoffs fit --write).",
        )
    return ()


# --- formatting --------------------------------------------------------------------------


def _absent(value: object) -> bool:
    try:
        return value is None or bool(pd.isna(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _text(value: object) -> str:
    return value if isinstance(value, str) and value else DASH


def _name(lab: Lab, player_id: int) -> str:
    names = lab.entities.players()["full_name"]
    return str(names.get(int(player_id), f"Player {player_id}"))


def _chance(key: str, value: object) -> str:
    return shown(CHANCES, probability_key(key), value)


def _chance_with_interval(key: str, probability: object, low: object, high: object) -> str:
    return f"{_chance(key, probability)} (95% interval {_chance(key, low)} to {_chance(key, high)})"


def _money(value: object) -> str:
    if _absent(value):
        return DASH
    amount = int(round(float(value)))  # type: ignore[arg-type]
    return f"-${-amount:,}" if amount < 0 else f"${amount:,}"


def _money_change(value: object) -> str:
    if _absent(value):
        return DASH
    amount = int(round(float(value)))  # type: ignore[arg-type]
    return f"+${amount:,}" if amount >= 0 else f"-${-amount:,}"


def _points(value: object) -> str:
    """A change in a chance, in percentage points."""
    return DASH if _absent(value) else f"{float(value) * 100:+.1f} points"  # type: ignore[arg-type]


def _signed(value: object, decimals: int = 1) -> str:
    return DASH if _absent(value) else f"{float(value):+.{decimals}f}"  # type: ignore[arg-type]


def _share(value: object) -> str:
    return DASH if _absent(value) else f"{float(value):.0%}"  # type: ignore[arg-type]


def _place(value: object) -> str:
    return DASH if _absent(value) else ordinal(round(float(value)))  # type: ignore[arg-type]


STAGE_HEADER = ("Stage", "Chance", "95% interval")


def _stage_rows(stages: pd.DataFrame) -> list[list[str]]:
    return [
        [
            row.label,
            _chance(row.key, row.probability),
            f"{_chance(row.key, row.low)} to {_chance(row.key, row.high)}",
        ]
        for row in stages.itertuples(index=False)
    ]


def _shown(header: Sequence[str], rows: Sequence[Sequence[str]]) -> pd.DataFrame:
    """Rows as the model read them, for the page: a chance as a percentage rather than a
    bare share. The figures behind them are in the result's chart and its export."""
    return pd.DataFrame([list(row) for row in rows], columns=list(header))


def _stage_chart(stages: pd.DataFrame, title: str) -> Chart:
    frame = pd.DataFrame(
        {
            "stage": stages["label"].to_numpy(),
            "probability": stages["probability"].to_numpy(),
            "low": stages["low"].to_numpy(),
            "high": stages["high"].to_numpy(),
            "text": [
                _chance_with_interval(row.key, row.probability, row.low, row.high)
                for row in stages.itertuples(index=False)
            ],
        }
    )
    return Chart(
        "intervals",
        title,
        frame,
        x="stage",
        y="probability",
        text="text",
        low="low",
        high="high",
        y_title="Chance, with its 95% interval",
        tickformat=".0%",
        y_range=(0.0, 1.0),
    )


# --- player_value ------------------------------------------------------------------------


def player_value(lab: Lab, args: t.PlayerValue) -> Found:
    status = lab.value.status()
    if not status.is_available:
        return Found(
            ResultStatus.UNAVAILABLE,
            "Player value",
            "No player has a value on record: the value model has to be fitted and applied "
            "first (fol value fit --write, then fol build).",
        )
    if args.view in ("player", "breakdown") and args.player_id is None:
        return Found(ResultStatus.ERROR, "Player value", f"The {args.view} view needs player_id.")
    if args.view == "model_evidence":
        return _value_card(lab)
    if args.view == "projections":
        return _projections(lab, args.player_id, status.upcoming)
    if args.view == "value_for_money":
        return _for_money(lab, args.season, status)
    if args.view == "player":
        return _value_history(lab, int(args.player_id), status.upcoming)  # type: ignore[arg-type]
    season = args.season or status.seasons[0]
    if season not in status.seasons:
        ahead = (
            f" {season} is still to be played: what the model expects of it is the projections."
            if season == status.upcoming
            else ""
        )
        return missing(
            f"Player value, {season}",
            f"The value model has valued {seasons_held(status.seasons)}; nothing for {season}."
            + ahead,
        )
    if args.view == "breakdown":
        return _breakdown(lab, int(args.player_id), season)  # type: ignore[arg-type]
    if args.view == "roles":
        return _roles(lab, args.player_id, season)
    return _leaders(lab, season)


def _valued(
    lab: Lab,
    title: str,
    text: str,
    table: pd.DataFrame,
    *,
    warnings: tuple[str, ...] = (),
    charts: tuple[Chart, ...] = (),
) -> Found:
    return Found(
        ResultStatus.OK,
        title,
        text,
        table,
        (lab_evidence(lab, "player_value_scores, player_seasons"), *value_evidence(lab)),
        _value_warnings(lab) + warnings,
        ("modeled", "derived"),
        charts=charts,
    )


def _leaders(lab: Lab, season: str) -> Found:
    frame = lab.value.season(season)
    catalog = lab.value.metrics
    rows = [
        [str(int(row["wins_rank"])), row["player_name"], _text(row["team"])]
        + [shown(catalog, key, row[key]) for key in LEADER_KEYS]
        for _, row in frame.iterrows()
    ]
    header = ["Rank", "Player", "Team", *(label(catalog, key) for key in LEADER_KEYS)]
    head = (
        f"The value model's most valuable players of {season}, ranked by wins above "
        f"replacement among the {len(frame)} players it rated that season (1 is the most). "
        "These are the model's estimates, not measurements."
    )
    top = frame.head(MAX_ROWS)
    bars = pd.DataFrame(
        {
            "player": top["player_name"].to_numpy(),
            "wins_added": top["wins_added"].to_numpy(),
            "text": [shown(catalog, "wins_added", value) for value in top["wins_added"]],
        }
    )
    chart = Chart(
        "bars",
        f"Wins above replacement, {season}: the {len(top)} most valuable",
        bars,
        x="player",
        y="wins_added",
        text="text",
        y_title=label(catalog, "wins_added"),
        metric="wins_added",
    )
    return _valued(
        lab,
        f"Most valuable players by the value model, {season}",
        head + "\n" + grid(header, rows),
        frame,
        charts=(chart,),
    )


def _value_history(lab: Lab, player_id: int, upcoming: str | None) -> Found:
    name = _name(lab, player_id)
    history = lab.value.player(player_id)
    played = history[history["impact"].notna()]
    ahead = history[history["impact"].isna() & history["projected_impact"].notna()]
    title = f"{name}: the value model, season by season"
    if played.empty and ahead.empty:
        return missing(title, f"The value model has no figures for {name}.")
    catalog = lab.value.metrics
    rows = [
        [row["season"], _text(row["team"])] + [shown(catalog, key, row[key]) for key in VALUE_KEYS]
        for _, row in played.sort_values("season", ascending=False).iterrows()
    ]
    header = ["Season", "Team", *(label(catalog, key) for key in VALUE_KEYS)]
    parts = [f"{name} season by season, as the value model rates them (estimates), newest first."]
    if rows:
        parts.append(grid(header, rows))
    if not ahead.empty:
        row = ahead.iloc[-1]
        parts.append(_projection_lines(lab, player_id, name, row, str(row["season"])))
    elif upcoming is not None:
        parts.append(f"No projection of {name} into {upcoming}.")
    return _valued(
        lab,
        title,
        "\n".join(parts),
        history,
        charts=over_seasons(
            played,
            "impact",
            catalog,
            f"{name}: impact by season",
            reference=0.0,
            reference_label="League-average minute",
        ),
    )


def _projection_lines(lab: Lab, player_id: int, name: str, row: pd.Series, season: str) -> str:
    """A projection in words, with what the lab knows of its error: how far projections of
    players known as well as this one have missed (the simulator's measure of one player)
    and how far the value model's forecasts of a team have missed."""
    catalog = lab.value.metrics
    figures = ", ".join(
        f"{label(catalog, key).lower()} {shown(catalog, key, row.get(key))}"
        for key in PROJECTED_KEYS
    )
    lines = [f"{name} going into {season}, the value model's projection: {figures}."]
    band = lab.simulator.projection_miss(player_id)
    if _absent(row.get("projection_reliability")):
        lines.append(
            f"{name} has no earlier season to go on, so the model gives them the level of a "
            "typical new player."
        )
    elif band is not None:
        # The signed miss is written as well: a figure the model writes with its sign must
        # be one it was given with its sign (checker.supports).
        side = "below" if band.mean_miss < 0 else "above"
        lines.append(
            "How sure is this? The value model is tested on whole teams, so there is no "
            "tested range for one player. For players the model knew this well "
            f"({band.players:,} past player-seasons), projections were typically off by about "
            f"{band.spread:.2f} points of impact either way, and players came out "
            f"{abs(band.mean_miss):.2f} points {side} their projections on average "
            f"({band.mean_miss:+.2f})."
        )
    model = lab.value.model()
    if model is not None and model.validation.projected is not None:
        tested = model.validation
        lines.append(
            "For whole teams, its forecasts of a season's net rating have typically been off "
            f"by about {tested.projected.rmse:.2f} points (tested on {tested.first_test_season} "
            f"to {tested.last_test_season})."
        )
    return "\n".join(lines)


def _projections(lab: Lab, player_id: int | None, upcoming: str | None) -> Found:
    frame = lab.value.projections()
    title = f"Projections into {upcoming}" if upcoming else "Projections"
    if frame.empty or upcoming is None:
        return missing(title, "No season is being looked ahead to, so there are no projections.")
    catalog = lab.value.metrics
    if player_id is not None:
        name = _name(lab, player_id)
        title = f"{name}: projection into {upcoming}"
        if player_id not in frame.index:
            return missing(title, f"The value model has no projection of {name} into {upcoming}.")
        row = frame.loc[player_id]
        lines = [_projection_lines(lab, player_id, name, row, upcoming)]
        if not _absent(row["last_season"]):
            lines.append(
                f"Last season on record: {row['last_season']}, impact "
                f"{shown(catalog, 'impact', row['last_impact'])}, share of team minutes "
                f"{shown(catalog, 'minutes_share', row['last_minutes_share'])}."
            )
        return _valued(lab, title, "\n".join(lines), frame.loc[[player_id]])
    rows = [
        [row["player_name"], _text(row["team"])]
        + [shown(catalog, key, row[key]) for key in PROJECTED_LIST_KEYS]
        for _, row in frame.iterrows()
    ]
    header = ["Player", "Team", *(label(catalog, key) for key in PROJECTED_LIST_KEYS)]
    head = (
        f"The value model's forecasts for {upcoming}, most projected wins first "
        f"({len(frame)} players). These are the model's estimates, not measurements."
    )
    return _valued(lab, title, head + "\n" + grid(header, rows), frame)


def _breakdown(lab: Lab, player_id: int, season: str) -> Found:
    name = _name(lab, player_id)
    parts = lab.value.parts(player_id, season)
    title = f"{name}, {season}: where the impact comes from"
    if parts.empty:
        return missing(title, f"{name} has no impact on record for {season}.")
    catalog = lab.value.metrics
    impact = lab.value.player(player_id).set_index("season")["impact"].get(season)
    rows = [[row["label"], shown(catalog, row["key"], row["value"])] for _, row in parts.iterrows()]
    text = (
        f"{name}'s impact in {season} was {shown(catalog, 'impact', impact)} by the value "
        "model's estimate. Here is what it is made of:\n"
        + grid(["Part", "Points per 100 possessions"], rows, limit=len(rows))
    )
    bars = parts.assign(
        text=[
            shown(catalog, key, value)
            for key, value in zip(parts["key"], parts["value"], strict=True)
        ]
    )
    chart = Chart(
        "bars",
        f"{name}, {season}: the parts of impact",
        bars[["label", "value", "text"]],
        x="label",
        y="value",
        text="text",
        y_title="Points per 100 possessions",
    )
    return _valued(lab, title, text, parts, charts=(chart,))


def _roles(lab: Lab, player_id: int | None, season: str) -> Found:
    summary = lab.value.role_summary(season).set_index("name")
    if player_id is None:
        rows = [
            [name, str(int(row["filled"])), _share(row["again"]), _share(row["anyone"])]
            for name, row in summary.iterrows()
        ]
        text = (
            f"The lab's roles in {season}: how many players have each, how often a player keeps "
            "the role the next season, and, for comparison, how often any player rated for it "
            "has it the next season.\n"
            + grid(
                ["Role", "Players", "Kept next season", "Any player"],
                rows,
                limit=len(rows),
            )
        )
        return _valued(
            lab, f"Roles, {season}", text, summary.reset_index(), warnings=(ROLES_ARE_RULES,)
        )
    name = _name(lab, player_id)
    title = f"{name}: roles, {season}"
    roles = lab.value.roles(season)
    if player_id not in roles.index:
        text = f"{name} has none of the lab's roles in {season}."
        return _valued(lab, title, text, summary.reset_index(), warnings=(ROLES_ARE_RULES,))
    mine = roles.loc[player_id]
    filled = [
        role.strip() for role in str(mine["roles"]).split(",") if role.strip() in summary.index
    ]
    rows = [
        [
            role + (" (primary)" if role == mine["role"] else ""),
            _share(summary.at[role, "again"]),
            _share(summary.at[role, "anyone"]),
        ]
        for role in filled
    ]
    text = (
        f"{name}'s roles in {season}, with how often a player keeps each role the next season "
        "and, for comparison, how often any player rated for it has it:\n"
        + grid(["Role", "Kept next season", "Any player"], rows, limit=len(rows))
    )
    return _valued(lab, title, text, summary.loc[filled].reset_index(), warnings=(ROLES_ARE_RULES,))


def _for_money(lab: Lab, season: str | None, status: ValueStatus) -> Found:
    title = "Value for money"
    if not lab.contracts.available:
        return Found(
            ResultStatus.UNAVAILABLE,
            title,
            "No contract file has been imported, so there are no salaries to set against the "
            "players' value. They come from a file the user supplies (docs/CONTRACT_DATA.md).",
        )
    season = season or status.upcoming or lab.status().default_payroll_season
    evidence = (contract_evidence(lab),)
    title = f"Value for money, {season}"
    money = lab.value.for_money(str(season))
    if money.basis is None or money.players.empty:
        return missing(
            title,
            f"No salary in {season} can be set against a value: the value model has valued "
            f"{seasons_held(status.seasons)} and projects {status.upcoming or 'no season'}.",
            evidence,
        )
    projected = money.basis == "projected"
    head = (
        f"{season} salaries from your contract file, set against "
        + ("the wins above replacement the value model expects in the season"
           if projected else "the wins above replacement the value model gave the season")
        + "."
    )  # fmt: skip
    market = money.market
    if market is not None:
        head += (
            f" Across {market.contracts} contracts, teams paid about "
            f"{_money(market.price_per_win)} per win on top of {_money(market.replacement_cost)} "
            f"for a replacement-level player; wins explain {market.r2:.0%} of the differences "
            "in salary. A player's surplus is what that rate would pay for their wins, minus "
            "their salary: the lab's estimate, not a market price."
        )
    catalog = lab.value.metrics
    wins = "projected_wins" if projected else "wins_added"
    rows = [
        [
            row["player_name"],
            _text(row["team"]),
            _money(row["salary"]),
            shown(catalog, wins, row["wins"]),
            _money(row["market_value"]),
            _money(row["surplus"]),
        ]
        for _, row in money.players.iterrows()
    ]
    header = ["Player", "Team", "Salary", label(catalog, wins), "Worth at that rate", "Surplus"]
    text = head + "\n" + grid(header, rows)
    if money.unvalued:
        text += f"\n{money.unvalued} players with a salary in {season} have no rating to compare it with."
    return Found(
        ResultStatus.OK,
        title,
        text,
        money.players,
        (*evidence, lab_evidence(lab, "player_value_scores"), *value_evidence(lab)),
        _value_warnings(lab)
        + ("Only this season of each contract is rated: the model looks one season ahead.",),
        ("measured", "modeled"),
    )


def _value_card(lab: Lab) -> Found:
    card = lab.value.card()
    if card is None:
        return Found(
            ResultStatus.UNAVAILABLE,
            "The value model",
            "No value model has been fitted (fol value fit --write).",
        )
    model, tested = card.model, card.model.validation
    head = (
        f"The player value model, revision {model.revision}, fitted {model.fitted_at:%Y-%m-%d} "
        f"on {model.fitted_on.first_season} to {model.fitted_on.last_season} "
        f"({model.fitted_on.team_seasons} team-seasons). How it was tested: each season from "
        f"{tested.first_test_season} to {tested.last_test_season} was predicted using only the "
        f"seasons before it ({tested.team_seasons} team-seasons). Given the minutes players "
        f"actually played, its team ratings were typically off by {tested.net.rmse:.2f} points "
        f"of net rating (RMSE; average miss {tested.net.mae:.2f})"
    )
    if tested.projected is not None:
        head += (
            f"; when the minutes are forecast too, as in a real forecast, by "
            f"{tested.projected.rmse:.2f}"
        )
    head += (
        ". Compared with simpler methods - the model's typical miss minus the method's, so "
        "below zero means the model did better, with a 95% interval:"
    )
    rows = []
    for _, row in card.baselines.iterrows():
        if row["key"] == "value_model":
            rows.append([row["label"], f"{row['rmse']:.2f}", DASH, DASH])
        else:
            rows.append(
                [
                    row["label"],
                    f"{row['rmse']:.2f}",
                    f"{row['difference']:+.2f}",
                    f"{row['low']:+.2f} to {row['high']:+.2f}",
                ]
            )
    header = ["Method", "Typical miss (RMSE)", "Difference", "95% interval"]
    lines = [head, grid(header, rows, limit=len(rows))]
    costliest = card.ablations.head(3)
    if not costliest.empty:
        lines.append(
            "The parts that matter most (how much bigger the typical miss gets without each): "
            + "; ".join(
                f"{row['label']} {row['difference']:+.2f} ({row['low']:+.2f} to {row['high']:+.2f})"
                for _, row in costliest.iterrows()
            )
            + "."
        )
    others = card.baselines[card.baselines["key"] != "value_model"].reset_index(drop=True)
    plotted = others[["label", "difference", "low", "high"]].assign(
        text=[
            f"{difference:+.2f} (95% interval {low:+.2f} to {high:+.2f})"
            for difference, low, high in zip(
                others["difference"], others["low"], others["high"], strict=True
            )
        ]
    )
    chart = Chart(
        "intervals",
        "How much better the value model did than simpler methods",
        plotted,
        x="label",
        y="difference",
        text="text",
        low="low",
        high="high",
        y_title="Points of net rating (below zero, the model did better)",
        reference=0.0,
        reference_label="No difference",
    )
    return Found(
        ResultStatus.OK,
        "The player value model and its test",
        "\n".join(lines),
        card.baselines,
        value_evidence(lab),
        _value_warnings(lab),
        ("modeled",),
        charts=(chart,),
    )


# --- roster_fit --------------------------------------------------------------------------


def roster_fit(lab: Lab, args: t.RosterFit) -> Found:
    if args.view == "evidence":
        return _fit_evidence_found(lab)
    if args.view == "champions":
        return _champions(lab)
    status = lab.fit.status()
    if args.roster_id is not None:
        report = lab.fit.roster(args.roster_id)
    elif args.team_id is not None:
        season = args.season or (status.seasons[0] if status.seasons else None)
        if season is None or season not in status.seasons:
            return missing(
                "Roster fit",
                f"The lab has team fit profiles for {seasons_held(status.seasons)}; nothing for "
                f"{season}.",
            )
        report = lab.fit.team(args.team_id, season)
    else:
        return Found(
            ResultStatus.ERROR,
            "Roster fit",
            "A profile needs team_id (with a season) or roster_id.",
        )
    title = f"{report.name}, {report.season}: how the players fit together"
    if report.is_empty:
        return missing(title, f"No player of {report.name} has minutes in {report.season}.")
    catalog = lab.fit.metrics
    placed = report.placed
    rows = [
        [row["name"], shown(catalog, row["key"], row["value"]), _place(row["percentile"])]
        for _, row in placed.iterrows()
    ]
    teams = int(placed["teams"].max()) if len(placed) else 0
    coverage = "; ".join(
        f"{row['name']} {row['count']}" + (f" ({row['filled_by']})" if row["filled_by"] else "")
        for _, row in report.coverage.iterrows()
    )
    parts = report.parts
    sums = (
        f"Adding up the players: their impacts come to {_signed(parts.impact)} for these "
        f"minutes ({_signed(parts.projected)} as forecast before the season)"
        + (
            f"; the value model's typical miss for a whole team is {parts.error:.2f}."
            if parts.error is not None
            else "."
        )
    )
    if parts.correction is None:
        sums += " Fit adds nothing to this total, and there is no fit score."
    else:
        sums += f" The fit evidence adds {_signed(parts.correction)} to it."
    text = "\n".join(
        [
            f"{report.name}, {report.season}: each fit measure, averaged over the players by the "
            f"minutes they played, compared with the season's {teams} teams (percentile: the "
            "100th is the highest value, the 50th the middle). This describes the team; it is "
            "not a rating:",
            grid(["Measure", "Value", "Percentile"], rows, limit=len(rows)),
            f"Roles in the rotation: {coverage}.",
            sums,
        ]
    )
    ranked = placed.dropna(subset=["percentile"])
    chart = Chart(
        "percentiles",
        f"{report.name}, {report.season}: each fit measure among the season's teams",
        pd.DataFrame(
            {
                "measure": ranked["name"].to_numpy(),
                "percentile": ranked["percentile"].to_numpy(),
                "value": [
                    shown(catalog, key, value)
                    for key, value in zip(ranked["key"], ranked["value"], strict=True)
                ],
            }
        ),
        x="measure",
        y="percentile",
        text="value",
        # As the Roster Fit page writes it: a high value is not a better one here.
        y_title=f"Percentile among the teams of {report.season}",
    )
    warnings: tuple[str, ...] = ()
    if status.is_gathered and not status.is_current:
        warnings += (
            "The fit evidence was gathered against another value model or archetype version "
            "than the database holds: gather it again (fol fit test --write).",
        )
    if report.absent:
        warnings += (
            f"No minutes in {report.season}, so not in the profile: {', '.join(report.absent)}.",
        )
    table = _shown(["Measure", "Value", "Percentile"], rows)
    table.insert(0, "Area", placed["area"].to_numpy())
    return Found(
        ResultStatus.OK,
        title,
        text,
        table,
        (
            lab_evidence(lab, "team_fit_profiles, player_seasons"),
            *fit_evidence(lab),
            *value_evidence(lab),
        ),
        warnings,
        ("derived", "modeled"),
        () if status.usable else (NO_FIT_SCORE,),
        (chart,) if not ranked.empty else (),
    )


def _fit_evidence_found(lab: Lab) -> Found:
    evidence = lab.fit.evidence()
    title = "The roster fit evidence"
    if evidence is None:
        return Found(
            ResultStatus.UNAVAILABLE,
            title,
            "No fit evidence has been gathered (fol fit test --write): nothing says whether fit "
            "explains anything, and the lab treats fit as description.",
        )
    combined = evidence.combined
    clear = [item for item in evidence.measures if item.is_distinguishable]
    verdict = (
        "clearly better, so the lab adds a fit correction to a roster's total."
        if combined.is_usable
        else "not clearly better, so the lab adds nothing and gives no fit score."
    )
    head = (
        "Do the fit measures help predict how good a team is? Tested on "
        f"{evidence.team_seasons} team-seasons from {evidence.first_test_season} to "
        f"{evidence.last_test_season} that the lab had not seen (revision {evidence.revision}): "
        "adding up the players' impacts was typically off by "
        f"{evidence.baseline_rmse:.2f} points of net rating (RMSE). With every fit measure "
        f"added: {combined.rmse:.2f}, a change of {combined.change.difference:+.2f} (95% "
        f"interval {combined.change.low:+.2f} to {combined.change.high:+.2f}) - {verdict}"
    )
    rows = [
        [
            item.name,
            f"{item.change.difference:+.3f}",
            f"{item.change.low:+.3f} to {item.change.high:+.3f}",
            "yes" if item.is_distinguishable else "no",
        ]
        for item in evidence.measures
    ]
    text = (
        head + f"\nEach measure on its own ({len(clear)} of {len(evidence.measures)} made the "
        "predictions clearly better; the change in the typical miss, below zero is better):\n"
        + grid(["Measure", "Change", "95% interval", "Clearly better"], rows)
    )
    table = pd.DataFrame(
        [
            {
                "measure": item.name,
                "area": item.area,
                "teams": item.teams,
                "rmse": item.rmse,
                "change": item.change.difference,
                "low": item.change.low,
                "high": item.change.high,
                "clear": item.is_distinguishable,
            }
            for item in evidence.measures
        ]
    )
    return Found(
        ResultStatus.OK,
        title,
        text,
        table,
        fit_evidence(lab) + value_evidence(lab),
        kinds=("modeled",),
    )


def _champions(lab: Lab) -> Found:
    frame = lab.fit.champions()
    title = "Where champions' rosters stood on each fit measure"
    if frame.empty or int(frame["champions"].max()) == 0:
        return missing(title, "No champion has a fit profile in the lab.")
    rows = [
        [
            row["name"],
            str(row["champions"]),
            _place(row["median_percentile"]),
            str(row["top_third"]),
            str(row["bottom_third"]),
        ]
        for _, row in frame.iterrows()
    ]
    head = (
        "Where each champion stood among its own season's teams, measure by measure: the "
        "middle (median) percentile - near the 50th means champions looked like everyone else "
        "- and how many were in the top and the bottom third. This is history, not a "
        "requirement."
    )
    header = ["Measure", "Champions", "Median percentile", "Top third", "Bottom third"]
    return Found(
        ResultStatus.OK,
        title,
        head + "\n" + grid(header, rows, limit=len(rows)),
        frame,
        (lab_evidence(lab, "team_fit_profiles, team_seasons"),),
        kinds=("derived",),
    )


# --- postseason_outlook ------------------------------------------------------------------


def postseason_outlook(lab: Lab, args: t.PostseasonOutlook) -> Found:
    service = lab.postseason
    model = service.model()
    title = "Postseason outlook"
    if model is None:
        return Found(
            ResultStatus.UNAVAILABLE,
            title,
            "No postseason model has been fitted (fol playoffs fit --write), so the lab gives "
            "no chances.",
        )
    status = service.status()
    view = args.view
    if view in ("team", "roster") and args.net_rating is not None:
        # At A4 a model asked the team view about "a team with a +5.0 net rating", with no
        # team: a rating and no subject can only mean a team of that strength.
        if (args.team_id if view == "team" else args.roster_id) is None:
            view = "strength"
    if view == "model_record":
        return _record_found(lab, model)
    if view == "bracket":
        return _bracket(lab, model, args.season or (status.seasons[0] if status.seasons else None))
    if view == "season_odds":
        return _season_odds(lab, model, args.season or status.latest)
    if view == "strength":
        if args.net_rating is None:
            return Found(
                ResultStatus.ERROR,
                title,
                "The strength view needs net_rating: the model judges a team by its regular-season "
                "net rating and the quality of its best players, not by its record. For how often "
                "past teams with a record like that went far, historical_benchmarks with measure "
                "wins_per_82 gives a share of past teams - not a chance.",
            )
        outlook = service.outlook(args.net_rating, args.top_players)
        typical = (
            " (the usual level for teams with that rating, since none was given)"
            if args.top_players is None
            else ""
        )
        head = (
            f"A team with a regular-season net rating of {_signed(args.net_rating)} and "
            f"top-player quality {_signed(outlook.top_players, 2)}{typical}: the model's chance "
            "of each stage for a team like this, before the playoff matchups are known."
        )
        named = f"A team of net rating {_signed(args.net_rating)}"
        return _chances(lab, model, named, head, outlook.stages, None)
    if view == "roster":
        if args.roster_id is None:
            return Found(ResultStatus.ERROR, title, "The roster view needs roster_id.")
        subject = service.roster(args.roster_id)
    else:
        if args.team_id is None:
            return Found(
                ResultStatus.ERROR,
                title,
                "The team view needs team_id; for a hypothetical team, use the strength view "
                "with its net_rating.",
            )
        season = args.season or status.latest
        if season is None:
            return missing(title, "The lab holds no team statistics.")
        ahead = lab.simulator.status()
        if season == ahead.upcoming and ahead.is_available:
            # A season not yet played has no strength to read: the lab's chances for it are
            # the simulator's (decision 0015). At A4 a model asked this view about 2026-27,
            # was told so, and asked the user whether to simulate instead of simulating.
            simulator = lab.simulator
            drawn = simulator.run(simulator.default_scenario(SubjectKind.TEAM, args.team_id))
            found = _scenario(lab, drawn)
            said = (
                f"{season} has not been played yet, so these chances come from the simulator, "
                "using the value model's forecasts for the team as it stands.\n"
            )
            return replace(found, text=said + found.text)
        subject = service.team(args.team_id, season)
    title = f"{subject.name}: postseason chances from {subject.season}"
    if subject.outlook is None:
        ahead = (
            f" {subject.season} has not been played yet: simulate_scenario forecasts the season "
            "ahead; this view reads a season already played."
            if status.latest is not None and subject.season > status.latest
            else ""
        )
        return missing(title, subject.note + ahead)
    best = (
        f" (the average impact of its {len(subject.top_names)} best players: "
        f"{', '.join(subject.top_names)})"
        if subject.top_names
        else ""
    )
    head = (
        f"{subject.name}, judged by its {subject.season} regular season: net rating "
        f"{_signed(subject.net_rating)} and top-player quality {_signed(subject.top_players, 2)}"
        f"{best}. The model's chance of each stage for a team like this, in a typical season:"
    )
    happened = _happened(lab, args.team_id, subject.season) if view == "team" else None
    return _chances(lab, model, title, head, subject.outlook.stages, happened)


def _happened(lab: Lab, team_id: int | None, season: str) -> str | None:
    if team_id is None:
        return None
    standings = lab.league.standings(season).set_index("team_id")
    if team_id not in standings.index:
        return None
    result = standings.at[team_id, "postseason_result"]
    return f"What happened in {season}: {result}." if isinstance(result, str) else None


def _chances(
    lab: Lab,
    model: PostseasonModel,
    title: str,
    head: str,
    stages: pd.DataFrame,
    happened: str | None,
) -> Found:
    rows = _stage_rows(stages)
    parts = [head, grid(list(STAGE_HEADER), rows, limit=len(rows))]
    if happened:
        parts.append(happened)
    parts.append(_record(model))
    return Found(
        ResultStatus.OK,
        title,
        "\n".join(parts),
        _shown(STAGE_HEADER, rows),
        (lab_evidence(lab, "team_seasons, player_value_scores"), postseason_evidence(lab, model)),
        (FIELD_NOT_MODELLED, *_postseason_warnings(lab)),
        ("modeled",),
        charts=(_stage_chart(stages, f"{title}: the chance of each stage"),),
    )


def _record(model: PostseasonModel) -> str:
    """The season model's record on team-seasons it had not seen, read both ways: with
    each season's own rating, and from the rating the value model predicted before it."""
    evaluation = model.evaluation
    ahead = evaluation.before_season
    before = {item.key: item for item in ahead.stages} if ahead is not None else {}
    rows = []
    for item in evaluation.season.stages:
        read = before.get(item.key)
        rows.append(
            [
                stage(item.key).label,
                f"{item.reached} of {item.cases}",
                f"{item.log_loss:.3f}",
                f"{item.baselines[0].log_loss:.3f}" if item.baselines else DASH,
                DASH if read is None else f"{read.log_loss:.3f}",
            ]
        )
    span = (
        f"{ahead.first_test_season} to {ahead.last_test_season}"
        if ahead is not None
        else f"from {model.spec.first_test_season}"
    )
    header = ["Stage", "Teams that got there", "Model's score", "Same chance for all", "Pre-season"]
    return (
        f"How this model has done on team-seasons it had not seen ({span}). Each score is a "
        "log loss: lower is better. 'Same chance for all' gives every team the same chance; "
        "'Pre-season' scores the model using only the rating forecast before each season, as "
        "a real forecast would:\n" + grid(header, rows, limit=len(rows))
    )


def _bracket(lab: Lab, model: PostseasonModel, season: str | None) -> Found:
    title = f"The {season} playoff bracket under the model"
    if season is None:
        return missing(title, "No postseason is decided and on record in the lab.")
    report = lab.postseason.bracket(season)
    if report.is_empty:
        return missing(title, report.note)
    teams = report.teams
    key = probability_key(TITLE)
    # A seed is a place in a conference, and says which, for the answer checker (A7).
    rows = [
        [
            row["team_name"],
            DASH
            if _absent(row["seed"])
            else f"{ordinal(int(row['seed']))} in the {row['conference']}",
        ]
        + [_chance(stage_key, row[probability_key(stage_key)]) for stage_key in ROUND_KEYS]
        + [
            f"{_chance(TITLE, row[f'{key}_low'])} to {_chance(TITLE, row[f'{key}_high'])}",
            _text(row["result"]),
        ]
        for _, row in teams.iterrows()
    ]
    head = (
        f"The {season} playoff teams' chance of each round, as the model saw them before the "
        "first game, next to what actually happened."
    )
    if report.favourite:
        head += f" Favourite: {report.favourite} ({_chance(TITLE, report.favourite_probability)})."
    if report.champion:
        head += f" Champion: {report.champion} ({_chance(TITLE, report.champion_probability)})."
    header = [
        "Team",
        "Seed",
        *(stage(item).label for item in ROUND_KEYS),
        "Title, 95% interval",
        "Result",
    ]
    plotted = pd.DataFrame(
        {
            "team": teams["team_name"].to_numpy(),
            "probability": teams[key].to_numpy(),
            "low": teams[f"{key}_low"].to_numpy(),
            "high": teams[f"{key}_high"].to_numpy(),
            "text": [
                _chance_with_interval(TITLE, probability, low, high)
                for probability, low, high in zip(
                    teams[key], teams[f"{key}_low"], teams[f"{key}_high"], strict=True
                )
            ],
        }
    )
    chart = Chart(
        "intervals",
        f"The {season} playoff teams: the chance of the title",
        plotted,
        x="team",
        y="probability",
        text="text",
        low="low",
        high="high",
        y_title="Chance of the title, with its 95% interval",
        tickformat=".0%",
        y_range=(0.0, 1.0),
    )
    return Found(
        ResultStatus.OK,
        title,
        head + "\n" + grid(header, rows, limit=len(rows)),
        _shown(header, rows),
        (
            lab_evidence(lab, "playoff_results, team_seasons, team_games"),
            postseason_evidence(lab, model),
        ),
        _postseason_warnings(lab),
        ("modeled", "measured"),
        charts=(chart,),
    )


def _season_odds(lab: Lab, model: PostseasonModel, season: str | None) -> Found:
    title = f"Every team of {season} under the season model"
    held = lab.status().team_seasons
    if season is None or season not in held:
        return missing(
            title, f"The lab holds team statistics for {seasons_held(held)}; nothing for {season}."
        )
    odds = lab.postseason.season_odds(season)
    playoffs, key = probability_key(PLAYOFFS), probability_key(TITLE)
    rows = [
        [
            row["team_name"],
            _signed(row["net_rating"]),
            _signed(row["top_players"], 2),
            _chance(PLAYOFFS, row[playoffs]),
            _chance_with_interval(TITLE, row[key], row[f"{key}_low"], row[f"{key}_high"]),
            _text(row["result"]),
        ]
        for _, row in odds.iterrows()
    ]
    head = (
        f"Every team of {season}, judged by its net rating and top-player quality as if "
        "entering a typical season: the best title chance first, next to what actually "
        "happened."
    )
    header = ["Team", "Net rating", "Top-3 quality", "Playoffs", "Title", "Result"]
    known = odds.dropna(subset=[key])
    plotted = pd.DataFrame(
        {
            "team": known["team_name"].to_numpy(),
            "probability": known[key].to_numpy(),
            "low": known[f"{key}_low"].to_numpy(),
            "high": known[f"{key}_high"].to_numpy(),
            "text": [
                _chance_with_interval(TITLE, probability, low, high)
                for probability, low, high in zip(
                    known[key], known[f"{key}_low"], known[f"{key}_high"], strict=True
                )
            ],
        }
    )
    chart = Chart(
        "intervals",
        f"Every team of {season}: the chance of the title for a team of its strength",
        plotted,
        x="team",
        y="probability",
        text="text",
        low="low",
        high="high",
        y_title="Chance of the title, with its 95% interval",
        tickformat=".0%",
        y_range=(0.0, 1.0),
    )
    return Found(
        ResultStatus.OK,
        title,
        head + "\n" + grid(header, rows),
        _shown(header, rows),
        (lab_evidence(lab, "team_seasons, player_value_scores"), postseason_evidence(lab, model)),
        (FIELD_NOT_MODELLED, *_postseason_warnings(lab)),
        ("modeled", "measured"),
        charts=(chart,) if not plotted.empty else (),
    )


def _record_found(lab: Lab, model: PostseasonModel) -> Found:
    evaluation = model.evaluation
    series, bracket = evaluation.series, evaluation.bracket
    baselines = "; ".join(f"{item.label.lower()} {item.log_loss:.3f}" for item in series.baselines)
    lines = [
        f"The postseason model, revision {model.revision}, fitted {model.fitted_at:%Y-%m-%d} on "
        f"{model.fitted_on.first_season} to {model.fitted_on.last_season}, tested on seasons it "
        "had not seen, each predicted from earlier seasons only.",
        f"Series: {series.series} from {series.first_test_season} to {series.last_test_season}; "
        f"the team it favoured won {series.favourite_won}. Its score (log loss, lower is "
        f"better) was {series.log_loss:.3f}, against {baselines}.",
        f"Titles: before each of {len(bracket.favourites)} playoffs, the team it favoured won "
        f"the title {bracket.favourite_won} times.",
        _record(model),
    ]
    tried = evaluation.season.comparisons
    if tried:
        rows = [
            [
                item.label,
                f"{item.difference:+.4f}",
                f"{item.low:+.4f} to {item.high:+.4f}",
                "clearly better"
                if item.is_clearly_better
                else "clearly worse"
                if item.is_clearly_worse
                else "no clear difference",
            ]
            for item in tried
        ]
        lines.append(
            "Other versions that were tried (the change in score; below zero is better):\n"
            + grid(["Version", "Change", "95% interval", "Reading"], rows, limit=len(rows))
        )
    better = [item.label.lower() for item in tried if item.is_clearly_better]
    if better:
        lines.append(
            f"Left out on purpose, although they scored better on past seasons: "
            f"{'; '.join(better)}. The model is meant for a roster before its season starts, "
            "when there is no record yet - a forecast record would just be the forecast net "
            "rating again - and the other teams are not known for a roster still being built "
            "(decision 0014)."
        )
    table = pd.DataFrame(
        [
            {
                "stage": stage(item.key).label,
                "cases": item.cases,
                "reached": item.reached,
                "mean_probability": item.mean_probability,
                "log_loss": item.log_loss,
                "brier": item.brier,
            }
            for item in evaluation.season.stages
        ]
    )
    return Found(
        ResultStatus.OK,
        "The postseason model's record",
        "\n".join(lines),
        table,
        (postseason_evidence(lab, model),),
        _postseason_warnings(lab),
        ("modeled",),
    )


# --- simulate_scenario -------------------------------------------------------------------


def simulate_scenario(lab: Lab, args: t.SimulateScenario) -> Found:
    service = lab.simulator
    status = service.status()
    title = "Scenario"
    if not status.is_available:
        return Found(ResultStatus.UNAVAILABLE, title, f"The simulator cannot run: {status.reason}")
    named = [item.player_id for item in args.player_assumptions]
    if len(set(named)) != len(named):
        return Found(ResultStatus.ERROR, title, "Give each player's assumptions in one entry.")
    adjustments = {
        int(item.player_id): Adjustment(
            games_missed=item.games_missed,
            development=item.development,
            share=item.minutes_share,
            salary=None
            if item.salary_millions is None
            else int(round(item.salary_millions * MILLION)),
        )
        for item in args.player_assumptions
    }
    subject = SubjectKind(args.subject)
    try:
        scenario = Scenario(
            subject=subject,
            key=int(args.subject_id),
            added=tuple(int(player) for player in args.add_player_ids),
            removed=tuple(int(player) for player in args.remove_player_ids),
            adjustments=adjustments,
            availability=Availability(args.availability),
            development=Development(args.development),
            simulations=service.default_scenario(subject, args.subject_id).simulations,
        )
    except ValueError as error:
        return Found(ResultStatus.ERROR, title, f"The scenario does not hold together: {error}")
    with lab.remembering():
        refused = _not_on_roster(lab, scenario, str(status.upcoming))
        return refused if refused is not None else _scenario(lab, service.run(scenario))


def _not_on_roster(lab: Lab, scenario: Scenario, season: str) -> Found | None:
    """A scenario for the season ahead takes each player's current team - the user's
    decision of 2026-10-10 - so one that removes, or assumes something of, a player who is
    not on the subject's roster is not run, and the result says where the player is."""
    service = lab.simulator
    on = set(service.roster_players(scenario).index)
    strangers = [
        player for player in (*scenario.removed, *scenario.adjustments) if player not in on
    ]
    if not strangers:
        return None
    if scenario.subject is SubjectKind.TEAM:
        subject = str(lab.team_labels()["full_name"].get(scenario.key, f"Team {scenario.key}"))
    else:
        subject = str(lab.rosters.get(scenario.key)["name"])
    pool = service.pool()
    said = []
    for player in dict.fromkeys(strangers):
        team_id = pool["team_id"].get(player)
        where = (
            f" They are with the {pool.at[player, 'team_name']} (team_id {int(team_id)})."
            if not _absent(team_id)
            else ""
        )
        said.append(f"{_name(lab, player)} is not on the {subject} roster for {season}.{where}")
    text = (
        "Nothing was simulated. "
        + " ".join(said)
        + " A scenario for the season ahead uses each player's current team. For a past "
        "season, the lab's statistics for that season answer instead."
    )
    return missing(
        f"Scenario: {subject}, {season}",
        text,
        (lab_evidence(lab, "team_rosters, players"),),
    )


def _scenario(lab: Lab, report: ScenarioReport) -> Found:
    model = lab.simulator.model()
    assert model is not None
    level = f"{model.spec.wins_interval:.0%}"
    before, after = report.before, report.after
    head = (
        f"{report.name}, {report.season}: {after.seasons:,} simulated seasons, "
        + ("as the roster stands and with the changes" if report.is_changed
           else "as the roster stands")
        + f", using the value model's forecasts ({report.stats_season} statistics) and the "
        "postseason model."
    )  # fmt: skip
    changes = _changes(report)
    if changes:
        head += " The changes (your assumptions): " + "; ".join(changes) + "."
    changed = report.is_changed
    sides = (("Before", before), ("After", after)) if changed else (("As it stands", after),)
    # The change is the service's: at A4 a model worked one out itself (+0.29) and had it
    # cut; a figure the lab has is given rather than left to arithmetic.
    change = report.comparison.set_index("key")["change"]
    rows = [
        # Every range says what it is: at A4 a model gave "(-5.9 to +2.6)" without saying
        # that it was the 80% interval of the seasons drawn.
        ["Projected net rating"]
        + [
            f"{_signed(o.rating)} ({level} interval {_signed(o.rating_low)} to "
            f"{_signed(o.rating_high)})"
            for _, o in sides
        ]
        + ([_signed(change["rating"])] if changed else []),
        ["Projected wins"]
        + [
            f"{o.wins:.1f} ({level} interval {o.wins_low:.0f} to {o.wins_high:.0f})"
            for _, o in sides
        ]
        + ([_signed(change["wins"])] if changed else []),
        ["Top-player quality"]
        + [_signed(o.top_players, 2) for _, o in sides]
        + ([_signed(change["top_players"], 2)] if changed else []),
    ]
    if after.payroll is not None or before.payroll is not None:
        rows.append(
            ["Payroll"]
            + [
                _money(o.payroll) + (f", {o.unpriced} unpriced" if o.unpriced else "")
                for _, o in sides
            ]
            + ([_money_change(change["payroll"])] if changed else [])
        )
    for key in BRACKET_STAGE_KEYS:
        rows.append(
            [stage(key).label]
            + [_chance_with_interval(key, *_stage(o.stages, key)) for _, o in sides]
            + ([_points(change[probability_key(key)])] if changed else [])
        )
    header = ["Figure", *(side for side, _ in sides)] + (["Change"] if changed else [])
    lines = [
        head,
        f"Net rating and wins with the {level} interval of the simulated seasons; each chance "
        "with its 95% interval"
        + ("; changes in chances are in percentage points:" if changed else ":"),
        grid(header, rows, limit=len(rows)),
    ]
    if after.unprojected:
        lines.append(
            "These players have no forecast, so they count as replacement-level players: "
            + ", ".join(after.unprojected)
            + "."
        )
    test = model.test
    held = next(
        (item for item in test.coverage if abs(item.level - model.spec.wins_interval) < 1e-9), None
    )
    if held is not None:
        lines.append(
            # A model read "held the wins in 81%" as "81% of simulated seasons matched" (A4).
            f"How far to trust the range: in a test on {held.cases} past team-seasons the lab "
            f"had not seen ({test.first_test_season} to {test.last_test_season}), the real win "
            f"total fell inside the {level} interval {held.covered} times ({held.share:.0%}, "
            f"against the {level} it promises)."
        )
    warnings = [FIELD_NOT_MODELLED]
    if not lab.simulator.status().is_current:
        warnings.append(
            "The simulator's parameters were measured against another value model than the "
            "database holds: measure them again (fol simulate fit --write)."
        )
    evidence = [lab_evidence(lab, "player_value_scores, team_rosters"), *value_evidence(lab)]
    postseason = lab.postseason.model()
    if postseason is not None:
        evidence.append(postseason_evidence(lab, postseason))
    evidence += simulator_evidence(lab)
    if after.priced or before.priced:
        evidence.append(contract_evidence(lab))
    dots = pd.DataFrame(
        [
            {
                "stage": row.label,
                "side": side,
                "probability": row.probability,
                "text": _chance_with_interval(row.key, row.probability, row.low, row.high),
            }
            for side, outcome in sides
            for row in outcome.stages.itertuples(index=False)
        ]
    )
    chart = Chart(
        "comparison",
        f"{report.name}, {report.season}: the chance of each stage",
        dots,
        x="stage",
        y="probability",
        text="text",
        who="side",
        y_title="Chance",
        tickformat=".0%",
        y_range=(0.0, 1.0),
    )
    return Found(
        ResultStatus.OK,
        f"Scenario: {report.name}, {report.season}",
        "\n".join(lines),
        _shown(header, rows),
        tuple(evidence),
        tuple(warnings),
        ("modeled", "assumption") if changed else ("modeled",),
        charts=(chart,),
    )


def _stage(stages: pd.DataFrame, key: str) -> tuple[float, float, float]:
    row = stages.set_index("key").loc[key]
    return float(row["probability"]), float(row["low"]), float(row["high"])


def _changes(report: ScenarioReport) -> list[str]:
    scenario, names = report.scenario, report.players["player_name"]

    def named(player: int) -> str:
        return str(names.get(player, f"Player {player}"))

    found = [f"{named(player)} added" for player in scenario.added]
    found += [f"{named(player)} removed" for player in scenario.removed if player in names.index]
    for player, item in scenario.adjustments.items():
        said = []
        if item.games_missed is not None:
            said.append(f"misses {item.games_missed:g} games")
        if item.development is not None:
            said.append(f"plays {item.development:+g} points of impact from the forecast")
        if item.share is not None:
            said.append(f"plays {item.share:.0%} of the team's minutes")
        if item.salary is not None:
            said.append(f"is paid {_money(item.salary)}")
        if said and player in names.index:
            found.append(f"{named(player)} " + " and ".join(said))
    if scenario.availability is not Availability.AS_PROJECTED:
        found.append(f"availability: {scenario.availability.title.lower()}")
    if scenario.development is not Development.EXPECTED:
        found.append(f"development: {scenario.development.title.lower()}")
    return found


MODEL_HANDLERS: dict[str, Handler] = {
    "player_value": player_value,
    "roster_fit": roster_fit,
    "postseason_outlook": postseason_outlook,
    "simulate_scenario": simulate_scenario,
}
