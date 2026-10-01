"""Read stats.nba.com payloads.

Every stats.nba.com response carries one or more *result sets*: a list of column
headers and a list of rows. These helpers turn one into a frame and check, loudly, that
the response is the one the caller expected.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from front_office.domain.seasons import Season, SeasonType
from front_office.domain.snapshots import Snapshot

_SEASON_TYPE_NAMES = {
    "Regular Season": SeasonType.REGULAR,
    "Playoffs": SeasonType.PLAYOFFS,
    "PlayIn": SeasonType.PLAY_IN,
}


class PayloadError(ValueError):
    """A raw payload does not have the shape processing relies on."""


def result_sets(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    found = payload.get("resultSets", payload.get("resultSet"))
    if isinstance(found, Mapping):
        return [found]
    if isinstance(found, list):
        return found
    raise PayloadError("payload has no result sets")


def result_set_frame(
    snapshot: Snapshot, *, name: str | None = None, required: Sequence[str] = ()
) -> pd.DataFrame:
    """One result set as a frame of plain Python objects.

    Columns are selected by name, never by position: stats.nba.com adds columns between
    seasons. ``required`` lists the columns the caller will use; a missing one raises
    rather than surfacing later as a confusing ``KeyError``.
    """
    sets = result_sets(snapshot.payload)
    if name is None:
        chosen = sets[0]
    else:
        matches = [candidate for candidate in sets if candidate.get("name") == name]
        if not matches:
            available = [candidate.get("name") for candidate in sets]
            raise PayloadError(
                f"{snapshot.describe()}: no result set {name!r}; available: {available}"
            )
        chosen = matches[0]

    headers = chosen.get("headers")
    rows = chosen.get("rowSet")
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise PayloadError(f"{snapshot.describe()}: result set lacks headers or rows")
    widths = {len(row) for row in rows}
    if widths - {len(headers)}:
        raise PayloadError(
            f"{snapshot.describe()}: rows have {sorted(widths)} values for {len(headers)} headers"
        )
    missing = [column for column in required if column not in headers]
    if missing:
        raise PayloadError(f"{snapshot.describe()}: missing expected columns {missing}")

    # dtype=object keeps every value exactly as the source sent it; each normaliser
    # converts the columns it uses, explicitly.
    return pd.DataFrame(rows, columns=headers, dtype=object)


def row_count(snapshot: Snapshot) -> int:
    """Rows in the snapshot's first result set."""
    rows = result_sets(snapshot.payload)[0].get("rowSet")
    return len(rows) if isinstance(rows, list) else 0


def snapshot_season(snapshot: Snapshot) -> Season:
    """The season a snapshot is filed under, checked against what the source says it sent."""
    try:
        season = Season.parse(snapshot.partition["season"])
    except KeyError:
        raise PayloadError(f"{snapshot.describe()} is not partitioned by season") from None
    parameters = snapshot.payload.get("parameters")
    if isinstance(parameters, Mapping):
        echoed = parameters.get("Season", parameters.get("SeasonYear"))
        if isinstance(echoed, str) and echoed != season.label:
            raise PayloadError(
                f"{snapshot.describe()}: filed under {season.label} but the source "
                f"answered for {echoed}"
            )
    return season


def snapshot_season_type(snapshot: Snapshot) -> SeasonType:
    """The season type a snapshot is filed under, checked against the source's echo."""
    try:
        season_type = SeasonType(snapshot.partition["season_type"])
    except KeyError:
        raise PayloadError(f"{snapshot.describe()} is not partitioned by season type") from None
    parameters = snapshot.payload.get("parameters")
    if isinstance(parameters, Mapping):
        echoed = parameters.get("SeasonType")
        if isinstance(echoed, str) and _SEASON_TYPE_NAMES.get(echoed) != season_type:
            raise PayloadError(
                f"{snapshot.describe()}: filed under {season_type.value} but the source "
                f"answered for {echoed!r}"
            )
    return season_type


def standings_team_ids(snapshot: Snapshot) -> list[int]:
    """Team ids listed in a standings snapshot, ascending."""
    frame = result_set_frame(snapshot, required=("TeamID",))
    return sorted(int(team_id) for team_id in frame["TeamID"])
