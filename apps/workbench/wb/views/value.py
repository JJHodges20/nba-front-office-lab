"""Player Value: what the value model makes of every player, and what the model rests on.

Everything on this page is an estimate. The model is fitted to the lab's own seasons and
tested on seasons it had not seen; the last tab shows how it did, weight by weight.
Value is estimated for whole regular seasons, so the sidebar's phase and comparison
window do not narrow this page.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.domain.metrics import MetricCatalog
from front_office.services import ModelCard, ValueStatus
from wb import ask, charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, MODELED, Figure
from wb.state import Filters

TABS = ("Season", "Projections", "Roles", "Value for money", "The model")
TAB = "value_tab"
POSITIONS = ("All", "Guard", "Forward", "Center")
ORDERS = ("wins_added", "impact", "impact_offense", "impact_defense")
SIDES = {"net": "Both ends", "offense": "Offense", "defense": "Defense"}
TOP = 15
"""Players a ranking chart draws: the table under it has everyone."""
LEVELS = "Levels"
OWN_ROW = "value_model"

FIT = "fol value fit --write"

IDENTITY = {
    "player_name": st.column_config.Column("Player", width="medium", pinned=True),
    "team": "Team",
    "position": "Pos",
    "age": "Age",
}
PLAYED = {
    "played": "what the season showed",
    "projected": "what was expected going into the season",
}


def render() -> None:
    filters = state.current()
    status = data.value_status(filters.build)
    components.header(
        "Player Value",
        "What each player adds to a team, estimated by a model that is tested on seasons "
        "it had not seen. Whole regular seasons only.",
        kinds=[MODELED, DERIVED],
    )
    ask.button(ask.from_filters("Player Value", filters))
    if not status.is_available:
        _unavailable(status)
        return
    _notices(status)
    catalog = data.lab().value.metrics

    season, ahead, roles, money, model = st.tabs(list(TABS), key=TAB, on_change="rerun")
    with season:
        _season(filters, status, catalog)
    with ahead:
        _projections(filters, status, catalog)
    with roles:
        _roles(filters, status, catalog)
    with money:
        _money(filters, status)
    with model:
        _model(filters, status)


def _unavailable(status: ValueStatus) -> None:
    if status.is_fitted:
        components.empty(
            "The value model has not been applied yet",
            "A fitted model is on file, but the database was built without it. Run: fol build",
            icon=":material/trending_up:",
        )
        return
    components.empty(
        "No value model has been fitted",
        "Player value comes from a model fitted to the seasons on record. Fit it, then "
        f"rebuild: {FIT}, then fol build.",
        icon=":material/trending_up:",
    )


def _notices(status: ValueStatus) -> None:
    """What a reader should know before trusting the page: is it current?"""
    if status.needs_build:
        components.tagged(
            components.OUT_OF_DATE,
            f"The model on file is revision {status.revision}; the values on this page "
            f"were built with {status.applied_revision}. Run: fol build",
        )
    if status.finished_since:
        seasons = status.finished_since
        span = seasons[0] if len(seasons) == 1 else f"{seasons[0]} to {seasons[-1]}"
        components.tagged(
            components.OUT_OF_DATE,
            f"The model was fitted on seasons to {status.fitted_through}. {span} finished "
            f"since and is valued with the old weights. Run: {FIT}, then fol build",
        )
    if not status.is_fitted:
        components.tagged(
            components.NOTE,
            "The model these values were built with is no longer on file, so its evidence "
            f"cannot be shown. Fit it again: {FIT}",
        )


def _narrowed(players: pd.DataFrame, filters: Filters, position: str) -> pd.DataFrame:
    if filters.team_id is not None:
        players = players[players["team_id"] == filters.team_id]
    if position != "All":
        players = players[players["position_group"] == position]
    return players


def _who(players: pd.DataFrame) -> pd.Series:
    """A player and their team on one line: the label of a ranking chart."""
    return players["player_name"] + " · " + players["team"].fillna("no team")


# --- a season ---------------------------------------------------------------------------


def _season(filters: Filters, status: ValueStatus, catalog: MetricCatalog) -> None:
    if filters.season not in status.seasons:
        components.empty(
            f"No values for {filters.season}",
            f"Value is estimated for seasons with player statistics: {status.seasons[-1]} to "
            f"{status.seasons[0]}. Pick one in the sidebar.",
            icon=":material/trending_up:",
        )
        return
    everyone = data.value_season(filters.build, filters.season)
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        position = st.segmented_control(
            "Position", POSITIONS, default="All", required=True, key="value_position"
        )
        order = st.selectbox(
            "Order by",
            ORDERS,
            format_func=lambda key: catalog[key].name,
            key="value_order",
            width=280,
        )
    players = _narrowed(everyone, filters, position).sort_values(order, ascending=False)
    if players.empty:
        components.empty("No players match", "Clear the team or position filter.")
        return

    spec = catalog[order]
    st.markdown(f"**{spec.name}, {filters.season}: the top {min(TOP, len(players))}**")
    top = players.head(TOP)
    plotted = top.assign(
        who=_who(top),
        shown=formats.shown(catalog, top, order),
        sides="Offense "
        + formats.shown(catalog, top, "impact_offense")
        + ", defense "
        + formats.shown(catalog, top, "impact_defense"),
        played=formats.shown(catalog, top, "minutes_share")
        + " of team minutes, "
        + formats.shown(catalog, top, "wins_added")
        + " wins above replacement",
    )
    figure = charts.diverging_bars(
        plotted,
        value=order,
        label="who",
        text="shown",
        palette=components.colors(),
        value_title=spec.name,
        tickformat=formats.tickformat(spec),
        hover=["sides", "played"],
        highlight=[filters.player_id],
    )
    keys = ["minutes_share", "impact", "impact_offense", "impact_defense", "wins_added"]
    components.chart(
        figure,
        plotted[["player_name", "team", *keys]],
        key="value_top",
        filename=f"value_{order}_{filters.season}",
        catalog=catalog,
    )
    st.caption(
        "Impact is points per 100 possessions against the league's average minute. Wins "
        "above replacement is impact over a replacement player, for the minutes played."
    )

    shown_keys = [*keys, "reliability"]
    shown = players[[*IDENTITY, *shown_keys]]
    chosen = st.dataframe(
        formats.styled(shown, catalog),
        hide_index=True,
        placeholder=EMPTY_CELL,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key("value_table"),
        height=components.table_height(min(len(shown), 15)),
        row_height=components.ROW,
        column_config={**IDENTITY, **components.metric_columns(catalog, shown_keys)},
    )
    picked = chosen.selection.rows
    if picked:
        state.choose(player_id=shown.index[picked[0]])
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(players.reset_index(), f"player_value_{filters.season}", key="value_csv")
        st.caption(f"{len(shown)} players. Select a row for that player's breakdown below.")

    if filters.player_id in everyone.index:
        _player(filters, everyone, catalog)
    elif filters.player_id is not None:
        components.empty(
            "No value for this player",
            f"The player chosen in the sidebar has no regular season in {filters.season}.",
        )


def _player(filters: Filters, everyone: pd.DataFrame, catalog: MetricCatalog) -> None:
    row = everyone.loc[filters.player_id]
    st.subheader(row["player_name"])
    filled = data.value_roles(filters.build, filters.season)
    if filters.player_id in filled.index:
        st.caption(f"Roles filled in {filters.season}: {filled.at[filters.player_id, 'roles']}.")
    of = f"of {len(everyone)}"
    components.figures(
        [
            Figure(
                "Impact",
                catalog["impact"].format_value(row["impact"]),
                f"{formats.ordinal(row['impact_rank'])} {of}",
                help=catalog["impact"].description,
            ),
            Figure(
                "Offense",
                catalog["impact_offense"].format_value(row["impact_offense"]),
                "points added",
                help=catalog["impact_offense"].description,
            ),
            Figure(
                "Defense",
                catalog["impact_defense"].format_value(row["impact_defense"]),
                "points saved",
                help=catalog["impact_defense"].description,
            ),
            Figure(
                "Wins above replacement",
                catalog["wins_added"].format_value(row["wins_added"]),
                f"{formats.ordinal(row['wins_rank'])} {of}",
                help=catalog["wins_added"].description,
            ),
            Figure(
                "Reliability",
                catalog["reliability"].format_value(row["reliability"]),
                f"{catalog['minutes_share'].format_value(row['minutes_share'])} of team minutes",
                help=catalog["reliability"].description,
            ),
        ],
        # Three a row: five across cut "Wins above replacement" short (UI polish P5).
        per_row=3,
    )
    left, right = st.columns(2, gap="large")
    with left:
        _parts(filters, row)
    with right:
        _history(filters, catalog)


def _parts(filters: Filters, row: pd.Series) -> None:
    st.markdown("**Where the impact comes from**")
    parts = data.value_parts(filters.build, filters.player_id, filters.season)
    plotted = parts.assign(shown=parts["value"].map("{:+.2f}".format))
    figure = charts.diverging_bars(
        plotted,
        value="value",
        label="label",
        text="shown",
        palette=components.colors(),
        value_title="Points per 100 possessions",
        tickformat="+.1f",
        hover=["description"],
    )
    components.chart(
        figure,
        parts[["label", "value", "description"]].rename(columns={"label": "part"}),
        key="value_parts",
        filename=f"impact_parts_{filters.player_id}_{filters.season}",
        formats={"value": "{:+.2f}".format},
    )
    st.caption(
        "The parts add up to the impact. 'Assumed' is what the model takes for granted "
        "about the share of the estimate the minutes do not vouch for: the less a player "
        "has played, the more of the impact it is."
    )


def _history(filters: Filters, catalog: MetricCatalog) -> None:
    st.markdown("**Season by season**")
    history = data.value_history(filters.build, filters.player_id)
    series = {"impact": "What the season showed", "projected_impact": "Expected going in"}
    plotted = history.assign(
        impact_text=history["season"] + ": " + formats.shown(catalog, history, "impact"),
        projected_text=history["season"]
        + ": "
        + formats.shown(catalog, history, "projected_impact"),
    )
    figure = charts.lines(
        plotted,
        x="season",
        series=series,
        text={"impact": "impact_text", "projected_impact": "projected_text"},
        palette=components.colors(),
        y_title="Impact",
        tickformat="+.1f",
        baseline_zero=True,
        categorical_x=True,
    )
    keys = ["impact", "impact_offense", "impact_defense", "wins_added", "projected_impact"]
    components.chart(
        figure,
        history[["season", "age", "team", *keys]],
        key="value_history",
        filename=f"value_history_{filters.player_id}",
        catalog=catalog,
    )
    st.caption(
        "The projection is what the seasons before it and age led the model to expect. "
        "Its last point looks ahead to a season not yet played."
    )


# --- the season still to come -------------------------------------------------------------


def _projections(filters: Filters, status: ValueStatus, catalog: MetricCatalog) -> None:
    everyone = data.value_projections(filters.build)
    if status.upcoming is None or everyone.empty:
        components.empty(
            "Nothing to look ahead to",
            "Projections are made for the season that follows the newest one on record.",
            icon=":material/trending_up:",
        )
        return
    position = st.segmented_control(
        "Position", POSITIONS, default="All", required=True, key="value_projection_position"
    )
    players = _narrowed(everyone, filters, position)
    st.caption(
        f"What the model expects of each player in **{status.upcoming}**, from up to three "
        "seasons before it and age. Minutes are projected separately, allow for the chance "
        "of not playing at all, and know nothing of injuries, trades or depth charts."
    )
    if players.empty:
        components.empty("No players match", "Clear the team or position filter.")
        return

    spec = catalog["projected_wins"]
    st.markdown(f"**{spec.name}, {status.upcoming}: the top {min(TOP, len(players))}**")
    top = players.head(TOP)
    plotted = top.assign(
        who=_who(top),
        shown=formats.shown(catalog, top, "projected_wins"),
        rating="Projected impact " + formats.shown(catalog, top, "projected_impact"),
        minutes=formats.shown(catalog, top, "projected_share") + " of team minutes projected",
    )
    figure = charts.diverging_bars(
        plotted,
        value="projected_wins",
        label="who",
        text="shown",
        palette=components.colors(),
        value_title=spec.name,
        tickformat=formats.tickformat(spec),
        hover=["rating", "minutes"],
    )
    keys = [
        "projected_impact",
        "projected_offense",
        "projected_defense",
        "projection_reliability",
        "projected_share",
        "projected_wins",
    ]
    components.chart(
        figure,
        plotted[["player_name", "team", *keys]],
        key="value_projected_top",
        filename=f"projected_value_{status.upcoming}",
        catalog=catalog,
    )

    shown = players[[*IDENTITY, *keys, "projection_seasons", "last_season", "last_impact"]]
    st.dataframe(
        formats.styled(shown, catalog, {"last_impact": catalog["impact"].format_value}),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(shown), 15)),
        row_height=components.ROW,
        column_config={
            **IDENTITY,
            **components.metric_columns(catalog, keys),
            "projection_seasons": st.column_config.Column(
                "Seasons", help="Earlier seasons the projection draws on, up to three."
            ),
            "last_season": st.column_config.Column(
                "Last played", help="The newest season the player has on record."
            ),
            "last_impact": st.column_config.Column(
                "IMP then", help="Impact in that season. Estimated by the value model."
            ),
        },
    )
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            players.reset_index(), f"projected_value_{status.upcoming}", key="value_projected_csv"
        )
        st.caption(f"{len(shown)} players with a season on record in the last three.")


# --- roles ----------------------------------------------------------------------------------


def _roles(filters: Filters, status: ValueStatus, catalog: MetricCatalog) -> None:
    if filters.season not in status.seasons:
        components.empty(
            f"No roles for {filters.season}",
            "Roles are given for seasons with player statistics. Pick one in the sidebar.",
            icon=":material/groups:",
        )
        return
    summary = data.role_summary(filters.build, filters.season)
    st.caption(
        "A role is a rule, not a measurement: a player's score for it is the weakest of "
        "their percentiles on the role's measures, among the players the role is open to, "
        "in that season - so it takes all of them together. A player fills a role from its "
        "cut-off up. The cut-off is a convention, and the rules are in "
        "configs/archetypes.yaml to be read and changed."
    )
    shown = summary[
        ["name", "open_to", "measures", "fills_at", "scored", "filled", "again", "anyone"]
    ]
    st.dataframe(
        shown.style.format(
            {"fills_at": "{:.0f}".format, "again": formats.share, "anyone": formats.share},
            na_rep=formats.MISSING,
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={
            "name": st.column_config.Column("Role", width="medium"),
            "open_to": st.column_config.Column(
                "Open to", help="Who can fill the role, and among whom percentiles are taken."
            ),
            "measures": st.column_config.Column(
                "Strong on, together", help="The score is the weakest of these percentiles."
            ),
            "fills_at": st.column_config.Column(
                "Fills from", help="The score from which a player fills the role: a convention."
            ),
            "scored": st.column_config.Column(
                "Scored", help=f"Players open to the role with enough minutes in {filters.season}."
            ),
            "filled": st.column_config.Column(
                "Fill it", help=f"Players at or above the cut-off in {filters.season}."
            ),
            "again": st.column_config.Column(
                "Fill it again",
                help="Of the players who filled the role in one season, the share who filled "
                "it in the next too. Every season on record.",
            ),
            "anyone": st.column_config.Column(
                "Anyone does",
                help="The share of all players scored for the role in that next season who "
                "filled it: what 'fill it again' would be if a role told nothing about a player.",
            ),
        },
    )
    st.caption(
        "A role that is a lasting trait is filled again far more often than by anyone at "
        "all. Roles are scored for players with enough minutes; everyone else has none."
    )

    names = dict(zip(summary["archetype"], summary["name"], strict=True))
    chosen = st.segmented_control(
        "Role", list(names), format_func=names.get, default=summary["archetype"].iloc[0],
        required=True, key="value_role",
    )  # fmt: skip
    role = summary.set_index("archetype").loc[chosen]
    st.markdown(f"**{role['name']}.** {role['description']}")
    upper = (
        "" if formats.is_missing(role["fills_below"]) else f" and below {role['fills_below']:.0f}"
    )
    st.caption(
        f"{role['note']} Fills the role: a score of {role['fills_at']:.0f} or more{upper}, "
        f"among {role['open_to'].lower()}."
    )
    players = data.role_players(filters.build, filters.season, chosen)
    if filters.team_id is not None:
        players = players[players["team_id"] == filters.team_id]
    if players.empty:
        components.empty(
            "Nobody fills this role",
            "No player in view reaches the cut-off. Clear the team filter, or pick another role.",
        )
        return
    keys = ["impact", "wins_added"]
    listed = players[[*IDENTITY, "score", "is_primary", "roles", *keys]]
    picked = st.dataframe(
        formats.styled(listed, catalog, {"score": "{:.0f}".format}),
        hide_index=True,
        placeholder=EMPTY_CELL,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key(f"value_role_table_{chosen}"),
        height=components.table_height(min(len(listed), 15)),
        row_height=components.ROW,
        column_config={
            **IDENTITY,
            "score": st.column_config.Column(
                "Score", help="The weakest of the player's percentiles on the role's measures."
            ),
            "is_primary": st.column_config.CheckboxColumn(
                "Main role", help="Of the roles the player fills, the one with the highest score."
            ),
            "roles": st.column_config.Column("Every role filled", width="large"),
            **components.metric_columns(catalog, keys),
        },
    ).selection.rows
    if picked:
        state.choose(player_id=listed.index[picked[0]])
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(players.reset_index(), f"{chosen}_{filters.season}", key="value_role_csv")
        count = "1 player fills" if len(listed) == 1 else f"{len(listed)} players fill"
        st.caption(
            f"{count} this role in {filters.season}. Select a row, then see the Season tab "
            "for the player's breakdown."
        )


# --- value against salary -----------------------------------------------------------------


def _money(filters: Filters, status: ValueStatus) -> None:
    seasons = data.contract_seasons(filters.build)
    if not seasons:
        components.empty(
            "No contract data",
            "Value for money sets salaries against wins, and salaries come from a contract "
            "file you import. See the Contract Explorer.",
            icon=":material/request_quote:",
        )
        return
    default = filters.payroll_season if filters.payroll_season in seasons else seasons[0]
    season = st.selectbox(
        "Salaries of", seasons, index=seasons.index(default), key="value_money_season", width=200
    )
    money = data.value_for_money(filters.build, season)
    if money.basis is None:
        components.empty(
            f"{season} has not been valued",
            "The model values seasons that have been played and looks one season ahead"
            + (f", to {status.upcoming}" if status.upcoming else "")
            + ". It does not project later seasons of a contract.",
            icon=":material/trending_up:",
        )
        return
    players = money.players
    if players.empty:
        components.empty(
            "Nobody to value",
            f"None of the players with a salary in {season} has a value in that season.",
        )
        return
    missing = f" {money.unvalued} with a salary have no value and are left out." * bool(
        money.unvalued
    )
    st.caption(
        f"Salaries in **{season}**, from your contract file, against {PLAYED[money.basis]}: "
        f"{len(players)} players.{missing}"
    )

    market = money.market
    if market is None:
        components.tagged(
            components.NOTE,
            "No price of a win can be read off these contracts: there are too few, or "
            "they do not pay more for more wins. Salary per win is shown without one.",
        )
    else:
        components.figures(
            [
                Figure(
                    "Price of a win",
                    formats.money_compact(market.price_per_win),
                    f"from {market.contracts} contracts",
                    help="What the contracts on file pay for one more win above replacement: "
                    "the slope of a straight line through salary and wins. Modeled.",
                ),
                Figure(
                    "Cost of no wins",
                    formats.money_compact(market.replacement_cost),
                    "a replacement player",
                    help="What the same line pays a player worth no wins above replacement.",
                ),
                Figure(
                    "Salary explained",
                    formats.share(market.r2, 0),
                    "by wins alone",
                    help="How much of the differences in salary the line accounts for. The "
                    "rest is everything else a contract pays for, and the line's error.",
                ),
            ]
        )

    in_view = players
    if filters.team_id is not None:
        in_view = players[players["team_id"] == filters.team_id]
    plotted = players.assign(
        who=_who(players),
        paid="Salary " + players["salary"].map(formats.money_compact),
        worth=players["wins"].map("{:.1f} wins above replacement".format),
        left="Surplus " + players["surplus"].map(formats.money_compact),
    )
    figure = charts.scatter(
        plotted,
        x="wins",
        y="salary",
        name="who",
        palette=components.colors(),
        x_title="Wins above replacement",
        y_title=f"Salary in {season}",
        y_tickformat="$~s",
        hover=["paid", "worth", "left"],
        highlight=list(in_view.index) if filters.team_id is not None else [filters.player_id],
        trend=None if market is None else (market.replacement_cost, market.price_per_win),
        reference_label="" if market is None else "The line: what these contracts pay for wins",
    )
    columns = ["salary", "wins", "market_value", "surplus", "cost_per_win"]
    # A salary is a figure from a file; what the line makes of it is an estimate, and is
    # not shown to the dollar.
    estimated = dict.fromkeys(["market_value", "surplus", "cost_per_win"], formats.money_compact)
    dollars = {"salary": formats.money, **estimated}
    components.chart(
        figure,
        players[["player_name", "team", *columns]],
        key="value_money",
        filename=f"value_for_money_{season}",
        formats={**dollars, "wins": "{:.1f}".format},
    )
    st.caption(
        "A player below the line is paid less than these contracts pay for the same wins. "
        "Rookie-scale and maximum contracts are set by rule, not by a market, and the line "
        "knows nothing of that."
    )

    shown = in_view[
        [*IDENTITY, "salary", "salary_cap_pct", "years_remaining", "rating", *columns[1:]]
    ]
    st.dataframe(
        shown.style.format(
            {
                **dollars,
                "salary_cap_pct": formats.share,
                "years_remaining": formats.number,
                "rating": "{:+.1f}".format,
                "wins": "{:.1f}".format,
            },
            na_rep=formats.MISSING,
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(shown), 15)),
        row_height=components.ROW,
        column_config={
            **IDENTITY,
            "salary": st.column_config.Column("Salary", help="From your contract file."),
            "salary_cap_pct": st.column_config.Column(
                "Cap %", help="Salary as a share of the cap."
            ),
            "years_remaining": st.column_config.Column(
                "Yrs left", help="Seasons left on the contract after this one."
            ),
            "rating": st.column_config.Column(
                "Impact", help=f"Impact, per 100 possessions: {PLAYED[money.basis]}. Modeled."
            ),
            "wins": st.column_config.Column(
                "WAR", help=f"Wins above replacement: {PLAYED[money.basis]}. Modeled."
            ),
            "market_value": st.column_config.Column(
                "Worth", help="What the line through these contracts pays for those wins. Modeled."
            ),
            "surplus": st.column_config.Column(
                "Surplus",
                help="Worth less salary: positive is a bargain against the line. Modeled.",
            ),
            "cost_per_win": st.column_config.Column(
                "$ per win", help="Salary over wins, for players worth more than none."
            ),
        },
    )
    components.export(
        players.reset_index(), f"value_for_money_{season}", key="value_money_players_csv"
    )


# --- the model -----------------------------------------------------------------------------


def _model(filters: Filters, status: ValueStatus) -> None:
    card = data.value_card(filters.build, status.revision)
    if card is None:
        components.empty(
            "No fitted model on file",
            f"The evidence for the model is kept in the model file. Fit it again: {FIT}",
            icon=":material/model_training:",
        )
        return
    model, tested, on = card.model, card.model.validation, card.model.fitted_on
    others = card.baselines[card.baselines["key"] != OWN_ROW]
    st.markdown(
        "A team's rating is modelled as the sum of its players' estimates, each counted for "
        "the minutes actually played, where every estimate is built **only from earlier "
        "seasons**. The weights are whatever makes that sum come closest to what teams then "
        "did. The model is then tested one season at a time, on weights fitted to the "
        "seasons before, and has to beat simpler ways of making the same prediction."
    )
    components.figures(
        [
            Figure(
                "Typical miss, in points",
                f"{tested.net.rmse:.2f}",
                f"{tested.team_seasons} team-seasons",
                help="Root mean squared error of a team's predicted net rating, out of "
                f"sample, {tested.first_test_season} to {tested.last_test_season}, given "
                "the minutes each season played.",
            ),
            Figure(
                "With minutes projected",
                formats.MISSING if tested.projected is None else f"{tested.projected.rmse:.2f}",
                "not in this file"
                if tested.projected is None
                else f"{tested.projected.share_covered:.0%} of minutes covered",
                help="The same test with the minutes projected from earlier seasons, as a "
                "forecast has them, and replacement level for the rest: the error the "
                "optimizer and the simulator carry.",
            ),
            Figure(
                "Best simpler method",
                formats.MISSING if others.empty else f"{others['rmse'].iloc[0]:.2f}",
                f"closest of {len(others)}",
                help="The closest of the simpler methods on the same test"
                + ("." if others.empty else f": {others['label'].iloc[0]}."),
            ),
            Figure(
                "Replacement level",
                f"{model.replacement_level:+.2f}",
                "per 100 possessions",
                help="Measured, not assumed: the minutes-weighted impact of players outside "
                f"their team's {model.spec.replacement_rank} most-used.",
            ),
            Figure(
                "Fitted on",
                f"{on.team_seasons:,}",
                f"team-seasons, to {on.last_season[:4]}",
                help=f"{on.first_season} to {on.last_season}: {on.player_seasons:,} player-seasons.",
            ),
            Figure(
                "Revision",
                str(model.revision),
                f"fitted {model.fitted_at:%b %d, %Y}",
                help="The fitted model is a file under configs/models. A build applies it "
                "and never fits one; every value names the revision that produced it.",
            ),
        ],
        per_row=3,
    )
    _against(card)
    _left_out(card)
    _weights(card)
    _backtest(filters, card)
    _limits(card)


def _interval_text(frame: pd.DataFrame, what: str) -> pd.Series:
    return (
        "<b>"
        + frame["label"]
        + "</b><br>"
        + what
        + " "
        + frame["difference"].map("{:+.2f}".format)
        + "<br>95% interval "
        + frame["low"].map("{:+.2f}".format)
        + " to "
        + frame["high"].map("{:+.2f}".format)
        + "<br>Its own error: "
        + frame["rmse"].map("{:.2f}".format)
    )


def _against(card: ModelCard) -> None:
    st.markdown("**Against simpler methods**")
    others = card.baselines[card.baselines["key"] != OWN_ROW]
    if others.empty:
        components.empty("No test on file", "This model carries no comparison with other methods.")
        return
    plotted = others.assign(text=_interval_text(others, "The model's error less this method's:"))
    figure = charts.interval_rows(
        plotted,
        label="label",
        value="difference",
        low="low",
        high="high",
        text="text",
        palette=components.colors(),
        value_title="Model's miss less the method's, in points",
        tickformat="+.1f",
        reference=0.0,
        reference_label="No difference",
    )
    components.chart(
        figure,
        card.baselines[["label", "rmse", "mae", "difference", "low", "high"]].rename(
            columns={"label": "method"}
        ),
        key="value_baselines",
        filename="value_model_against_baselines",
        formats=_two_decimals("rmse", "mae", signed=("difference", "low", "high")),
    )
    st.caption(
        "Left of the line, the model predicted better. The thin line through each dot is "
        "the 95% interval from resampling whole seasons: where it stays clear of zero the "
        "difference is not luck. Each method is given next season's actual minutes, as the "
        "model is, so what is compared is the rating and not a forecast of playing time."
    )


def _left_out(card: ModelCard) -> None:
    st.markdown("**What each part adds**")
    table = card.ablations
    if table.empty:
        components.empty("No test on file", "This model was not tested with its parts left out.")
        return
    plotted = table.assign(text=_interval_text(table, "Error without it, less the full model's:"))
    figure = charts.interval_rows(
        plotted,
        label="label",
        value="difference",
        low="low",
        high="high",
        text="text",
        palette=components.colors(),
        value_title="Error without the part, less the full model's",
        tickformat="+.2f",
        reference=0.0,
        reference_label="Not missed",
    )
    components.chart(
        figure,
        table[["label", "rmse", "difference", "low", "high", "distinguishable"]].rename(
            columns={"label": "left out"}
        ),
        key="value_ablations",
        filename="value_model_ablations",
        formats=_two_decimals("rmse", signed=("difference", "low", "high")),
    )
    unsure = table.loc[~table["distinguishable"].astype(bool), "label"].str.lower().tolist()
    st.caption(
        "The model is fitted again with one part left out and put through the same test. "
        "Right of the line, the part was missed. "
        + (
            f"On this evidence {_listed(unsure)} cannot be told from adding nothing: their "
            "intervals reach zero. They stay in because the box score as a whole is missed, "
            "but no single weight in them should be leaned on."
            if unsure
            else "Every part is missed beyond doubt."
        )
    )


def _weights(card: ModelCard) -> None:
    st.markdown("**The weights**")
    side = st.segmented_control(
        "End of the floor", list(SIDES), format_func=SIDES.get, default="net", required=True,
        key="value_side",
    )  # fmt: skip
    terms = card.terms
    features = terms[terms["group"] != LEVELS]
    plotted = features.assign(
        text="<b>"
        + features["label"]
        + "</b> ("
        + features["group"]
        + ")<br>"
        + features[side].map("{:+.3f}".format)
        + " points per unit<br>95% interval "
        + features[f"{side}_low"].map("{:+.2f}".format)
        + " to "
        + features[f"{side}_high"].map("{:+.2f}".format)
        + "<br>"
        + features["description"]
    )
    figure = charts.interval_rows(
        plotted,
        label="label",
        value=side,
        low=f"{side}_low",
        high=f"{side}_high",
        text="text",
        palette=components.colors(),
        value_title=f"Points of team rating per unit of the feature: {SIDES[side].lower()}",
        tickformat="+.1f",
        reference=0.0,
        reference_label="No weight",
    )
    columns = ["label", "group", side, f"{side}_low", f"{side}_high", "description"]
    components.chart(
        figure,
        terms[columns].rename(columns={"label": "term"}),
        key="value_weights",
        filename=f"value_model_weights_{side}",
        formats=_two_decimals(signed=(side, f"{side}_low", f"{side}_high")),
    )
    levels = terms[terms["group"] == LEVELS].set_index("key")
    st.caption(
        "A weight is what one more of something per 100 possessions has been worth to a "
        "team's rating next season - not the price of a steal or a rebound. Several are "
        "wide. Besides these, the model has four levels: a player with no earlier season "
        f"starts at {levels.at['new_player', 'net']:+.2f}; the unproven part of a known "
        f"player is assumed to be {levels.at['prior_level', 'net']:+.2f} at the league's "
        f"average minutes per game and {levels.at['prior_minutes', 'net']:+.2f} more for "
        f"each minute above it; and each year of age past {card.model.spec.age_centre:g} "
        f"moves next season's estimate by {levels.at['age', 'net']:+.2f}."
    )


def _backtest(filters: Filters, card: ModelCard) -> None:
    st.markdown("**Predicted against what happened**")
    backtest = card.backtest
    if backtest.empty:
        components.empty(
            "No test on file", "This model carries no predictions to set against results."
        )
        return
    plotted = backtest.assign(
        who=backtest["team_name"] + ", " + backtest["season"],
        expected="Predicted " + backtest["predicted"].map("{:+.1f}".format),
        happened="Actual " + backtest["actual"].map("{:+.1f}".format),
        miss="Missed by " + backtest["error"].abs().map("{:.1f}".format),
    )
    mine = plotted.index[plotted["team_id"] == filters.team_id] if filters.team_id else []
    figure = charts.scatter(
        plotted,
        x="predicted",
        y="actual",
        name="who",
        palette=components.colors(),
        x_title="Predicted net rating, from earlier seasons",
        y_title="Actual net rating",
        x_tickformat="+.0f",
        y_tickformat="+.0f",
        hover=["expected", "happened", "miss"],
        highlight=list(mine),
        trend=(0.0, 1.0),
        reference_label="On the line: predicted exactly",
    )
    components.chart(
        figure,
        backtest[["season", "team", "predicted", "actual", "error"]],
        key="value_backtest",
        filename="value_model_backtest",
        formats=_two_decimals(signed=("predicted", "actual", "error")),
    )
    tested = card.model.validation
    by_season = card.by_season
    worst = by_season.loc[by_season["rmse"].idxmax()]
    kindest = by_season.loc[by_season["rmse"].idxmin()]
    st.caption(
        f"One mark for each of {len(backtest)} team-seasons, each predicted with weights "
        "fitted only to the seasons before it and with the minutes its players went on to "
        f"play. A typical miss is {tested.net.rmse:.1f} points of net rating: about "
        f"{tested.offense.rmse:.1f} on offense and {tested.defense.rmse:.1f} on defense. "
        f"By season it runs from {kindest['rmse']:.1f} ({kindest['season']}) to "
        f"{worst['rmse']:.1f} ({worst['season']})."
        + (" Choose a team in the sidebar to pick out its seasons." if not filters.team_id else "")
    )


def _limits(card: ModelCard) -> None:
    same, minutes = card.model.validation.same_season, card.model.availability
    with st.expander("What this model cannot tell you", icon=":material/report:"):
        st.markdown(
            "- **Impact is an estimate of ability, not a split of results.** A team's "
            "impacts add up to roughly its net rating - a correlation of "
            f"{same.correlation:.2f}, with the team's rating {same.slope:.2f} times the sum - "
            "and nothing forces the two to agree.\n"
            "- **Defense is the weak side.** A box score records little of it, so the model "
            "leans on the team's own defensive results, shared among the players who were "
            "there. A good defender on a poor defensive team is underrated, and the reverse.\n"
            "- **The test takes next season's minutes as given.** It says the ratings carry "
            "over; it does not say the lab can foresee who will play.\n"
            "- **Projected minutes are plain.** Next season's share of team minutes from the "
            f"last three and age misses by {minutes.rmse:.2f} of a team's minutes on average, "
            f"against {minutes.baseline_rmse:.2f} for assuming last season's share. It knows "
            "nothing of injuries, trades or depth charts.\n"
            "- **Playoff performance is not in it.** Counting playoff minutes did not help "
            "predict the next season, so they are left out. Whether they matter in the "
            "playoffs is a different question.\n"
            "- **Wins are a conversion, not a count.** Impact above replacement, times "
            "minutes, times what a point of net rating has been worth in wins."
        )


def _two_decimals(*plain: str, signed: tuple[str, ...] = ()) -> dict:
    formats_by_column: dict = dict.fromkeys(plain, "{:.2f}".format)
    formats_by_column.update(dict.fromkeys(signed, "{:+.2f}".format))
    return formats_by_column


def _listed(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
