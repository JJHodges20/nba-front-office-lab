"""The global filters: season, phase, team, player and comparison window.

They sit in the sidebar on every page and live in the session, so a choice made on one
page still holds on the next.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from front_office.domain.seasons import SeasonType
from front_office.services import LabStatus, Window
from wb import data

SEASON = "filter_season"
PHASE = "filter_phase"
TEAM = "filter_team"
PLAYER = "filter_player"
SPAN = "filter_span"
DATES = "filter_dates"
PENDING = "pending_selection"
CLICKS = "table_clicks"
CURRENT = "filters"

PHASES = {SeasonType.REGULAR.value: "Regular season", SeasonType.PLAYOFFS.value: "Playoffs"}
FULL_SEASON = "Full season"
DATE_RANGE = "Date range"
SPANS: dict[str, int | None] = {
    FULL_SEASON: None,
    "Last 5 games": 5,
    "Last 10 games": 10,
    "Last 20 games": 20,
    DATE_RANGE: None,
}


@dataclass(frozen=True, slots=True)
class Filters:
    """What the reader is looking at, as chosen in the sidebar."""

    build: int | None
    """Id of the build on screen: what every cached result is keyed on."""
    season: str
    season_type: str
    team_id: int | None
    player_id: int | None
    window: Window
    has_players: bool
    """Whether the season has player statistics."""
    payroll_season: str | None
    """The season salaries are read from, or ``None`` when no contract data exists."""

    @property
    def scope(self) -> str:
        """The season, phase and span in words, for a page's subtitle."""
        return f"{self.season} · {PHASES[self.season_type]} · {self.window.describe()}"

    @property
    def is_regular_season(self) -> bool:
        return self.season_type == SeasonType.REGULAR.value


def current() -> Filters:
    """The filters of this run, as set by :func:`sidebar`."""
    return st.session_state[CURRENT]


def table_key(name: str) -> str:
    """The key for a table whose rows can be clicked to choose a team or a player.

    A row stays selected for as long as its table keeps its key, and a selected row
    would go on overruling whatever is chosen in the sidebar afterwards. The key changes
    with every choice, so a click acts once and the table returns with nothing selected.
    """
    return f"{name}_{st.session_state.get(CLICKS, 0)}"


def choose(*, team_id: int | None = None, player_id: int | None = None) -> None:
    """Point the global filters at a team or a player, from a click on a page.

    A widget's value cannot be changed once it has been drawn, so the choice is parked
    and the run restarted; :func:`sidebar` applies it before drawing anything.
    """
    pending = {}
    if team_id is not None:
        pending[TEAM] = int(team_id)
    if player_id is not None:
        pending[PLAYER] = int(player_id)
    st.session_state[PENDING] = pending
    st.session_state[CLICKS] = st.session_state.get(CLICKS, 0) + 1
    st.rerun()


def sidebar(status: LabStatus) -> Filters:
    """Draw the filters and return what they say."""
    build = status.build_id
    for key, value in st.session_state.pop(PENDING, {}).items():
        st.session_state[key] = value

    with st.sidebar:
        st.markdown("**Filters**")
        seasons = list(status.team_seasons)
        # A remembered choice can stop being offered: another season, a rebuilt database.
        # Each filter then returns to its default here, whatever Streamlit would do itself.
        if st.session_state.get(SEASON) not in seasons:
            st.session_state[SEASON] = seasons[0]
        season = st.selectbox("Season", seasons, key=SEASON)

        if st.session_state.get(PHASE) not in PHASES:
            st.session_state[PHASE] = SeasonType.REGULAR.value
        season_type = st.segmented_control(
            "Phase", list(PHASES), format_func=PHASES.get, key=PHASE, required=True, width="stretch"
        )

        teams = data.team_labels(build)
        team_ids = teams.sort_values("full_name").index.tolist()
        if st.session_state.get(TEAM) not in team_ids:
            st.session_state[TEAM] = None
        team_id = st.selectbox(
            "Team",
            team_ids,
            index=None,
            placeholder="All teams",
            format_func=lambda value: teams.at[value, "full_name"],
            key=TEAM,
        )

        has_players = season in status.player_seasons
        players = data.player_options(build, season) if has_players else None
        player_ids = [] if players is None else players.sort_values("player_name").index.tolist()
        if st.session_state.get(PLAYER) not in player_ids:
            st.session_state[PLAYER] = None

        def player_label(value: int) -> str:
            return f"{players.at[value, 'player_name']} · {players.at[value, 'team']}"

        player_id = st.selectbox(
            "Player",
            player_ids,
            index=None,
            placeholder="All players" if has_players else "No player data",
            format_func=player_label,
            key=PLAYER,
            disabled=not has_players,
            help=None if has_players else _no_players(status, season),
        )

        if st.session_state.get(SPAN) not in SPANS:
            st.session_state[SPAN] = FULL_SEASON
        span = st.selectbox(
            "Comparison window",
            list(SPANS),
            key=SPAN,
            help="The games every table and chart covers. Anything narrower than a full "
            "season is computed from game box scores.",
        )
        window = _window(build, season, season_type, span)

    filters = Filters(
        build=build,
        season=season,
        season_type=season_type,
        team_id=team_id,
        player_id=player_id,
        window=window,
        has_players=has_players,
        payroll_season=status.default_payroll_season if status.has_contracts else None,
    )
    st.session_state[CURRENT] = filters
    return filters


def _window(build: int | None, season: str, season_type: str, span: str) -> Window:
    if span != DATE_RANGE:
        return Window(last_games=SPANS[span])
    played = data.season_dates(build, season, season_type)
    if played is None:
        st.caption("This season has no games to choose dates from.")
        return Window()
    first, last = played
    chosen = st.date_input(
        "Dates", value=(first, last), min_value=first, max_value=last, key=f"{DATES}_{season}"
    )
    # While the second date is being picked the widget holds only the first.
    if not isinstance(chosen, tuple) or len(chosen) != 2:
        return Window(start=chosen[0] if chosen else first, end=last)
    start, end = chosen
    return Window(start=start, end=end)


def _no_players(status: LabStatus, season: str) -> str:
    if not status.player_seasons:
        return "No player statistics have been built."
    covered = f"{status.player_seasons[-1]} to {status.player_seasons[0]}"
    return f"There are no player statistics for {season}. Player detail covers {covered}."
