"""Team Explorer: one team's season - how good, why, who played, and the years before."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.domain.cap_rules import PayrollLine
from front_office.services import TeamTable
from wb import charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, ESTIMATE, MEASURED, Figure
from wb.state import Filters

IDENTITY = ("team_name", "conference")
OVERVIEW = ("wins", "losses", "win_pct", "net_rating", "off_rating", "def_rating", "pace")
HEADLINES = ("net_rating", "off_rating", "def_rating", "pace")
FACTORS = (
    "efg_pct",
    "tov_pct",
    "oreb_pct",
    "ft_rate",
    "opp_efg_pct",
    "opp_tov_pct",
    "dreb_pct",
    "opp_ft_rate",
    "ts_pct",
    "fg3_pct",
)
GAME_METRICS = (
    "off_rating",
    "def_rating",
    "net_rating",
    "pace",
    "efg_pct",
    "tov_pct",
    "oreb_pct",
    "ft_rate",
    "opp_efg_pct",
)
ROTATION = (
    "games_played",
    "minutes",
    "minutes_per_game",
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "ts_pct",
    "fg3_pct",
    "stocks_per_36",
    "plus_minus_per_game",
)
ROLLING = ("net_rating", "off_rating", "def_rating", "efg_pct", "pace")


def render() -> None:
    filters = state.current()
    table = data.team_table(filters.build, filters.season, filters.season_type, filters.window)
    kinds = [MEASURED, DERIVED, *([ESTIMATE] if table.estimated else [])]
    components.header("Team Explorer", filters.scope, kinds=kinds)
    if table.estimated:
        st.caption(
            "Over a span of games, ratings, pace and turnover rates are estimates from box "
            "scores. They are marked ≈."
        )

    if filters.team_id is None:
        _all_teams(filters, table)
    elif filters.team_id not in table.teams.index:
        name = data.team_labels(filters.build).at[filters.team_id, "full_name"]
        components.empty(
            "No games in this span",
            f"The {name} did not play in {filters.scope}. Their history is below.",
        )
        _history(filters)
    else:
        _team(filters, table)


def _all_teams(filters: Filters, table: TeamTable) -> None:
    teams, catalog = table.teams, table.metrics
    if teams.empty:
        components.empty("No games in this span", "Widen the comparison window or pick a season.")
        return
    categories = ["Overview", *catalog.categories]
    category = st.segmented_control(
        "Columns", categories, default="Overview", required=True, key="teams_columns"
    )
    keys = [key for key in OVERVIEW if key in catalog]
    if category != "Overview":
        keys = [spec.key for spec in catalog.in_category(category)]
    extra = ["postseason_result"] if category == "Overview" else []
    shown = teams[[*IDENTITY, *keys, *extra]].sort_values(
        "net_rating" if "net_rating" in keys else keys[0], ascending=False
    )
    chosen = st.dataframe(
        formats.styled(shown, catalog),
        hide_index=True,
        placeholder=EMPTY_CELL,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key(f"teams_table_{category}"),
        height=components.table_height(len(shown)),
        row_height=components.ROW,
        column_config={
            "team_name": st.column_config.Column("Team", width="medium", pinned=True),
            "conference": "Conf",
            "postseason_result": "Season ended",
            **components.metric_columns(catalog, keys, estimated=table.estimated),
        },
    )
    picked = chosen.selection.rows
    if picked:
        state.choose(team_id=shown.index[picked[0]])
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            shown.reset_index(), f"teams_{filters.season}_{category.lower()}", key="teams_csv"
        )
        st.caption("Select a row, or pick a team in the sidebar, to open that team.")


def _team(filters: Filters, table: TeamTable) -> None:
    team_id, catalog = filters.team_id, table.metrics
    row, ranks = table.teams.loc[team_id], table.ranks.loc[team_id]
    size = len(table.teams)

    st.subheader(row["team_name"])
    facts = [
        f"{row['conference']}ern Conference",
        row["division"],
        f"Finished {formats.ordinal(row['conference_rank'])} in the {row['conference']}",
        None if formats.is_missing(row["postseason_result"]) else row["postseason_result"],
    ]
    st.caption(" · ".join(fact for fact in facts if fact))

    estimate = "≈ " if table.estimated else ""
    items = [
        Figure(
            label="Record",
            value=f"{int(row['wins'])}-{int(row['losses'])}",
            context=f"{catalog['win_pct'].format_value(row['win_pct'])} of games won",
            help="Wins and losses in the games this view covers.",
        )
    ]
    for key in HEADLINES:
        spec = catalog[key]
        estimated = key in table.estimated
        items.append(
            Figure(
                label=f"{estimate if estimated else ''}{spec.name}",
                value=spec.format_value(row[key]),
                context=formats.rank_of(ranks[key], size),
                help=f"{spec.description} "
                + ("Estimated here." if estimated else components.origin(spec.provenance))
                + (" Rank 1 is the fastest." if key == "pace" else ""),
            )
        )
    components.figures(items)

    profile, games, rotation, history, payroll = st.tabs(
        ["Profile", "Games", "Rotation", "History", "Payroll"]
    )
    with profile:
        left, right = st.columns([3, 2], gap="large")
        with left:
            _factors(filters, table)
        with right:
            _form(filters, table)
    with games:
        _games(filters, table)
    with rotation:
        _rotation(filters)
    with history:
        _history(filters)
    with payroll:
        _payroll(filters)


def _factors(filters: Filters, table: TeamTable) -> None:
    catalog, palette = table.metrics, components.colors()
    row = table.teams.loc[filters.team_id]
    ranks, percentiles = table.ranks.loc[filters.team_id], table.percentiles.loc[filters.team_id]
    st.markdown("**How they win or lose: the four factors**")
    keys = [key for key in FACTORS if key in catalog]
    frame = pd.DataFrame(
        {
            "metric": [
                f"≈ {catalog[key].label}" if key in table.estimated else catalog[key].label
                for key in keys
            ],
            "name": [catalog[key].name for key in keys],
            "category": [catalog[key].category for key in keys],
            "percentile": [float(percentiles[key]) for key in keys],
            "value": [catalog[key].format_value(row[key]) for key in keys],
            "rank": [formats.rank_of(ranks[key], len(table.teams)) for key in keys],
            "league": [catalog[key].format_value(table.league[key]) for key in keys],
        }
    )
    frame["league_text"] = "League average " + frame["league"]
    figure = charts.percentile_bars(
        frame,
        percentile="percentile",
        label="metric",
        text="value",
        hover=["name", "rank", "league_text"],
        group="category",
        palette=palette,
    )
    components.chart(
        figure,
        frame[["category", "name", "value", "league", "rank"]].rename(
            columns={"league": "league average"}
        ),
        key="team_factors",
        filename=f"four_factors_{filters.team_id}_{filters.season}",
    )
    st.caption(
        "Bars show the team's standing among the league's teams; a longer bar is always "
        "better, so for turnovers and for everything an opponent does it means less."
    )


def _form(filters: Filters, table: TeamTable) -> None:
    catalog, palette = table.metrics, components.colors()
    st.markdown("**Form over the season**")
    pick, span = st.columns(2, vertical_alignment="bottom")
    key = pick.selectbox(
        "Metric",
        [key for key in ROLLING if key in catalog],
        format_func=lambda option: catalog[option].name,
        key="team_form_metric",
    )
    games = span.segmented_control(
        "Trailing games", [5, 10, 20], default=10, required=True, key="team_form_games"
    )
    rolling = data.team_rolling(
        filters.build, filters.team_id, filters.season, filters.season_type, games
    )
    if rolling.empty:
        components.empty("Not enough games", components.TOO_FEW_GAMES.format(games=games))
        return
    spec = catalog[key]
    row = table.teams.loc[filters.team_id]
    plotted = rolling.assign(
        text=rolling["game_date"].dt.strftime("%b %d")
        + ": "
        + rolling[key].map(spec.format_value)
        + " over "
        + rolling["games_played"].astype(str)
        + " games"
    )
    figure = charts.line(
        plotted,
        x="game_date",
        y=key,
        text="text",
        palette=palette,
        tickformat=formats.tickformat(spec),
        reference=float(row[key]),
        reference_label=("Season" if filters.window.is_full_season else "This span")
        + f"<br>{spec.format_value(row[key])}",
        baseline_zero=key == "net_rating",
        height=300,
    )
    components.chart(
        figure,
        rolling[["game_date", "games_played", key]],
        key="team_form",
        filename=f"form_{filters.team_id}_{key}",
        catalog=catalog,
    )
    st.caption(
        f"Each point covers the {games} games ending on that date. "
        "Ratings and pace over a span are estimates from box scores."
    )


def _games(filters: Filters, table: TeamTable) -> None:
    log = data.team_game_log(filters.build, filters.team_id, filters.season, filters.season_type)
    if log.empty:
        components.empty("No games", "No games in this season and phase.")
        return
    catalog = table.metrics
    keys = [key for key in GAME_METRICS if key in catalog]
    shown = log[["game_date", "opponent", "venue", "result", *keys]]
    st.caption(
        "Every finished game, newest first. A single game's ratings and pace are estimates "
        "from its box score, and noisy."
    )
    st.dataframe(
        formats.styled(shown, catalog, {"game_date": formats.day}),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(shown), 15)),
        row_height=components.ROW,
        column_config={
            "game_date": "Date",
            "opponent": "Opp",
            "venue": "Venue",
            "result": "Result",
            **components.metric_columns(
                catalog, keys, estimated=("off_rating", "def_rating", "net_rating", "pace")
            ),
        },
    )
    components.export(log, f"games_{filters.team_id}_{filters.season}", key="team_games_csv")


def _rotation(filters: Filters) -> None:
    rotation = data.team_rotation(
        filters.build, filters.team_id, filters.season, filters.season_type, filters.payroll_season
    )
    if rotation.empty:
        components.empty(
            f"No player statistics for {filters.season}",
            "Player detail is kept for recent seasons only.",
            icon=":material/person_off:",
        )
        return
    catalog = data.lab().players.metrics
    st.caption(
        "What each player did in this team's games, most minutes first. A player traded "
        "in mid-season shows only the games played here."
    )
    money = ["salary", "salary_cap_pct"] if filters.payroll_season else []
    shown = rotation[["player_name", "position", "age", *ROTATION, *money]]
    chosen = st.dataframe(
        formats.styled(shown, catalog, {"salary": formats.money, "salary_cap_pct": formats.share}),
        hide_index=True,
        placeholder=EMPTY_CELL,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key("team_rotation"),
        height=components.table_height(len(shown)),
        row_height=components.ROW,
        column_config={
            "player_name": st.column_config.Column("Player", width="medium", pinned=True),
            "position": "Pos",
            "age": "Age",
            "salary": st.column_config.Column(
                "Salary", help=f"Salary in {filters.payroll_season}, from your contract file."
            ),
            "salary_cap_pct": "Cap %",
            **components.metric_columns(catalog, ROTATION),
        },
    )
    picked = chosen.selection.rows
    if picked:
        state.choose(player_id=shown.index[picked[0]])
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            shown.reset_index(), f"rotation_{filters.team_id}_{filters.season}", key="rotation_csv"
        )
        st.caption("Select a row to make that player the subject of the Player Explorer.")


def _history(filters: Filters) -> None:
    profile = data.team_profile(filters.build, filters.team_id)
    seasons, catalog, palette = profile.seasons, profile.metrics, components.colors()
    if seasons.empty:
        components.empty("No seasons on record", "This franchise has no seasons in the data.")
        return
    st.markdown("**Every season on record**")
    st.caption("Regular-season net rating, published by the league. A star marks a championship.")
    ordered = seasons.sort_values("season")
    plotted = ordered.assign(
        text=ordered["team_name"] + ": " + formats.shown(catalog, ordered, "net_rating"),
        record=ordered["wins"].astype(str) + "-" + ordered["losses"].astype(str),
        ended=ordered["postseason_result"].fillna("Season in progress"),
        champion=ordered["won_championship"].fillna(False).astype(bool),
    )
    figure = charts.diverging_columns(
        plotted,
        x="season",
        value="net_rating",
        text="text",
        hover=["record", "ended"],
        marked="champion",
        marked_label="Champion",
        palette=palette,
        value_title="Net rating",
        tickformat="+.0f",
    )
    listed = pd.DataFrame(
        {
            "Season": seasons["season"],
            "Team": seasons["team_name"],
            "Record": seasons["wins"].astype(str) + "-" + seasons["losses"].astype(str),
            "Net rating": seasons["net_rating"],
            "Net rank": seasons["net_rating_rank"],
            "Offense rank": seasons["off_rating_rank"],
            "Defense rank": seasons["def_rating_rank"],
            "Teams": seasons["league_teams"],
            "Season ended": seasons["postseason_result"],
        }
    )
    components.chart(
        figure,
        listed,
        key="team_history",
        filename=f"history_{filters.team_id}",
    )


def from_season(
    owed: pd.DataFrame, seasons: list[str], season: str
) -> tuple[pd.DataFrame, list[str]]:
    """The commitments table from ``season`` on, and the season columns it keeps.

    A contract file that is history carries every season a team paid; the seasons before
    the one on screen are dropped, and with them the contracts that ended before it.
    """
    shown = [column for column in seasons if column >= season]
    kept = owed.drop(columns=[column for column in seasons if column < season])
    if shown:
        kept = kept[kept[shown].notna().any(axis=1)]
    return kept, shown


def _payroll(filters: Filters) -> None:
    if filters.payroll_season is None:
        components.empty(
            "No contract data",
            "Payroll needs salaries, which come from a contract file you import. See the "
            "Contract Explorer for how.",
            icon=":material/request_quote:",
        )
        return
    outlook = data.outlook(filters.build, filters.team_id)
    owed = data.commitments(filters.build, filters.team_id)
    if outlook.empty:
        components.empty(
            "No contracts for this team",
            "Your contract file lists no salaries owed by this team.",
            icon=":material/request_quote:",
        )
        return
    season = filters.payroll_season if filters.payroll_season in outlook.index else outlook.index[0]
    current = outlook.loc[season]
    st.markdown(f"**Payroll in {season}**")
    st.caption(
        "From your contract file. Team salary counts standard contracts and dead money; "
        f"two-way contracts sit outside it. {formats.LINES_EXPLAINED}"
    )
    thresholds = {
        formats.LINE_LABELS[line]: float(current[line.value])
        for line in PayrollLine
        if not formats.is_missing(current[line.value])
    }
    figure = charts.meter(
        value=float(current["team_salary"]),
        value_text=f"Team salary {formats.money(current['team_salary'])}",
        thresholds=thresholds,
        palette=components.colors(),
        tickformat="$~s",
    )
    summary = outlook.reset_index()[
        ["season", "team_salary", "active_salary", "dead_money", "standard_contracts", "cap_share"]
    ]
    components.chart(figure, summary, key="team_payroll", filename=f"payroll_{filters.team_id}")

    st.markdown("**What the team owes, contract by contract**")
    owed, seasons = from_season(owed, [c for c in owed.columns if c in outlook.index], season)
    st.caption(
        f"Contracts running in {season} or later, season by season from {season}. A "
        "contract's total covers its whole run, earlier seasons included."
    )
    st.dataframe(
        owed.drop(columns="player_id").style.format(
            {
                **{column: formats.money for column in [*seasons, "total_salary"]},
                "contract_type": formats.CONTRACT_TYPES.get,
                "status": formats.CONTRACT_STATUSES.get,
            },
            na_rep=formats.MISSING,
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={
            "player_name": st.column_config.Column("Player", width="medium", pinned=True),
            "contract_type": "Type",
            "status": "Status",
            "total_salary": "Total",
        },
    )
    components.export(owed, f"commitments_{filters.team_id}", key="team_commitments_csv")
