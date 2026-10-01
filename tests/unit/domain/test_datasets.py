from __future__ import annotations

import pytest

from front_office.domain.datasets import DATASET_SPECS, NbaStatsDataset, partition_for
from front_office.domain.seasons import Season, SeasonType

D = NbaStatsDataset
SEASON = Season(2025)


def test_every_dataset_has_a_spec() -> None:
    assert set(DATASET_SPECS) == set(NbaStatsDataset)
    assert all(spec.description.strip() for spec in DATASET_SPECS.values())


def test_global_datasets_have_an_empty_partition() -> None:
    assert partition_for(D.TEAM_YEARS) == {}
    assert partition_for(D.PLAYER_INDEX) == {}


def test_partitions_list_season_then_type_then_team() -> None:
    assert partition_for(D.STANDINGS, season=SEASON) == {"season": "2025-26"}
    assert partition_for(
        D.TEAM_ON_OFF, season=SEASON, season_type=SeasonType.REGULAR, team_id=1610612738
    ) == {"season": "2025-26", "season_type": "regular", "team_id": "1610612738"}
    assert list(
        partition_for(D.TEAM_ON_OFF, team_id=1, season_type=SeasonType.PLAYOFFS, season=SEASON)
    ) == ["season", "season_type", "team_id"]


def test_a_missing_partition_value_is_an_error() -> None:
    with pytest.raises(ValueError, match="needs season_type"):
        partition_for(D.TEAM_GAME_LOGS, season=SEASON)
    with pytest.raises(ValueError, match="needs team_id"):
        partition_for(D.TEAM_ROSTER, season=SEASON)


def test_an_unexpected_partition_value_is_an_error() -> None:
    with pytest.raises(ValueError, match="not partitioned by season_type"):
        partition_for(D.STANDINGS, season=SEASON, season_type=SeasonType.REGULAR)
    with pytest.raises(ValueError, match="not partitioned by season"):
        partition_for(D.TEAM_YEARS, season=SEASON)


def test_player_level_datasets_are_marked() -> None:
    player_level = {d for d, spec in DATASET_SPECS.items() if spec.player_level}
    assert D.PLAYER_GAME_LOGS in player_level
    assert D.TEAM_ROSTER in player_level
    assert D.TEAM_GAME_LOGS not in player_level
    assert D.STANDINGS not in player_level
