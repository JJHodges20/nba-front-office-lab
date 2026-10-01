"""The catalogue of raw datasets the lab ingests.

A dataset is one kind of provider response. Naming them here gives providers, the raw
store, pipelines and processing a shared vocabulary without any of them importing
another.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from front_office.domain.seasons import Season, SeasonType

NBA_STATS = "nba_stats"
"""Source name for stats.nba.com."""

CONTRACT_FILE = "contract_file"
"""Source name for contract data supplied by the user as a file."""

CONTRACT_FILE_DATASET = "contracts"


class NbaStatsDataset(StrEnum):
    TEAM_YEARS = "team_years"
    PLAYER_INDEX = "player_index"
    STANDINGS = "standings"
    TEAM_SEASON_BASE = "team_season_base"
    TEAM_SEASON_ADVANCED = "team_season_advanced"
    TEAM_SEASON_OPPONENT = "team_season_opponent"
    TEAM_GAME_LOGS = "team_game_logs"
    PLAYER_SEASON_BASE = "player_season_base"
    PLAYER_SEASON_ADVANCED = "player_season_advanced"
    PLAYER_SEASON_STARTERS = "player_season_starters"
    PLAYER_GAME_LOGS = "player_game_logs"
    TEAM_ROSTER = "team_roster"
    TEAM_ON_OFF = "team_on_off"


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """What one dataset holds and how its snapshots are partitioned."""

    dataset: NbaStatsDataset
    description: str
    by_season: bool = False
    by_season_type: bool = False
    by_team: bool = False
    player_level: bool = False
    """Whether the dataset is part of the heavier player-detail ingest."""


_SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec(NbaStatsDataset.TEAM_YEARS, "Franchise ids with their first and last seasons."),
    DatasetSpec(
        NbaStatsDataset.PLAYER_INDEX,
        "Every player in league history: position, size, draft, career span, current team.",
    ),
    DatasetSpec(
        NbaStatsDataset.STANDINGS,
        "Regular-season standings: record, conference, division, conference rank.",
        by_season=True,
    ),
    DatasetSpec(
        NbaStatsDataset.TEAM_SEASON_BASE,
        "Team box-score totals for a season.",
        by_season=True,
        by_season_type=True,
    ),
    DatasetSpec(
        NbaStatsDataset.TEAM_SEASON_ADVANCED,
        "Team possessions, pace, and offensive, defensive and net rating for a season.",
        by_season=True,
        by_season_type=True,
    ),
    DatasetSpec(
        NbaStatsDataset.TEAM_SEASON_OPPONENT,
        "Box-score totals a team allowed its opponents over a season.",
        by_season=True,
        by_season_type=True,
    ),
    DatasetSpec(
        NbaStatsDataset.TEAM_GAME_LOGS,
        "One box-score line per team per game.",
        by_season=True,
        by_season_type=True,
    ),
    DatasetSpec(
        NbaStatsDataset.PLAYER_SEASON_BASE,
        "Player box-score totals for a season.",
        by_season=True,
        by_season_type=True,
        player_level=True,
    ),
    DatasetSpec(
        NbaStatsDataset.PLAYER_SEASON_ADVANCED,
        "Player on-court ratings, usage, and assist and rebound percentages for a season.",
        by_season=True,
        by_season_type=True,
        player_level=True,
    ),
    DatasetSpec(
        NbaStatsDataset.PLAYER_SEASON_STARTERS,
        "Player totals restricted to games started; its games-played count is games started.",
        by_season=True,
        by_season_type=True,
        player_level=True,
    ),
    DatasetSpec(
        NbaStatsDataset.PLAYER_GAME_LOGS,
        "One box-score line per player per game.",
        by_season=True,
        by_season_type=True,
        player_level=True,
    ),
    DatasetSpec(
        NbaStatsDataset.TEAM_ROSTER,
        "A team's roster for a season, with birth dates and experience.",
        by_season=True,
        by_team=True,
        player_level=True,
    ),
    DatasetSpec(
        NbaStatsDataset.TEAM_ON_OFF,
        "Team ratings with each player on and off the court.",
        by_season=True,
        by_season_type=True,
        by_team=True,
        player_level=True,
    ),
)

DATASET_SPECS: dict[NbaStatsDataset, DatasetSpec] = {spec.dataset: spec for spec in _SPECS}


def partition_for(
    dataset: NbaStatsDataset,
    *,
    season: Season | None = None,
    season_type: SeasonType | None = None,
    team_id: int | None = None,
) -> dict[str, str]:
    """The partition a request belongs to, validating that exactly the right keys are given."""
    spec = DATASET_SPECS[dataset]
    given = {"season": season, "season_type": season_type, "team_id": team_id}
    wanted = {
        "season": spec.by_season,
        "season_type": spec.by_season_type,
        "team_id": spec.by_team,
    }
    for key, is_wanted in wanted.items():
        if is_wanted and given[key] is None:
            raise ValueError(f"dataset {dataset.value!r} needs {key}")
        if not is_wanted and given[key] is not None:
            raise ValueError(f"dataset {dataset.value!r} is not partitioned by {key}")

    partition: dict[str, str] = {}
    if season is not None:
        partition["season"] = season.label
    if season_type is not None:
        partition["season_type"] = season_type.value
    if team_id is not None:
        partition["team_id"] = str(team_id)
    return partition
