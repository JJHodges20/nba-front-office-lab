"""The workbench's access to the lab: one shared ``Lab``, results cached per build.

Every cached call takes the build id first. A rebuild in another process changes the id,
so the workbench picks up new data on its next run without being restarted.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import front_office.assistant.api as api
from front_office.domain.fit_model import FitEvidence
from front_office.domain.optimizer import OptimizerRequest
from front_office.domain.postseason import PostseasonModel
from front_office.domain.scenario import Scenario
from front_office.domain.simulator import SimulatorModel
from front_office.services import (
    BracketReport,
    CurrentSource,
    Era,
    EraView,
    FitReport,
    FitStatus,
    Lab,
    LabStatus,
    ModelCard,
    OptimizerReport,
    OptimizerStatus,
    Outlook,
    PlayerProfile,
    PlayerTable,
    PostseasonStatus,
    Qualification,
    Relationship,
    RosterSummary,
    ScenarioReport,
    SimulatorStatus,
    StageSummary,
    SubjectOutlook,
    TeamProfile,
    TeamTable,
    ValueForMoney,
    ValueStatus,
    Window,
    WorkspaceService,
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
def champions(build: int | None) -> pd.DataFrame:
    return lab().league.champions()


@st.cache_data(show_spinner=False)
def playoffs(build: int | None, season: str) -> pd.DataFrame:
    return lab().league.playoffs(season)


@st.cache_data(show_spinner=False)
def season_dates(build: int | None, season: str, season_type: str) -> tuple[date, date] | None:
    """The first and last game dates of a season, or ``None`` if it has no games."""
    return lab().league.season_dates(season, season_type)


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


# --- player value ---------------------------------------------------------------------------


def value_status(build: int | None) -> ValueStatus:
    """Keyed on the model files too: fitting again changes them without a build."""
    return _value_status(build, lab().model_stamp())


@st.cache_data(show_spinner=False)
def _value_status(build: int | None, stamp: str) -> ValueStatus:
    return lab().value.status()


@st.cache_data(show_spinner=False)
def value_season(build: int | None, season: str) -> pd.DataFrame:
    return lab().value.season(season)


@st.cache_data(show_spinner=False)
def value_projections(build: int | None) -> pd.DataFrame:
    return lab().value.projections()


@st.cache_data(show_spinner=False)
def value_history(build: int | None, player_id: int) -> pd.DataFrame:
    return lab().value.player(player_id)


@st.cache_data(show_spinner=False)
def value_parts(build: int | None, player_id: int, season: str) -> pd.DataFrame:
    return lab().value.parts(player_id, season)


@st.cache_data(show_spinner=False)
def value_for_money(build: int | None, season: str) -> ValueForMoney:
    return lab().value.for_money(season)


@st.cache_data(show_spinner=False)
def value_roles(build: int | None, season: str) -> pd.DataFrame:
    """The roles each player fills in a season: ``role`` and ``roles`` by ``player_id``."""
    return lab().value.roles(season)


@st.cache_data(show_spinner=False)
def role_summary(build: int | None, season: str) -> pd.DataFrame:
    return lab().value.role_summary(season)


@st.cache_data(show_spinner=False)
def role_players(build: int | None, season: str, archetype: str) -> pd.DataFrame:
    return lab().value.role_players(season, archetype)


@st.cache_data(show_spinner=False)
def value_card(build: int | None, revision: int | None) -> ModelCard | None:
    """The fitted model on file. Keyed on its revision too: fitting again changes the
    file without a build."""
    return lab().value.card()


# --- roster fit -------------------------------------------------------------------------


def fit_status(build: int | None) -> FitStatus:
    """Keyed on the model files too: fitting again changes them without a build."""
    return _fit_status(build, lab().model_stamp())


@st.cache_data(show_spinner=False)
def _fit_status(build: int | None, stamp: str) -> FitStatus:
    return lab().fit.status()


@st.cache_data(show_spinner=False)
def fit_team(build: int | None, team_id: int, season: str) -> FitReport:
    return lab().fit.team(team_id, season)


def fit_roster(roster_id: int) -> FitReport:
    """A built roster's profile. The roster changes from the Team Builder, so never cached."""
    return lab().fit.roster(roster_id)


@st.cache_data(show_spinner=False)
def fit_evidence(build: int | None, revision: int | None) -> FitEvidence | None:
    """The evidence on file. Keyed on its revision too: gathering it again changes the
    file without a build."""
    return lab().fit.evidence()


@st.cache_data(show_spinner=False)
def fit_champions(build: int | None) -> pd.DataFrame:
    return lab().fit.champions()


# --- the roster optimizer ---------------------------------------------------------------


@st.cache_data(show_spinner=False)
def optimizer_status(build: int | None) -> OptimizerStatus:
    return lab().optimizer.status()


@st.cache_data(show_spinner=False)
def optimizer_defaults(build: int | None) -> OptimizerRequest:
    return lab().optimizer.defaults()


@st.cache_data(show_spinner=False)
def optimizer_pool(build: int | None) -> pd.DataFrame:
    return lab().optimizer.pool()


@st.cache_data(show_spinner="Searching for rosters...")
def optimizer_solve(build: int | None, request: OptimizerRequest) -> OptimizerReport:
    """A run of the optimizer, kept for as long as the request and the build stand."""
    return lab().optimizer.solve(request)


# --- the postseason model ---------------------------------------------------------------
#
# Besides the build, these are keyed on the model's revision: fitting the model again
# changes the file without a build.


def postseason_status(build: int | None) -> PostseasonStatus:
    """Keyed on the model files too: fitting again changes them without a build."""
    return _postseason_status(build, lab().model_stamp())


@st.cache_data(show_spinner=False)
def _postseason_status(build: int | None, stamp: str) -> PostseasonStatus:
    return lab().postseason.status()


@st.cache_data(show_spinner=False)
def postseason_model(build: int | None, revision: int | None) -> PostseasonModel | None:
    return lab().postseason.model()


@st.cache_data(show_spinner=False)
def postseason_bracket(build: int | None, revision: int | None, season: str) -> BracketReport:
    return lab().postseason.bracket(season)


@st.cache_data(show_spinner=False)
def postseason_series(build: int | None, revision: int | None, season: str) -> pd.DataFrame:
    return lab().postseason.series(season)


@st.cache_data(show_spinner=False)
def postseason_odds(build: int | None, revision: int | None, season: str) -> pd.DataFrame:
    return lab().postseason.season_odds(season)


@st.cache_data(show_spinner=False)
def postseason_outlook(
    build: int | None,
    revision: int | None,
    net_rating: float,
    top_players: float | None,
    error: float | None,
) -> Outlook:
    return lab().postseason.outlook(net_rating, top_players, error=error)


@st.cache_data(show_spinner=False)
def postseason_curve(
    build: int | None, revision: int | None, top_players: float | None
) -> pd.DataFrame:
    return lab().postseason.curve(top_players)


@st.cache_data(show_spinner=False)
def postseason_typical(build: int | None, revision: int | None, net_rating: float) -> float:
    return lab().postseason.typical_top(net_rating)


@st.cache_data(show_spinner=False)
def postseason_team(
    build: int | None, revision: int | None, team_id: int, season: str
) -> SubjectOutlook:
    return lab().postseason.team(team_id, season)


def postseason_roster(roster_id: int) -> SubjectOutlook:
    """A built roster read as a team of its strength. Rosters change, so never cached."""
    return lab().postseason.roster(roster_id)


# --- the scenario simulator ---------------------------------------------------------------
#
# Keyed on the simulator's revision and the postseason model's too: either file can be
# fitted again without a build. A scenario about a built roster is never cached, because
# the roster changes from the Team Builder.


def simulator_status(build: int | None) -> SimulatorStatus:
    """Keyed on the model files too: fitting again changes them without a build."""
    return _simulator_status(build, lab().model_stamp())


@st.cache_data(show_spinner=False)
def _simulator_status(build: int | None, stamp: str) -> SimulatorStatus:
    return lab().simulator.status()


@st.cache_data(show_spinner=False)
def simulator_model(build: int | None, revision: int | None) -> SimulatorModel | None:
    return lab().simulator.model()


@st.cache_data(show_spinner=False)
def simulator_teams(build: int | None, revision: int | None) -> pd.DataFrame:
    return lab().simulator.teams()


@st.cache_data(show_spinner=False)
def simulator_pool(build: int | None, revision: int | None) -> pd.DataFrame:
    return lab().simulator.pool()


@st.cache_data(show_spinner=False)
def simulator_team_players(
    build: int | None, revision: int | None, scenario: Scenario
) -> pd.DataFrame:
    return lab().simulator.roster_players(scenario)


def roster_stamp(roster_id: int) -> str:
    """When a built roster last changed: what its scenario caches are keyed on, since
    the Team Builder changes rosters without a build."""
    listed = rosters()
    mine = listed[listed["roster_id"] == int(roster_id)]
    return "" if mine.empty else str(mine["updated_at"].iloc[0])


@st.cache_data(show_spinner=False)
def simulator_roster_players(
    build: int | None, revision: int | None, stamp: str, scenario: Scenario
) -> pd.DataFrame:
    return lab().simulator.roster_players(scenario)


@st.cache_data(show_spinner="Drawing seasons...")
def simulator_team_run(
    build: int | None, revision: int | None, postseason: int | None, scenario: Scenario
) -> ScenarioReport:
    return lab().simulator.run(scenario)


@st.cache_data(show_spinner="Drawing seasons...")
def simulator_roster_run(
    build: int | None, revision: int | None, postseason: int | None, stamp: str, scenario: Scenario
) -> ScenarioReport:
    return lab().simulator.run(scenario)


@st.cache_data(show_spinner="Drawing the season ahead for every team...")
def simulator_league(
    build: int | None, revision: int | None, postseason: int | None
) -> pd.DataFrame:
    return lab().simulator.league()


def simulator_save(scenario: Scenario, name: str) -> int:
    """Save a scenario's roster in the Team Builder. Rosters are never cached."""
    return lab().simulator.save(scenario, name)


def optimizer_save(player_ids: list[int], name: str, request: OptimizerRequest) -> int:
    """Save a found roster in the Team Builder. Rosters are never cached."""
    return lab().optimizer.save(player_ids, name, request)


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


# --- benchmarks ---------------------------------------------------------------------------
#
# An era reaches these functions as plain values - a configured era's key, or "custom"
# with the first and last season of a span chosen on the page - so that a result can be
# cached on them.

CUSTOM_ERA = "custom"


def _era(key: str, first: str | None, last: str | None) -> Era:
    if key == CUSTOM_ERA:
        return Era.between(str(first), str(last))
    return lab().benchmarks.era(key)


@st.cache_data(show_spinner=False)
def benchmark_eras(build: int | None) -> tuple[Era, ...]:
    return tuple(lab().benchmarks.eras)


@st.cache_data(show_spinner=False)
def benchmark_seasons(build: int | None) -> tuple[str, ...]:
    """Seasons whose postseason is complete, oldest first."""
    return lab().benchmarks.seasons()


@st.cache_data(show_spinner=False)
def benchmark_view(build: int | None, era: str, first: str | None, last: str | None) -> EraView:
    return lab().benchmarks.view(_era(era, first, last))


@st.cache_data(show_spinner=False)
def benchmark_summary(
    build: int | None, era: str, first: str | None, last: str | None, stage: str
) -> StageSummary:
    return lab().benchmarks.summary(_era(era, first, last), stage)


@st.cache_data(show_spinner=False)
def benchmark_rates(
    build: int | None,
    era: str,
    first: str | None,
    last: str | None,
    measure: str,
    width: float | None,
    among: str | None,
) -> pd.DataFrame:
    return lab().benchmarks.rates(_era(era, first, last), measure, width=width, among=among)


@st.cache_data(show_spinner=False)
def benchmark_profiles(
    build: int | None, era: str, first: str | None, last: str | None
) -> pd.DataFrame:
    return lab().benchmarks.profiles(_era(era, first, last))


@st.cache_data(show_spinner=False)
def benchmark_rank_counts(
    build: int | None, era: str, first: str | None, last: str | None
) -> pd.DataFrame:
    return lab().benchmarks.rank_counts(_era(era, first, last))


@st.cache_data(show_spinner=False)
def benchmark_separation(
    build: int | None,
    era: str,
    first: str | None,
    last: str | None,
    stage: str,
    among: str | None,
) -> pd.DataFrame:
    return lab().benchmarks.separation(_era(era, first, last), stage, among=among)


@st.cache_data(show_spinner=False)
def benchmark_dataset(
    build: int | None, era: str, first: str | None, last: str | None
) -> pd.DataFrame:
    return lab().benchmarks.dataset(_era(era, first, last))


@st.cache_data(show_spinner=False)
def benchmark_highlights(
    build: int | None, era: str, first: str | None, last: str | None, x: str, y: str
) -> pd.DataFrame:
    return lab().benchmarks.highlights(_era(era, first, last), x, y)


# --- rosters: the user's own work, changed from the page, so never cached -----------------


def rosters() -> pd.DataFrame:
    return lab().builder.rosters()


def roster_summary(roster_id: int) -> RosterSummary:
    return lab().builder.summary(roster_id)


def research() -> WorkspaceService:
    """The user's research workspaces (A6): their own work, changed from the page, so never
    cached."""
    return lab().workspaces


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


# --- the AI research assistant ------------------------------------------------------------
#
# Ollama can be started or stopped while the workbench runs, so its status expires on its
# own. What the current-information cache holds changes with every refresh and is read
# fresh.


@st.cache_data(show_spinner=False, ttl=30)
def assistant_status(build: int | None) -> api.AssistantStatus:
    return api.status()


def current_sources() -> tuple[CurrentSource, ...]:
    return lab().current.status()
