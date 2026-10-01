from __future__ import annotations

import pytest

from front_office.domain.seasons import Season, SeasonType
from front_office.processing.nba_stats.resultsets import (
    PayloadError,
    result_set_frame,
    row_count,
    snapshot_season,
    snapshot_season_type,
    standings_team_ids,
)
from tests.helpers import snapshot, stats_payload

PARTITION = {"season": "2025-26", "season_type": "regular"}


def test_frame_keeps_values_as_the_source_sent_them() -> None:
    snap = snapshot(
        "x", stats_payload(["GAME_ID", "PTS"], [["0022500001", 125], ["0022500002", None]])
    )
    frame = result_set_frame(snap, required=("GAME_ID", "PTS"))
    assert frame["GAME_ID"].tolist() == ["0022500001", "0022500002"]
    assert frame["PTS"].tolist()[0] == 125
    assert frame["PTS"].isna().tolist() == [False, True]
    assert frame.dtypes.map(str).tolist() == ["object", "object"]


def test_an_empty_result_set_gives_an_empty_frame_with_columns() -> None:
    frame = result_set_frame(snapshot("x", stats_payload(["A", "B"], [])))
    assert list(frame.columns) == ["A", "B"]
    assert len(frame) == 0


def test_a_named_result_set_is_selected() -> None:
    payload = {
        "resultSets": [
            {"name": "Overall", "headers": ["A"], "rowSet": [[1]]},
            {"name": "OnCourt", "headers": ["B"], "rowSet": [[2], [3]]},
        ]
    }
    frame = result_set_frame(snapshot("x", payload), name="OnCourt")
    assert frame["B"].tolist() == [2, 3]


def test_an_unknown_result_set_name_lists_what_is_available() -> None:
    with pytest.raises(PayloadError, match=r"no result set 'Nope'; available: \['ResultSet'\]"):
        result_set_frame(snapshot("x", stats_payload(["A"], [])), name="Nope")


def test_the_single_result_set_form_is_understood() -> None:
    payload = {"resultSet": {"name": "Only", "headers": ["A"], "rowSet": [[1]]}}
    assert result_set_frame(snapshot("x", payload))["A"].tolist() == [1]


def test_missing_required_columns_are_named() -> None:
    with pytest.raises(PayloadError, match=r"missing expected columns \['PTS'\]"):
        result_set_frame(snapshot("x", stats_payload(["A"], [[1]])), required=("A", "PTS"))


def test_extra_columns_are_tolerated() -> None:
    frame = result_set_frame(snapshot("x", stats_payload(["A", "NEW"], [[1, 2]])), required=("A",))
    assert "NEW" in frame.columns


def test_ragged_rows_are_rejected() -> None:
    with pytest.raises(PayloadError, match="rows have"):
        result_set_frame(snapshot("x", stats_payload(["A", "B"], [[1, 2], [3]])))


@pytest.mark.parametrize("payload", [{}, {"resultSets": "nope"}, {"resultSets": [{"name": "x"}]}])
def test_payloads_without_usable_result_sets_are_rejected(payload: dict) -> None:
    with pytest.raises(PayloadError):
        result_set_frame(snapshot("x", payload))


def test_row_count() -> None:
    assert row_count(snapshot("x", stats_payload(["A"], [[1], [2], [3]]))) == 3
    assert row_count(snapshot("x", stats_payload(["A"], []))) == 0


def test_season_and_type_come_from_the_partition() -> None:
    snap = snapshot("x", stats_payload(["A"], []), PARTITION)
    assert snapshot_season(snap) == Season(2025)
    assert snapshot_season_type(snap) is SeasonType.REGULAR


@pytest.mark.parametrize("key", ["Season", "SeasonYear"])
def test_a_mislabelled_season_is_caught(key: str) -> None:
    payload = stats_payload(["A"], [], parameters={key: "2024-25"})
    with pytest.raises(
        PayloadError, match="filed under 2025-26 but the source answered for 2024-25"
    ):
        snapshot_season(snapshot("x", payload, PARTITION))


def test_a_matching_echo_passes() -> None:
    payload = stats_payload(
        ["A"], [], parameters={"Season": "2025-26", "SeasonType": "Regular Season"}
    )
    snap = snapshot("x", payload, PARTITION)
    assert snapshot_season(snap) == Season(2025)
    assert snapshot_season_type(snap) is SeasonType.REGULAR


def test_a_mislabelled_season_type_is_caught() -> None:
    payload = stats_payload(["A"], [], parameters={"SeasonType": "Playoffs"})
    with pytest.raises(PayloadError, match="filed under regular"):
        snapshot_season_type(snapshot("x", payload, PARTITION))


def test_play_in_echo_is_recognised() -> None:
    payload = stats_payload(["A"], [], parameters={"SeasonType": "PlayIn"})
    snap = snapshot("x", payload, {"season": "2025-26", "season_type": "playin"})
    assert snapshot_season_type(snap) is SeasonType.PLAY_IN


def test_unpartitioned_snapshots_have_no_season() -> None:
    with pytest.raises(PayloadError, match="not partitioned by season"):
        snapshot_season(snapshot("x", stats_payload(["A"], [])))
    with pytest.raises(PayloadError, match="not partitioned by season type"):
        snapshot_season_type(snapshot("x", stats_payload(["A"], []), {"season": "2025-26"}))


def test_standings_team_ids_are_sorted_integers() -> None:
    snap = snapshot(
        "standings", stats_payload(["TeamID", "W"], [[1610612760, 64], [1610612738, 56]])
    )
    assert standings_team_ids(snap) == [1610612738, 1610612760]
