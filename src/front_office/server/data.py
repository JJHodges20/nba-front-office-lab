"""The lab's data through its services (C4): what is built, a season's teams and players, a
franchise, a player. Read only: nothing here writes, fits or builds, and every endpoint needs
a token.

The services compute; this formats. Every figure goes out under its metric key, and the
response's ``metrics`` say what each one is - measured, derived or modeled, and whether it is
an estimate - so a client can keep them apart as the workbench does. Missing is null, never
0. No salary or contract figure is served: the contract file is the user's own, from a
source with its own terms.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from front_office.config.season_rules import load_all_season_rules
from front_office.domain.metrics import MetricCatalog
from front_office.domain.seasons import Season
from front_office.server.auth import REFUSED, SignedIn, State
from front_office.server.schemas import (
    BuildOut,
    LabOut,
    MetricOut,
    PlayerOut,
    PlayerRow,
    PlayerSeasonRow,
    PlayersOut,
    Problem,
    QualificationOut,
    TeamOut,
    TeamRow,
    TeamSeasonRow,
    TeamsOut,
    ValueModelOut,
    ValueRow,
)
from front_office.services import Lab, LabStatus

router = APIRouter(tags=["The lab's data"])

NOT_BUILT = "No data has been built yet. Run: fol refresh"
SEASON = r"^\d{4}-\d{2}$"
VALUE_NOTE = (
    "Modeled: the value model's estimates, not measurements. The model is tested on whole "
    "teams - how well the sum of a roster's players predicts its net rating - so its errors "
    "are a team's; a single player's figure has no tested interval of its own."
)
NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "Not in the lab"}}
UNBUILT = {status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Problem, "description": NOT_BUILT}}
RESPONSES: dict[int | str, dict[str, Any]] = {**REFUSED, **NOT_FOUND, **UNBUILT}

SeasonLabel = Annotated[
    str, Path(pattern=SEASON, examples=["2025-26"], description="A season, both years: 2025-26.")
]


def opened_lab(state: State) -> Iterator[Lab]:
    """The lab, opened for one request and closed after it. A lab never built is not made
    by asking: opening it would create an empty database."""
    if not state.settings.database_path.is_file():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_BUILT)
    with Lab(state.settings) as lab:
        yield lab


OpenLab = Annotated[Lab, Depends(opened_lab)]


# --- formatting ------------------------------------------------------------------------------


def _number(value: object) -> float | None:
    """A figure as JSON has it: missing - None, NaN, pandas' NA - is null."""
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _whole(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _flag(value: object) -> bool | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return bool(value)


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value)
    return text if text and text not in ("nan", "NaT", "<NA>") else None


def _figures(row: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, float | None]:
    return {key: _number(row.get(key)) for key in keys}


def _build(lab_status: LabStatus) -> BuildOut:
    return BuildOut(build_id=lab_status.build_id, built_at=lab_status.built_at)


def _metrics(catalog: MetricCatalog, estimated: tuple[str, ...] = ()) -> list[MetricOut]:
    return [MetricOut.of(spec, estimated=spec.key in estimated) for spec in catalog]


def _require(season: str, held: tuple[str, ...], what: str) -> None:
    try:
        Season.parse(season)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    if season not in held:
        span = f" It has {held[-1]} to {held[0]}." if held else ""
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"The lab has no {what} for {season}.{span}")


# --- endpoints -------------------------------------------------------------------------------


@router.get("/lab", responses=REFUSED)
def lab_state(user: SignedIn, state: State) -> LabOut:
    """What the lab holds: the build, and the seasons it has statistics and cap rules for."""
    if not state.settings.database_path.is_file():
        rules = load_all_season_rules(state.settings.season_rules_dir)
        return LabOut(
            built=False,
            current=False,
            build=BuildOut(build_id=None, built_at=None),
            team_seasons=[],
            player_seasons=[],
            cap_seasons=[season.label for season in sorted(rules, reverse=True)],
            contract_file_as_of=None,
        )
    with Lab(state.settings) as lab:
        held = lab.status()
    return LabOut(
        built=held.is_built,
        current=held.is_current,
        build=_build(held),
        team_seasons=list(held.team_seasons),
        player_seasons=list(held.player_seasons),
        cap_seasons=list(held.cap_seasons),
        contract_file_as_of=held.contract_as_of,
    )


@router.get("/seasons/{season}/teams", responses=RESPONSES)
def season_teams(season: SeasonLabel, user: SignedIn, lab: OpenLab) -> TeamsOut:
    """Every team of one regular season, with each figure's place among that season's teams
    and the league's average."""
    held = lab.status()
    _require(season, held.team_seasons, "team statistics")
    table = lab.teams.table(season)
    keys = table.metrics.keys
    teams = [
        TeamRow(
            team_id=int(team_id),
            team_name=str(row["team_name"]),
            abbreviation=str(row["team_abbreviation"]),
            conference=_text(row.get("conference")),
            division=_text(row.get("division")),
            conference_rank=_whole(row.get("conference_rank")),
            postseason_result=_text(row.get("postseason_result")),
            figures=_figures(row, keys),
            ranks={key: _whole(table.ranks.at[team_id, key]) for key in keys},
        )
        for team_id, row in table.teams.iterrows()
    ]
    return TeamsOut(
        season=season,
        build=_build(held),
        metrics=_metrics(table.metrics, table.estimated),
        league_average=_figures(table.league, keys),
        teams=teams,
    )


@router.get("/teams/{team_id}", responses=RESPONSES)
def team(
    team_id: Annotated[int, Path(ge=1, description="The league's id for the team.")],
    user: SignedIn,
    lab: OpenLab,
) -> TeamOut:
    """A franchise as it is now, and every season on record, newest first."""
    try:
        profile = lab.teams.profile(team_id)
    except KeyError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "The lab has no team with that id."
        ) from None
    keys = profile.metrics.keys
    ranked = [
        column.removesuffix("_rank")
        for column in profile.seasons.columns
        if column.endswith("_rank") and column != "conference_rank"
    ]
    seasons = [
        TeamSeasonRow(
            season=str(row["season"]),
            team_name=str(row["team_name"]),
            conference_rank=_whole(row.get("conference_rank")),
            postseason_result=_text(row.get("postseason_result")),
            league_teams=_whole(row.get("league_teams")),
            figures=_figures(row, keys),
            rating_ranks={key: _whole(row.get(f"{key}_rank")) for key in ranked},
        )
        for _, row in profile.seasons.iterrows()
    ]
    found = profile.team
    return TeamOut(
        team_id=int(found["team_id"]),
        full_name=str(found["full_name"]),
        abbreviation=str(found["abbreviation"]),
        city=_text(found.get("city")),
        conference=_text(found.get("conference")),
        division=_text(found.get("division")),
        build=_build(lab.status()),
        metrics=_metrics(profile.metrics),
        seasons=seasons,
    )


@router.get("/seasons/{season}/players", responses=RESPONSES)
def season_players(
    season: SeasonLabel,
    user: SignedIn,
    lab: OpenLab,
    team_id: Annotated[int | None, Query(ge=1, description="Only this team's players.")] = None,
    qualified_only: Annotated[
        bool, Query(description="Only players who played enough to be compared.")
    ] = True,
    sort: Annotated[
        str | None, Query(description="A metric key to sort by; by name when left out.")
    ] = None,
    descending: Annotated[
        bool, Query(description="Highest first when sorting by a metric.")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlayersOut:
    """Players of one regular season, with every figure the lab computes for them and what
    the value model estimates. No salary or contract figure is served."""
    held = lab.status()
    _require(season, held.player_seasons, "player statistics")
    table = lab.players.table(season)
    keys = table.metrics.keys
    if sort is not None and sort not in keys:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"sort must be a metric key of this table; {sort!r} is not one (see metrics).",
        )
    frame = table.players
    if team_id is not None:
        frame = frame[frame["team_id"] == team_id]
    if qualified_only:
        frame = frame[frame["is_qualified"]]
    if sort is not None:
        frame = frame.sort_values(sort, ascending=not descending, na_position="last")
    page = frame.iloc[offset : offset + limit]
    players = [
        PlayerRow(
            player_id=int(player_id),
            player_name=str(row["player_name"]),
            team=_text(row.get("team")),
            team_id=_whole(row.get("team_id")),
            teams_played_for=_whole(row.get("team_count")),
            position=_text(row.get("position")),
            age=_whole(row.get("age")),
            qualified=bool(row["is_qualified"]),
            figures=_figures(row, keys),
        )
        for player_id, row in page.iterrows()
    ]
    rule = table.qualification
    return PlayersOut(
        season=season,
        build=_build(held),
        qualification=QualificationOut(
            min_games=rule.min_games, min_minutes=rule.min_minutes, described=rule.describe()
        ),
        metrics=_metrics(table.metrics),
        matched=len(frame),
        players=players,
    )


@router.get("/players/{player_id}", responses=RESPONSES)
def player(
    player_id: Annotated[int, Path(ge=1, description="The league's id for the player.")],
    user: SignedIn,
    lab: OpenLab,
) -> PlayerOut:
    """A player: who they are, every season on record, and the value model's estimates with
    how the model was tested. No salary or contract figure is served."""
    try:
        profile = lab.players.profile(player_id)
    except KeyError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "The lab has no player with that id."
        ) from None
    season_keys = profile.metrics.keys
    value_catalog = lab.value.metrics
    value_keys = value_catalog.keys
    extra = MetricCatalog(tuple(spec for spec in value_catalog if spec.key not in season_keys))
    found = profile.player
    birth = found.get("birth_date")
    model = lab.value.model()
    value_model = None
    if model is not None:
        tested = model.validation
        value_model = ValueModelOut(
            revision=model.revision,
            tested_seasons=f"{tested.first_test_season} to {tested.last_test_season}",
            team_seasons=tested.team_seasons,
            rmse_minutes_played=round(tested.net.rmse, 2),
            rmse_minutes_projected=(
                round(tested.projected.rmse, 2) if tested.projected is not None else None
            ),
            note=VALUE_NOTE,
        )
    return PlayerOut(
        player_id=int(found["player_id"]),
        full_name=str(found["full_name"]),
        position=_text(found.get("position")),
        position_group=_text(found.get("position_group")),
        height_inches=_whole(found.get("height_inches")),
        weight_lbs=_whole(found.get("weight_lbs")),
        birth_date=None if _text(birth) is None else birth.date(),  # type: ignore[union-attr]
        country=_text(found.get("country")),
        college=_text(found.get("college")),
        is_active=_flag(found.get("is_active")),
        current_team=_text(found.get("current_team")),
        build=_build(lab.status()),
        metrics=[*_metrics(profile.metrics), *_metrics(extra)],
        seasons=[
            PlayerSeasonRow(
                season=str(row["season"]),
                season_type=str(row["season_type"]),
                team=_text(row.get("team")),
                age=_whole(row.get("age")),
                figures=_figures(row, season_keys),
            )
            for _, row in profile.seasons.iterrows()
        ],
        value=[
            ValueRow(
                season=str(row["season"]),
                team=_text(row.get("team")),
                age=_whole(row.get("age")),
                projection_only=_number(row.get("impact")) is None,
                figures=_figures(row, tuple(key for key in value_keys if key in row)),
            )
            for _, row in profile.value.iterrows()
        ],
        value_model=value_model,
    )
