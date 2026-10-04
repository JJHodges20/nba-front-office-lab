"""Player Explorer: every player of a season, one player's profile, and side-by-side comparison."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.services import DEFAULT_QUALIFICATION, PlayerTable, Qualification
from wb import charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, MEASURED, MODELED, Figure
from wb.state import Filters

SPAN_QUALIFICATION = Qualification(min_games=3, min_minutes=30)
"""Where the thresholds start for a span of games: a 20-game minimum cannot apply to ten."""

IDENTITY = ("player_name", "team", "position", "age")
OVERVIEW = (
    "games_played",
    "minutes_per_game",
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "ts_pct",
    "usage_pct",
    "net_rating",
    "impact",
    "wins_added",
)
VALUE = ("impact", "wins_added")
"""The value model's estimates, shown beside the statistics where a season has them."""
HEADLINES = {
    "pts_per_game": "Points per game",
    "reb_per_game": "Rebounds per game",
    "ast_per_game": "Assists per game",
    "ts_pct": "True shooting",
    "usage_pct": "Usage",
}
PROFILE = (
    "pts_per_game",
    "ts_pct",
    "fg3_pct",
    "ft_rate",
    "ast_per_game",
    "usage_pct",
    "tov_pct",
    "ast_to_tov",
    "reb_per_game",
    "oreb_pct",
    "dreb_pct",
    "stl_per_36",
    "blk_per_36",
    "def_rating",
    "net_rating",
    "on_off_net",
    "impact",
)
TRENDS = ("pts_per_game", "ts_pct", "minutes_per_game", "reb_per_game", "ast_per_game")
POSITIONS = ("All", "Guard", "Forward", "Center")
CONTRACT = ("salary", "salary_cap_pct", "years_remaining")
MOST_COMPARED = 3
TABS = ("Players", "Profile", "Compare")
TAB = "players_tab"
SUBJECT = "players_subject"


def render() -> None:
    filters = state.current()
    components.header("Player Explorer", filters.scope, kinds=_kinds(filters))
    if not filters.has_players:
        components.empty(
            f"No player statistics for {filters.season}",
            "Player detail is kept for recent seasons only. Pick a later season in the sidebar.",
            icon=":material/person_off:",
        )
        return

    _follow_the_subject(filters)
    position, qualified_only, qualification, by_position = _controls(filters)
    table = data.player_table(
        filters.build,
        filters.season,
        filters.season_type,
        filters.window,
        qualification,
        filters.payroll_season,
        by_position,
    )
    st.caption(
        f"Percentiles compare {qualification.describe()}"
        f"{' within each position group' if by_position else ''}: "
        f"{table.qualified_count} of {len(table.players)} players."
    )

    listing, profile, compare = st.tabs(list(TABS), key=TAB, on_change="rerun")
    with listing:
        _listing(filters, table, position, qualified_only)
    with profile:
        _profile(filters, table)
    with compare:
        _compare(filters, table, qualification)


def _kinds(filters: Filters) -> list[str]:
    """What kinds of number the page holds: the value model's too, for a whole season."""
    whole_season = filters.is_regular_season and filters.window.is_full_season
    valued = whole_season and filters.season in data.value_status(filters.build).seasons
    return [MEASURED, DERIVED, MODELED] if valued else [MEASURED, DERIVED]


def _follow_the_subject(filters: Filters) -> None:
    """Open the profile when a player is chosen, and the listing when the choice is cleared.

    Wherever the choice was made - a row of the listing, the sidebar, another page - a
    newly chosen player is what the reader came to see. After that the tabs are the
    reader's: switching between them changes nothing here.
    """
    unseen = TAB not in st.session_state
    if unseen or st.session_state.get(SUBJECT) != filters.player_id:
        st.session_state[TAB] = TABS[0] if filters.player_id is None else TABS[1]
    st.session_state[SUBJECT] = filters.player_id


def _controls(filters: Filters) -> tuple[str, bool, Qualification, bool]:
    """The page's own filters, in one row above everything they scope."""
    full = filters.window.is_full_season
    start = DEFAULT_QUALIFICATION if full else SPAN_QUALIFICATION
    kind = "season" if full else "span"
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        position = st.segmented_control(
            "Position", POSITIONS, default="All", required=True, key="players_position"
        )
        qualified_only = st.toggle(
            "Qualified players only",
            value=True,
            key="players_qualified_only",
            help="Hide players below the minimum games and minutes.",
        )
    with st.expander("Comparison settings", icon=":material/tune:"):
        st.caption(
            "A rate means little on a tiny sample, so players are ranked only against those "
            "who cleared a minimum of games and minutes. The thresholds are a choice, not a "
            "property of the data."
        )
        games, minutes, grouped = st.columns(3)
        min_games = games.number_input(
            "Minimum games", min_value=0, value=start.min_games, step=1, key=f"min_games_{kind}"
        )
        min_minutes = minutes.number_input(
            "Minimum minutes",
            min_value=0,
            value=int(start.min_minutes),
            step=10,
            key=f"min_minutes_{kind}",
        )
        by_position = grouped.toggle(
            "Rank within position group",
            value=False,
            key="players_by_position",
            help="Compare guards with guards, forwards with forwards, centers with centers.",
        )
    qualification = Qualification(min_games=int(min_games), min_minutes=float(min_minutes))
    return position, qualified_only, qualification, by_position


def _listing(filters: Filters, table: PlayerTable, position: str, qualified_only: bool) -> None:
    players, catalog = table.players, table.metrics
    if filters.team_id is not None:
        players = players[players["team_id"] == filters.team_id]
    if position != "All":
        players = players[players["position_group"] == position]
    if qualified_only:
        players = players[players["is_qualified"]]
    if players.empty:
        components.empty(
            "No players match", "Loosen the filters, or lower the minimum games and minutes."
        )
        return

    categories = ["Overview", *catalog.categories]
    category = st.segmented_control(
        "Columns", categories, default="Overview", required=True, key="players_columns"
    )
    if category == "Overview":
        keys = [key for key in OVERVIEW if key in catalog]
    else:
        keys = [spec.key for spec in catalog.in_category(category)]
    money = [column for column in CONTRACT if filters.payroll_season and category == "Overview"]
    role = ["role"] if category == "Overview" and players["role"].notna().any() else []
    shown = players[[*IDENTITY, *role, *keys, *money]].sort_values(
        "pts_per_game" if "pts_per_game" in keys else keys[0], ascending=False
    )

    chosen = st.dataframe(
        formats.styled(
            shown,
            catalog,
            {
                "salary": formats.money,
                "salary_cap_pct": formats.share,
                "years_remaining": formats.number,
            },
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key(f"players_table_{category}"),
        height=components.table_height(min(len(shown), 18)),
        row_height=components.ROW,
        column_config={
            "player_name": st.column_config.Column("Player", width="medium", pinned=True),
            "team": "Team",
            "position": "Pos",
            "age": "Age",
            "role": st.column_config.Column(
                "Role",
                help="The main role the player fills this season, by the rules on the Player "
                "Value page. Empty for a player who fills none. A rule, not a measurement.",
            ),
            "salary": st.column_config.Column(
                "Salary", help=f"Salary in {filters.payroll_season}, from your contract file."
            ),
            "salary_cap_pct": st.column_config.Column(
                "Cap %", help=f"Salary as a share of the {filters.payroll_season} cap."
            ),
            "years_remaining": st.column_config.Column(
                "Yrs left", help="Seasons left on the contract after that one."
            ),
            **components.metric_columns(catalog, keys),
        },
    )
    picked = chosen.selection.rows
    if picked:
        state.choose(player_id=shown.index[picked[0]])
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            shown.reset_index(), f"players_{filters.season}_{category.lower()}", key="players_csv"
        )
        st.caption(f"{len(shown)} players. Select a row to open that player's profile.")


def _profile(filters: Filters, table: PlayerTable) -> None:
    if filters.player_id is None:
        components.empty(
            "No player selected",
            "Choose a player in the sidebar, or select a row in the Players tab.",
            icon=":material/person_search:",
        )
        return
    profile = data.player_profile(filters.build, filters.player_id, filters.payroll_season)
    player, catalog, palette = profile.player, table.metrics, components.colors()

    st.subheader(player["full_name"])
    facts = [
        f"Now with the {player['current_team']}"
        if player["current_team"]
        else "Not on a roster now",
        player["position"],
        formats.height(player["height_inches"]),
        f"{int(player['weight_lbs'])} lb" if not formats.is_missing(player["weight_lbs"]) else None,
        f"Born {formats.day(player['birth_date'])}"
        if not formats.is_missing(player["birth_date"])
        else None,
        _draft(player),
    ]
    st.caption(" · ".join(fact for fact in facts if fact and fact != formats.MISSING))

    if filters.player_id not in table.players.index:
        components.empty(
            "No games in this span",
            f"{player['full_name']} did not play in {filters.scope}. Other seasons are below.",
        )
    else:
        row = table.players.loc[filters.player_id]
        ranks = table.percentiles.loc[filters.player_id]
        if not formats.is_missing(row["roles"]):
            st.caption(f"Roles filled in {filters.season}: {row['roles']}.")
        _headline(row, ranks, catalog)
        left, right = st.columns([3, 2], gap="large")
        with left:
            _percentile_profile(filters, row, ranks, catalog, palette)
        with right:
            _trend(filters, row, catalog, palette)

    seasons, games, on_off, contract = st.tabs(["Seasons", "Game log", "On and off", "Contract"])
    with seasons:
        _seasons(profile)
    with games:
        _game_log(filters)
    with on_off:
        _on_off(profile)
    with contract:
        _contract(profile)


def _draft(player: dict) -> str | None:
    if formats.is_missing(player["draft_year"]):
        return "Undrafted"
    pick = "" if formats.is_missing(player["draft_number"]) else f", pick {player['draft_number']}"
    return f"Drafted {int(player['draft_year'])}{pick}"


def _headline(row: pd.Series, ranks: pd.Series, catalog) -> None:  # type: ignore[no-untyped-def]
    items = []
    for key in HEADLINES:
        if key not in catalog:
            continue
        spec = catalog[key]
        context = formats.percentile(ranks[key])
        items.append(
            Figure(
                label=HEADLINES[key],
                value=spec.format_value(row[key]),
                context="Not ranked" if context == formats.MISSING else context,
                help=f"{spec.name}. {spec.description} {components.origin(spec.provenance)}",
            )
        )
    components.figures(items)


def _percentile_profile(filters: Filters, row, ranks, catalog, palette) -> None:  # type: ignore[no-untyped-def]
    st.markdown("**Percentile profile**")
    keys = [key for key in PROFILE if key in catalog and not formats.is_missing(ranks[key])]
    if not keys:
        components.empty(
            "Not ranked",
            "This player is below the minimum games and minutes and so has no percentiles. "
            "Lower the thresholds under Comparison settings to rank everyone.",
        )
        return
    frame = pd.DataFrame(
        {
            "metric": [catalog[key].label for key in keys],
            "name": [catalog[key].name for key in keys],
            "category": [catalog[key].category for key in keys],
            "percentile": [float(ranks[key]) for key in keys],
            "value": [catalog[key].format_value(row[key]) for key in keys],
            "rank": [formats.percentile(ranks[key]) for key in keys],
        }
    )
    figure = charts.percentile_bars(
        frame,
        percentile="percentile",
        label="metric",
        text="value",
        hover=["name", "rank"],
        group="category",
        palette=palette,
    )
    components.chart(
        figure,
        frame[["category", "name", "value", "percentile"]].round({"percentile": 0}),
        key="player_percentiles",
        filename=f"percentiles_{filters.player_id}_{filters.season}",
    )
    st.caption(
        "A longer bar is always better: for turnovers and defensive rating it means fewer "
        "and lower. Usage has no better direction; there a longer bar simply means more."
    )


def _trend(filters: Filters, row, catalog, palette) -> None:  # type: ignore[no-untyped-def]
    st.markdown("**Form over the season**")
    keys = [key for key in TRENDS if key in catalog]
    pick, span = st.columns(2, vertical_alignment="bottom")
    key = pick.selectbox(
        "Metric",
        keys,
        format_func=lambda option: catalog[option].name,
        key="player_trend_metric",
    )
    games = span.segmented_control(
        "Trailing games", [5, 10, 20], default=10, required=True, key="player_trend_games"
    )
    rolling = data.player_rolling(
        filters.build, filters.player_id, filters.season, filters.season_type, games
    )
    if rolling.empty:
        components.empty("Not enough games", components.TOO_FEW_GAMES.format(games=games))
        return
    spec = catalog[key]
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
        reference=None if formats.is_missing(row[key]) else float(row[key]),
        reference_label=f"{_span_word(filters)}<br>{spec.format_value(row[key])}",
        height=300,
    )
    components.chart(
        figure,
        rolling[["game_date", "games_played", key]],
        key="player_trend",
        filename=f"trend_{filters.player_id}_{key}",
        catalog=catalog,
    )
    st.caption(f"Each point covers the {games} games ending on that date.")


def _span_word(filters: Filters) -> str:
    """What the reference line of a trend chart stands for."""
    return "Season" if filters.window.is_full_season else "This span"


def _seasons(profile) -> None:  # type: ignore[no-untyped-def]
    seasons, catalog = profile.seasons, profile.metrics
    if seasons.empty:
        components.empty("No seasons on record", "Player detail is kept for recent seasons only.")
        return
    keys = [key for key in OVERVIEW if key in catalog]
    shown = seasons[["season", "season_type", "team", "age", *keys]]
    st.dataframe(
        formats.styled(shown, catalog, {"season_type": state.PHASES.get}),
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={
            "season": "Season",
            "season_type": "Phase",
            "team": "Team",
            "age": "Age",
            **components.metric_columns(catalog, keys),
        },
    )
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            seasons, f"seasons_{profile.player['player_id']}", key="player_seasons_csv"
        )
        if seasons[list(VALUE)].notna().any().any():
            st.caption(
                "IMP and WAR are the value model's estimates, for regular seasons. The "
                "Player Value page shows where they come from."
            )


def _game_log(filters: Filters) -> None:
    log = data.player_game_log(
        filters.build, filters.player_id, filters.season, filters.season_type
    )
    if log.empty:
        components.empty("No games", "No games in this season and phase.")
        return
    st.dataframe(
        log.drop(columns="game_id").style.format(
            {"ts_pct": formats.share, "plus_minus": "{:+d}", "game_date": formats.day},
            na_rep=formats.MISSING,
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(log), 15)),
        row_height=components.ROW,
        column_config={
            "game_date": "Date",
            "team": "Team",
            "opponent": "Opp",
            "venue": "Venue",
            "result": "Result",
            "minutes": "MIN",
            "pts": "PTS",
            "reb": "REB",
            "ast": "AST",
            "stl": "STL",
            "blk": "BLK",
            "tov": "TOV",
            "fgm": "FGM",
            "fga": "FGA",
            "fg3m": "3PM",
            "fg3a": "3PA",
            "ftm": "FTM",
            "fta": "FTA",
            "plus_minus": "+/-",
            "ts_pct": st.column_config.Column("TS%", help="True shooting in that game. Derived."),
        },
    )
    components.export(log, f"games_{filters.player_id}_{filters.season}", key="player_games_csv")


def _on_off(profile) -> None:  # type: ignore[no-untyped-def]
    stints = profile.on_off
    if stints.empty:
        components.empty("No on/off data", "On/off ratings exist for the regular season only.")
        return
    st.caption(
        "Team ratings with the player on the court and off it, measured by the league. "
        "They describe the lineups around the player as much as the player."
    )
    columns = {
        "season": "Season",
        "team": "Team",
        "on_court_minutes": "On: MIN",
        "on_court_off_rating": "On: ORtg",
        "on_court_def_rating": "On: DRtg",
        "on_court_net_rating": "On: Net",
        "off_court_minutes": "Off: MIN",
        "off_court_net_rating": "Off: Net",
        "on_off_net": "On minus off",
    }
    signed = {name: "{:+.1f}" for name in ("on_court_net_rating", "off_court_net_rating")}
    st.dataframe(
        stints[list(columns)].style.format(
            {
                "on_court_minutes": "{:,.0f}",
                "off_court_minutes": "{:,.0f}",
                "on_court_off_rating": "{:.1f}",
                "on_court_def_rating": "{:.1f}",
                "on_off_net": "{:+.1f}",
                **signed,
            },
            na_rep=formats.MISSING,
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config=columns,
    )


def _contract(profile) -> None:  # type: ignore[no-untyped-def]
    years = profile.contract_years
    if years.empty:
        components.empty(
            "No contract on file",
            "Salaries come from a contract file you import. See the Contract Explorer.",
            icon=":material/request_quote:",
        )
        return
    contract = profile.contract
    st.caption(
        f"As supplied in your contract file: {contract['source_label']}, current as of "
        f"{formats.day(contract['as_of_date'])}."
    )
    st.dataframe(
        years[["season", "team", "salary", "salary_cap_pct", "option", "guarantee"]].style.format(
            {
                "salary": formats.money,
                "salary_cap_pct": formats.share,
                "option": formats.words,
                "guarantee": formats.words,
            },
            na_rep=formats.MISSING,
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={
            "season": "Season",
            "team": "Team",
            "salary": "Salary",
            "salary_cap_pct": st.column_config.Column(
                "Cap %", help="Share of that season's cap. Missing where no cap is configured."
            ),
            "option": "Option",
            "guarantee": "Guarantee",
        },
    )


def _compare(filters: Filters, table: PlayerTable, qualification: Qualification) -> None:
    players, catalog, palette = table.players, table.metrics, components.colors()
    names = players["player_name"] + " · " + players["team"].fillna("")
    default = [filters.player_id] if filters.player_id in players.index else []
    chosen = st.multiselect(
        "Players to compare",
        players.index.tolist(),
        default=default,
        format_func=names.get,
        max_selections=MOST_COMPARED,
        key=f"compare_players_{filters.season}",
        placeholder="Choose up to three players",
    )
    if len(chosen) < 2:
        components.empty(
            "Choose two or three players",
            "Their percentiles on the same metrics are drawn side by side.",
            icon=":material/compare_arrows:",
        )
        return
    keys = tuple(key for key in PROFILE if key in catalog)
    tidy = data.player_comparison(
        filters.build,
        filters.season,
        filters.season_type,
        filters.window,
        qualification,
        tuple(int(player) for player in chosen),
        keys,
    )
    ranked = tidy.dropna(subset=["percentile"])
    if ranked.empty:
        components.empty(
            "Nobody is ranked",
            "These players are below the minimum games and minutes. Lower the thresholds "
            "under Comparison settings.",
        )
    else:
        figure = charts.comparison_dots(
            ranked, metric="label", who="player_name", percentile="percentile", text="shown",
            palette=palette,
        )  # fmt: skip
        wide = tidy.pivot(index="name", columns="player_name", values="shown")
        wide = wide.reindex([catalog[key].name for key in keys]).reset_index()
        components.chart(
            figure,
            wide.rename(columns={"name": "Metric"}),
            key="player_compare",
            filename=f"compare_{'_'.join(str(player) for player in chosen)}",
        )
    unranked = sorted(set(tidy["player_name"]) - set(ranked["player_name"]))
    if unranked and not ranked.empty:
        st.caption(f"Not ranked, below the minimum: {', '.join(unranked)}.")
