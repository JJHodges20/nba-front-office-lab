"""The workbench's access to the lab: one shared ``Lab``, results cached per build.

Every cached call takes the build id first. A rebuild in another process changes the id,
so the workbench picks up new data on its next run without being restarted.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from front_office.services import (
    Lab,
    LabStatus,
    PlayerProfile,
    PlayerTable,
    Qualification,
    Relationship,
    RosterSummary,
    TeamProfile,
    TeamTable,
    Window,
    relationship,
)


@st.cache_resource(show_spinner=False, on_release=lambda opened: opened.close())
def lab() -> Lab:
    return Lab.open()


def status() -> LabStatus:
    """What the lab holds right now. Never cached: it is what the caches are keyed on."""
    return lab().status()


def reset() -> None:
    """Forget everything cached and close the lab. For tests, which swap the data underneath."""
    st.cache_data.clear()
    st.cache_resource.clear()


# --- league -----------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def team_labels(build: int | None) -> pd.DataFrame:
    return lab().team_labels()


@st.cache_data(show_spinner=False)
def standings(build: int | None, season: str) -> pd.DataFrame:
    return lab().league.standings(season)


@st.cache_data(show_spinner=False)
def league_averages(build: int | None) -> pd.DataFrame:
    return lab().league.averages()


@st.cache_data(show_spinner=False)
def league_changes(build: int | None) -> pd.DataFrame:
    return lab().league.changes()


@st.cache_data(show_spinner=False)
def history(build: int | None) -> pd.DataFrame:
    return lab().league.history()


@st.cache_data(show_spinner=False)
def champions(build: int | None) -> pd.DataFrame:
    return lab().league.champions()


@st.cache_data(show_spinner=False)
def playoffs(build: int | None, season: str) -> pd.DataFrame:
    return lab().league.playoffs(season)


@st.cache_data(show_spinner=False)
def season_dates(build: int | None, season: str, season_type: str) -> tuple[date, date] | None:
    """The first and last game dates of a season, or ``None`` if it has no games."""
    games = lab().read("team_games", {"season": season, "season_type": season_type})
    if games.empty:
        return None
    return games["game_date"].min().date(), games["game_date"].max().date()


# --- teams ------------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def team_table(build: int | None, season: str, season_type: str, window: Window) -> TeamTable:
    return lab().teams.table(season, season_type, window=window)


@st.cache_data(show_spinner=False)
def team_profile(build: int | None, team_id: int) -> TeamProfile:
    return lab().teams.profile(team_id)


@st.cache_data(show_spinner=False)
def team_game_log(build: int | None, team_id: int, season: str, season_type: str) -> pd.DataFrame:
    return lab().teams.game_log(team_id, season, season_type)


@st.cache_data(show_spinner=False)
def team_rolling(
    build: int | None, team_id: int, season: str, season_type: str, games: int
) -> pd.DataFrame:
    """A team's form: one row per span of exactly ``games`` games, so the rows compare."""
    return lab().teams.rolling(team_id, season, season_type, games=games, full_spans=True)


@st.cache_data(show_spinner=False)
def team_rotation(
    build: int | None, team_id: int, season: str, season_type: str, payroll_season: str | None
) -> pd.DataFrame:
    return lab().teams.rotation(team_id, season, season_type, payroll_season=payroll_season)


# --- players ----------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def player_table(
    build: int | None,
    season: str,
    season_type: str,
    window: Window,
    qualification: Qualification,
    payroll_season: str | None,
    by_position: bool = False,
) -> PlayerTable:
    return lab().players.table(
        season,
        season_type,
        window=window,
        qualification=qualification,
        payroll_season=payroll_season,
        by_position=by_position,
    )


@st.cache_data(show_spinner=False)
def player_options(build: int | None, season: str) -> pd.DataFrame:
    """Who played in a season: ``player_name`` and ``team``, indexed by ``player_id``."""
    table = lab().players.table(season, qualification=Qualification())
    return table.players[["player_name", "team"]]


@st.cache_data(show_spinner=False)
def player_profile(build: int | None, player_id: int, payroll_season: str | None) -> PlayerProfile:
    return lab().players.profile(player_id, payroll_season=payroll_season)


@st.cache_data(show_spinner=False)
def player_game_log(
    build: int | None, player_id: int, season: str, season_type: str
) -> pd.DataFrame:
    return lab().players.game_log(player_id, season, season_type)


@st.cache_data(show_spinner=False)
def player_rolling(
    build: int | None, player_id: int, season: str, season_type: str, games: int
) -> pd.DataFrame:
    """A player's form: one row per span of exactly ``games`` games, so the rows compare."""
    return lab().players.rolling(player_id, season, season_type, games=games, full_spans=True)


@st.cache_data(show_spinner=False)
def player_comparison(
    build: int | None,
    season: str,
    season_type: str,
    window: Window,
    qualification: Qualification,
    player_ids: tuple[int, ...],
    keys: tuple[str, ...],
) -> pd.DataFrame:
    table = player_table(build, season, season_type, window, qualification, None)
    return lab().players.compare(table, list(player_ids), list(keys))


# --- contracts --------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def contract_table(build: int | None, season: str) -> pd.DataFrame:
    return lab().contracts.table(season)


@st.cache_data(show_spinner=False)
def contract_sources(build: int | None) -> pd.DataFrame:
    return lab().contracts.sources()


@st.cache_data(show_spinner=False)
def team_payrolls(build: int | None, season: str) -> pd.DataFrame:
    return lab().contracts.team_payrolls(season)


@st.cache_data(show_spinner=False)
def commitments(build: int | None, team_id: int) -> pd.DataFrame:
    return lab().contracts.commitments(team_id)


@st.cache_data(show_spinner=False)
def outlook(build: int | None, team_id: int) -> pd.DataFrame:
    return lab().contracts.outlook(team_id)


@st.cache_data(show_spinner=False)
def cap_rules(build: int | None) -> pd.DataFrame:
    return lab().contracts.cap_rules()


@st.cache_data(show_spinner=False)
def contract_seasons(build: int | None) -> tuple[str, ...]:
    return lab().contracts.seasons()


@st.cache_data(show_spinner=False)
def contract_summary(build: int | None, season: str):  # type: ignore[no-untyped-def]
    return lab().contracts.summary(season)


@st.cache_data(show_spinner=False)
def player_seasons_played(build: int | None) -> tuple[str, ...]:
    """Seasons with player statistics, newest first."""
    return lab().status().player_seasons


# --- rosters: the user's own work, changed from the page, so never cached -----------------


def rosters() -> pd.DataFrame:
    return lab().builder.rosters()


def roster_summary(roster_id: int) -> RosterSummary:
    return lab().builder.summary(roster_id)


# --- exploration ------------------------------------------------------------------------


def association(frame: pd.DataFrame, x: str, y: str) -> Relationship:
    """How two columns move together, as the lab computes it."""
    return relationship(frame, x, y)


# --- health -----------------------------------------------------------------------------


@st.cache_data(show_spinner=False, ttl=60)
def sources(build: int | None, now: datetime) -> tuple:
    return lab().health.sources(now=now)


# Fetches are logged without a build, so these two also expire on their own.


@st.cache_data(show_spinner=False, ttl=60)
def datasets(build: int | None) -> pd.DataFrame:
    return lab().health.datasets()


@st.cache_data(show_spinner=False, ttl=60)
def failed_fetches(build: int | None) -> pd.DataFrame:
    return lab().health.failed_fetches()


@st.cache_data(show_spinner=False)
def builds(build: int | None) -> pd.DataFrame:
    return lab().health.builds()


@st.cache_data(show_spinner=False)
def issues(build: int | None) -> pd.DataFrame:
    return lab().health.issues()


@st.cache_data(show_spinner=False)
def checks(build: int | None) -> pd.DataFrame:
    return lab().health.checks()


@st.cache_data(show_spinner=False, ttl=60)
def tables(build: int | None) -> pd.DataFrame:
    return lab().health.tables()


@st.cache_data(show_spinner=False)
def gaps(build: int | None, today: date) -> tuple:
    return lab().health.gaps(today=today)
