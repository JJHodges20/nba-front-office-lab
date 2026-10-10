"""Current information, normalised: the league's transactions and its injury report.

Pure functions (decision 0018): what a provider fetched goes in, frames that satisfy the
contracts of ``domain/tables/current.py`` come out. Rules applied to the source, each
noted where it is applied:

- The player-movement file writes ids as decimals and 0 for a move without a player or a
  team: ids are whole numbers, and 0 is no id. Identical lines are kept once.
- The injury report is a PDF table, read by where each piece of text sits on the page:
  every column starts where its header does, a row is anchored by its player (or by a team
  not yet submitted), a reason wrapped over several lines - or onto the next page - joins
  its row, and the date, time, matchup and team written once for a group carry down to
  every row of it.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
from pypdf import PdfReader

from front_office.domain.schema import conform_frame
from front_office.domain.tables.current import INJURY_REPORTS, INJURY_STATUSES, TRANSACTIONS


class CurrentPayloadError(ValueError):
    """A fetched file is not what its source publishes."""


# --- transactions ----------------------------------------------------------------------


def transactions_frame(
    payload: Mapping[str, Any], retrieved_at: datetime, notes: list[str] | None = None
) -> pd.DataFrame:
    try:
        rows = payload["NBA_Player_Movement"]["rows"]
    except (KeyError, TypeError) as error:
        raise CurrentPayloadError("not the league's player-movement file") from error
    records = []
    for row in rows:
        moved = {
            "transaction_date": pd.Timestamp(row["TRANSACTION_DATE"]).date(),
            "transaction_type": str(row["Transaction_Type"]),
            "description": str(row["TRANSACTION_DESCRIPTION"]),
            "team_id": _league_id(row.get("TEAM_ID")),
            "player_id": _league_id(row.get("PLAYER_ID")),
            "group_key": row.get("GroupSort") or None,
            "retrieved_at": retrieved_at,
        }
        moved["transaction_key"] = _fingerprint(moved)
        records.append(moved)
    frame = pd.DataFrame(records, columns=list(TRANSACTIONS.column_names))
    repeated = int(frame.duplicated("transaction_key").sum())
    if repeated and notes is not None:
        notes.append(f"{repeated} line(s) repeated in the file, kept once")
    frame = frame.drop_duplicates("transaction_key")
    return conform_frame(frame.sort_values(["transaction_date", "transaction_key"]), TRANSACTIONS)


def _league_id(value: object) -> int | None:
    """The file writes ids as decimals, and 0 where a move names no player or team."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    number = int(float(value))  # type: ignore[arg-type]
    return number or None


def _fingerprint(row: Mapping[str, object]) -> str:
    parts = (
        row["transaction_date"],
        row["transaction_type"],
        row["description"],
        row["team_id"],
        row["player_id"],
    )
    return hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:20]


# --- the injury report -----------------------------------------------------------------

COLUMNS = ("game_date", "game_time", "matchup", "team_name", "player_name", "status", "reason")
HEADERS = ("Game", "Game", "Matchup", "Team", "Player", "Current", "Reason")
CARRIED = ("game_date", "game_time", "matchup", "team_name")
ANCHORING = ("player_name", "status")
NOT_SUBMITTED = "NOT YET SUBMITTED"
SAME_LINE = 1.5
"""Points of height within which two pieces of text are on one line."""
CONTINUATION = 12.0
"""Points above a page's first row beyond which reason text belongs to the page before."""


@dataclass(frozen=True, slots=True)
class _Text:
    y: float
    x: float
    text: str
    page: int = 0


def injury_frame(
    pdf: bytes, *, report_time: datetime, url: str, retrieved_at: datetime
) -> pd.DataFrame:
    try:
        pages = PdfReader(io.BytesIO(pdf)).pages
    except Exception as error:  # pypdf raises several kinds for a damaged file
        raise CurrentPayloadError(f"the injury report could not be read: {error}") from error
    starts: list[float] | None = None
    rows: list[dict[str, list[_Text]]] = []
    for number, page in enumerate(pages):
        items = _without_footer(_texts(page, number))
        if not items:
            continue
        header_y, starts = _header(items, starts)
        body = [item for item in items if item.y < header_y - SAME_LINE]
        anchors = sorted(
            {round(item.y, 1) for item in body if _column(item.x, starts) in ANCHORING}
            | {round(item.y, 1) for item in body if NOT_SUBMITTED.split()[-1] in item.text},
            reverse=True,
        )
        if not anchors:
            continue
        first = len(rows)
        rows.extend({column: [] for column in COLUMNS} for _ in anchors)
        for item in body:
            column = _column(item.x, starts)
            if column == "reason" and item.y > anchors[0] + CONTINUATION and first > 0:
                rows[first - 1]["reason"].append(item)  # a reason carried over the page break
                continue
            nearest = min(range(len(anchors)), key=lambda index: abs(anchors[index] - item.y))
            rows[first + nearest][column].append(item)
    return conform_frame(_frame(rows, report_time, url, retrieved_at), INJURY_REPORTS)


def _texts(page: Any, number: int = 0) -> list[_Text]:
    items: list[_Text] = []

    def visit(text: str, cm: list, tm: list, font: object, size: object) -> None:
        if text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            items.append(_Text(y, x, text.strip(), number))

    page.extract_text(visitor_text=visit)
    return items


def _header(items: list[_Text], known: list[float] | None) -> tuple[float, list[float]]:
    """Where the column headers are, and the x at which each column starts. A page with no
    header row keeps the previous page's columns, and its body starts below its title."""
    marker = next((item for item in items if item.text == "Matchup"), None)
    if marker is not None:
        line = sorted(
            (item for item in items if abs(item.y - marker.y) <= SAME_LINE), key=lambda item: item.x
        )
        starts = [item.x for item in line if item.text in HEADERS]
        starts = _first_of_each(line, starts)
        if len(starts) != len(COLUMNS):
            raise CurrentPayloadError(
                f"the injury report's header has {len(starts)} columns, not {len(COLUMNS)}"
            )
        return marker.y, starts
    if known is None:
        raise CurrentPayloadError("the injury report has no header row")
    title = next((item.y for item in items if item.text.startswith("Report")), None)
    return (title if title is not None else max(item.y for item in items) + 1), known


def _without_footer(items: list[_Text]) -> list[_Text]:
    """A page without its "Page n of m" line, wherever the page puts it."""
    footer = next((item.y for item in items if item.text == "Page"), None)
    if footer is None:
        return items
    return [item for item in items if abs(item.y - footer) > SAME_LINE]


def _first_of_each(line: list[_Text], starts: list[float]) -> list[float]:
    """The header words in order: 'Game Date', 'Game Time', 'Matchup', 'Team', 'Player
    Name', 'Current Status', 'Reason' - one start per heading."""
    wanted = list(HEADERS)
    found = []
    for item in line:
        if wanted and item.text == wanted[0]:
            found.append(item.x)
            wanted.pop(0)
    return found


def _column(x: float, starts: list[float]) -> str:
    index = 0
    for position, start in enumerate(starts):
        if x >= start - SAME_LINE:
            index = position
    return COLUMNS[index]


def _joined(items: list[_Text]) -> str | None:
    """A cell's text in reading order - page, then line, then left to right. A piece ending
    in a hyphen ("Two-") is the first half of a word the report sets as two ("Two-Way")."""
    text = ""
    for item in sorted(items, key=lambda item: (item.page, -round(item.y, 1), item.x)):
        joiner = (
            "" if not text or (text.endswith("-") and len(text) > 1 and text[-2] != " ") else " "
        )
        text += joiner + item.text
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _frame(
    rows: list[dict[str, list[_Text]]], report_time: datetime, url: str, retrieved_at: datetime
) -> pd.DataFrame:
    records = []
    carried: dict[str, str | None] = dict.fromkeys(CARRIED)
    for number, row in enumerate(rows, start=1):
        cells = {column: _joined(items) for column, items in row.items()}
        for column in CARRIED:
            if cells[column]:
                carried[column] = cells[column]
            cells[column] = carried[column]
        reason = cells["reason"]
        if reason and NOT_SUBMITTED in reason.upper() and not cells["player_name"]:
            status, reason = "Not Yet Submitted", None
        else:
            status = cells["status"]
        if status not in INJURY_STATUSES:
            raise CurrentPayloadError(
                f"row {number} of the injury report has the status {status!r}"
            )
        if cells["game_date"] is None or cells["team_name"] is None:
            raise CurrentPayloadError(f"row {number} of the injury report has no game or team")
        records.append(
            {
                "report_time": report_time,
                "row_number": number,
                "game_date": _day(cells["game_date"]),
                "game_time": cells["game_time"],
                "matchup": cells["matchup"],
                "team_name": cells["team_name"],
                "player_name": cells["player_name"],
                "status": status,
                "reason": None if reason in (None, "-") else reason,
                "source_url": url,
                "retrieved_at": retrieved_at,
            }
        )
    return pd.DataFrame(records, columns=list(INJURY_REPORTS.column_names))


def _day(text: str) -> date:
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError as error:
        raise CurrentPayloadError(f"the injury report has the game date {text!r}") from error
