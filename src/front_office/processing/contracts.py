"""Normalise a user-supplied contract file into ``contracts`` and ``contract_years``.

Two layouts are accepted, told apart by the header row.

*Wide* - one row per player, one column per season, the way salary tables are usually
laid out::

    player,team,2026-27,2027-28,2028-29,guaranteed
    Pat Example,BOS,"$30,000,000","$32,400,000 PO",,62400000

*Long* - one row per player per season::

    player,team,season,salary,option,guarantee
    Pat Example,BOS,2026-27,30000000,,full

A file-level problem (an unknown column, an unreadable amount, a duplicate) rejects the
whole file: it almost certainly means the file is not what the user thinks it is. A row
that cannot be tied to a known player is left out and reported, because a file of five
hundred names will always contain a spelling the league does not use.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from front_office.domain.contract_review import ContractChange
from front_office.domain.schema import conform_frame
from front_office.domain.seasons import Season
from front_office.domain.snapshots import Snapshot
from front_office.domain.tables.finance import (
    CONTRACT_STATUSES,
    CONTRACT_TYPES,
    CONTRACT_YEARS,
    CONTRACTS,
)

_SEASON_COLUMN = re.compile(r"^\d{4}-\d{2}$")
_SEASON_LIKE = re.compile(r"^(19|20)\d{2}([-/_ ]?\d{2,4})?$")
_AMOUNT = re.compile(r"^\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*([kKmM])?$")
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

_OPTION_TOKENS = {
    "PO": "player",
    "P": "player",
    "PLAYER": "player",
    "TO": "team",
    "T": "team",
    "TEAM": "team",
    "ETO": "early_termination",
    "EARLY_TERMINATION": "early_termination",
}
_GUARANTEE_TOKENS = {
    "G": "full",
    "FULL": "full",
    "PG": "partial",
    "PARTIAL": "partial",
    "NG": "none",
    "NONE": "none",
}
_TYPE_WORDS = {"standard": "standard", "two_way": "two_way", "two-way": "two_way", "2w": "two_way"}
_STATUS_WORDS = {"active": "active", "dead_money": "dead_money", "dead": "dead_money"}

_SHARED_COLUMNS = {"player", "player_id", "team", "type", "status", "guaranteed", "notes"}
_LONG_COLUMNS = {"season", "salary", "option", "guarantee"}

MAX_REPORTED = 25


class ContractFileError(ValueError):
    """The contract file cannot be read as a contract file at all."""


@dataclass(frozen=True, slots=True)
class UnmatchedRow:
    """A file row left out because it could not be tied to a known player or team."""

    line: int
    player: str
    team: str | None
    reason: str


@dataclass(slots=True)
class ContractTables:
    contracts: pd.DataFrame
    contract_years: pd.DataFrame
    unmatched: list[UnmatchedRow] = field(default_factory=list)
    rows_read: int = 0


def normalize_name(name: str) -> str:
    """A name reduced to what matters for matching: letters, lower case, no suffix.

    "Nikola Vučević" and "Nikola Vucevic", "Jaren Jackson Jr." and "Jaren Jackson",
    "O.G. Anunoby" and "OG Anunoby" all compare equal.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    plain = plain.lower().replace("-", " ")
    plain = re.sub(r"[.'’`,]", "", plain)
    words = [word for word in plain.split() if word not in _NAME_SUFFIXES]
    return " ".join(words)


def parse_amount(text: str) -> int:
    """Whole dollars from ``"$30,000,000"``, ``"30000000"``, ``"30.5M"`` or ``"850K"``."""
    match = _AMOUNT.match(text.strip())
    if match is None:
        raise ValueError(f"not a dollar amount: {text!r}")
    whole, fraction, scale = match.groups()
    value = float(whole.replace(",", "") + (fraction or ""))
    if scale:
        value *= 1_000_000 if scale.lower() == "m" else 1_000
    elif fraction:
        raise ValueError(f"salaries are whole dollars; found cents in {text!r}")
    return round(value)


def parse_salary_cell(text: str) -> tuple[int, str | None, str | None]:
    """``(salary, option, guarantee)`` from a wide-layout cell such as ``"$32,400,000 (PO)"``."""
    pieces = text.replace("(", " ").replace(")", " ").split()
    if not pieces:
        raise ValueError("empty salary cell")
    # A dollar sign may stand apart from its number: "$ 30,000,000".
    if pieces[0] == "$" and len(pieces) > 1:
        pieces = pieces[1:]
    salary = parse_amount(pieces[0])
    option = guarantee = None
    for token in pieces[1:]:
        key = token.upper().replace("-", "_")
        if key in _OPTION_TOKENS and option is None:
            option = _OPTION_TOKENS[key]
        elif key in _GUARANTEE_TOKENS and guarantee is None:
            guarantee = _GUARANTEE_TOKENS[key]
        else:
            raise ValueError(f"unrecognised marker {token!r} in {text!r}")
    return salary, option, guarantee


@dataclass(frozen=True, slots=True)
class _Entry:
    """One player-season of salary read from the file."""

    line: int
    player: str
    player_id: int | None
    team: str | None
    contract_type: str
    status: str
    season: Season
    salary: int
    option: str | None
    guarantee: str | None
    guaranteed_amount: int | None


def build_contracts(
    snapshot: Snapshot,
    *,
    players: pd.DataFrame,
    teams: pd.DataFrame,
    caps: Mapping[str, int],
) -> ContractTables:
    """Parse a contract-file snapshot and tie its rows to known players and teams.

    ``caps`` maps a season label to that season's salary cap, for the cap share. A
    season missing from it gets a null share.
    """
    payload = snapshot.payload
    try:
        text, source_label = payload["text"], payload["source_label"]
        as_of = date.fromisoformat(payload["as_of"])
    except (KeyError, TypeError, ValueError) as error:
        raise ContractFileError(f"contract snapshot is malformed: {error}") from error

    entries = _read_entries(text)
    rows_read = len({entry.line for entry in entries})
    team_ids = _TeamIndex(teams)
    player_index = _PlayerIndex(players)

    unmatched: dict[int, UnmatchedRow] = {}
    resolved: list[tuple[_Entry, int, int | None]] = []
    for entry in entries:
        if entry.line in unmatched:
            continue
        team_id, team_problem = team_ids.resolve(entry.team)
        if team_problem:
            unmatched[entry.line] = UnmatchedRow(entry.line, entry.player, entry.team, team_problem)
            continue
        player_id, player_problem = player_index.resolve(entry, team_id)
        if player_problem or player_id is None:
            unmatched[entry.line] = UnmatchedRow(
                entry.line, entry.player, entry.team, player_problem or "no match"
            )
            continue
        resolved.append((entry, player_id, team_id))
    resolved = [item for item in resolved if item[0].line not in unmatched]

    contracts, contract_years = _assemble(resolved, caps, source_label, as_of)
    return ContractTables(
        contracts=contracts,
        contract_years=contract_years,
        unmatched=sorted(unmatched.values(), key=lambda row: row.line),
        rows_read=rows_read,
    )


def compare_contract_years(
    in_use: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    names: Mapping[int, str],
    teams: Mapping[int, str],
) -> tuple[list[ContractChange], int]:
    """Two files' contract seasons side by side (A7): what a candidate adds, drops or
    changes against the file in use, by player, team and season - largest change first -
    and how many are the same in both. A player paid by two teams in a season is compared
    team by team, as the file lists them."""
    before, after = _salaries(in_use), _salaries(candidate)
    changes: list[ContractChange] = []
    unchanged = 0
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old == new:
            unchanged += 1
            continue
        player, team, season = key
        detail = []
        if old is not None and new is not None:
            for what, was, now in (("option", old[1], new[1]), ("guarantee", old[2], new[2])):
                if was != now:
                    detail.append(f"{what}: {was or 'none'} to {now or 'none'}")
        changes.append(
            ContractChange(
                player_id=player,
                player=names.get(player, f"Player {player}"),
                team=None if team < 0 else teams.get(team),
                season=season,
                in_use=None if old is None else old[0],
                candidate=None if new is None else new[0],
                detail="; ".join(detail) or None,
            )
        )
    changes.sort(key=lambda c: (-abs(c.difference), c.season, c.player))
    return changes, unchanged


def _salaries(years: pd.DataFrame) -> dict[tuple[int, int, str], tuple[int, str, str]]:
    """Salary, options and guarantees by player, team (-1 for none) and season."""
    if years.empty:
        return {}
    keyed = years.assign(team_key=years["team_id"].fillna(-1).astype(int))
    found = {}
    for (player, team, season), rows in keyed.groupby(["player_id", "team_key", "season"]):
        found[(int(player), int(team), str(season))] = (
            int(rows["salary"].sum()),
            ", ".join(sorted({str(v) for v in rows["option"].dropna()})),
            ", ".join(sorted({str(v) for v in rows["guarantee"].dropna()})),
        )
    return found


def describe_unmatched(unmatched: list[UnmatchedRow]) -> str | None:
    """A one-line account of the rows left out, for the build notes."""
    if not unmatched:
        return None
    shown = "; ".join(
        f"line {row.line} {row.player}" + (f" ({row.team})" if row.team else "") + f": {row.reason}"
        for row in unmatched[:MAX_REPORTED]
    )
    more = f"; and {len(unmatched) - MAX_REPORTED} more" if len(unmatched) > MAX_REPORTED else ""
    return f"{len(unmatched)} contract file row(s) left out: {shown}{more}"


# --- reading the file -------------------------------------------------------------------


def _read_entries(text: str) -> list[_Entry]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ContractFileError("the contract file has no header row") from None
    columns = [name.strip().lower().replace(" ", "_") for name in header]
    if len(set(columns)) != len(columns):
        repeated = sorted({name for name in columns if columns.count(name) > 1})
        raise ContractFileError(f"the header repeats columns: {repeated}")

    season_columns = [name for name in columns if _SEASON_COLUMN.match(name)]
    is_long = "season" in columns
    if is_long and season_columns:
        raise ContractFileError(
            "the header has both a 'season' column and season columns; use one layout"
        )
    allowed = _SHARED_COLUMNS | (_LONG_COLUMNS if is_long else set(season_columns))
    unknown = [name for name in columns if name not in allowed]
    # The commonest slip is a season written some other way: 2026-2027, 2026/27, 2026.
    misspelt = [name for name in unknown if _SEASON_LIKE.match(name)]
    if misspelt:
        raise ContractFileError(
            f"column(s) {misspelt} look like seasons; write a season as both years, like 2026-27"
        )
    if not is_long and not season_columns:
        raise ContractFileError(
            "the header has no season columns (such as 2026-27) and no 'season' column"
        )
    if unknown:
        raise ContractFileError(
            f"unrecognised column(s) {unknown}; expected some of {sorted(allowed)}"
        )
    if "player" not in columns and "player_id" not in columns:
        raise ContractFileError("the file needs a 'player' column, a 'player_id' column, or both")
    if is_long and "salary" not in columns:
        raise ContractFileError("the long layout needs a 'salary' column")
    seasons = {name: _season(name, 1) for name in season_columns}

    entries: list[_Entry] = []
    for line, values in enumerate(reader, start=2):
        if not any(value.strip() for value in values):
            continue
        if len(values) > len(columns):
            raise ContractFileError(
                f"line {line} has {len(values)} values for {len(columns)} columns"
            )
        row = {name: value.strip() for name, value in zip(columns, values, strict=False)}
        common = _common_fields(row, line)
        if is_long:
            entries.append(_long_entry(row, line, common))
        else:
            entries.extend(_wide_entries(row, line, common, seasons))
    if not entries:
        raise ContractFileError("the contract file lists no salaries")

    # A two-way contract converted to a standard one in the same season is two contracts
    # with the same team, so the kind of contract is part of what makes a row distinct.
    seen: dict[tuple, int] = {}
    for entry in entries:
        key = (
            entry.player_id or normalize_name(entry.player),
            entry.team,
            entry.status,
            entry.contract_type,
            entry.season,
        )
        if key in seen and seen[key] != entry.line:
            raise ContractFileError(
                f"lines {seen[key]} and {entry.line} both give {entry.player} a "
                f"{entry.season.label} salary for the same team, status and kind of contract"
            )
        seen[key] = entry.line
    return entries


def _season(text: str, line: int) -> Season:
    try:
        return Season.parse(text)
    except ValueError as error:
        raise ContractFileError(f"line {line}: {error}") from error


def _common_fields(row: Mapping[str, str], line: int) -> dict:
    player = row.get("player", "")
    raw_id = row.get("player_id", "")
    if not player and not raw_id:
        raise ContractFileError(f"line {line} names no player")
    player_id = None
    if raw_id:
        if not raw_id.isdigit():
            raise ContractFileError(f"line {line}: player_id {raw_id!r} is not a number")
        player_id = int(raw_id)

    type_word = row.get("type", "").lower()
    if type_word and type_word not in _TYPE_WORDS:
        raise ContractFileError(
            f"line {line}: contract type {type_word!r} is not one of {list(CONTRACT_TYPES)}"
        )
    status_word = row.get("status", "").lower()
    if status_word and status_word not in _STATUS_WORDS:
        raise ContractFileError(
            f"line {line}: status {status_word!r} is not one of {list(CONTRACT_STATUSES)}"
        )
    guaranteed = None
    if row.get("guaranteed"):
        try:
            guaranteed = parse_amount(row["guaranteed"])
        except ValueError as error:
            raise ContractFileError(f"line {line}, guaranteed: {error}") from error
    return {
        "line": line,
        "player": player or f"player {player_id}",
        "player_id": player_id,
        "team": row.get("team") or None,
        "contract_type": _TYPE_WORDS.get(type_word, "standard"),
        "status": _STATUS_WORDS.get(status_word, "active"),
        "guaranteed_amount": guaranteed,
    }


def _wide_entries(
    row: Mapping[str, str], line: int, common: dict, seasons: Mapping[str, Season]
) -> list[_Entry]:
    entries = []
    for column, season in seasons.items():
        cell = row.get(column, "")
        if not cell:
            continue
        try:
            salary, option, guarantee = parse_salary_cell(cell)
        except ValueError as error:
            raise ContractFileError(f"line {line}, column {column}: {error}") from error
        entries.append(
            _Entry(season=season, salary=salary, option=option, guarantee=guarantee, **common)
        )
    if not entries:
        raise ContractFileError(f"line {line} ({common['player']}) lists no salary in any season")
    return entries


def _long_entry(row: Mapping[str, str], line: int, common: dict) -> _Entry:
    season = _season(row.get("season", ""), line)
    try:
        salary = parse_amount(row.get("salary", ""))
    except ValueError as error:
        raise ContractFileError(f"line {line}, salary: {error}") from error
    option = guarantee = None
    if row.get("option"):
        key = row["option"].upper().replace("-", "_").replace(" ", "_")
        if key not in _OPTION_TOKENS:
            raise ContractFileError(f"line {line}: unrecognised option {row['option']!r}")
        option = _OPTION_TOKENS[key]
    if row.get("guarantee"):
        key = row["guarantee"].upper()
        if key not in _GUARANTEE_TOKENS:
            raise ContractFileError(f"line {line}: unrecognised guarantee {row['guarantee']!r}")
        guarantee = _GUARANTEE_TOKENS[key]
    return _Entry(season=season, salary=salary, option=option, guarantee=guarantee, **common)


# --- matching ---------------------------------------------------------------------------


class _TeamIndex:
    def __init__(self, teams: pd.DataFrame) -> None:
        self._by_text: dict[str, int] = {}
        for team in teams.itertuples():
            for text in (team.abbreviation, team.full_name, team.nickname):
                self._by_text[str(text).lower()] = int(team.team_id)

    def resolve(self, team: str | None) -> tuple[int | None, str | None]:
        if team is None:
            return None, None
        team_id = self._by_text.get(team.lower())
        if team_id is None:
            return None, f"unknown team {team!r}"
        return team_id, None


class _PlayerIndex:
    def __init__(self, players: pd.DataFrame) -> None:
        self._known = set(players["player_id"].astype(int))
        self._by_name: dict[str, list[tuple[int, bool, int | None]]] = {}
        for player in players.itertuples():
            current = None if pd.isna(player.current_team_id) else int(player.current_team_id)
            self._by_name.setdefault(normalize_name(player.full_name), []).append(
                (int(player.player_id), bool(player.is_active), current)
            )

    def resolve(self, entry: _Entry, team_id: int | None) -> tuple[int | None, str | None]:
        if entry.player_id is not None:
            if entry.player_id not in self._known:
                return None, f"player_id {entry.player_id} is not a known player"
            return entry.player_id, None

        candidates = self._by_name.get(normalize_name(entry.player), [])
        if not candidates:
            return None, "no player with this name"
        if len(candidates) == 1:
            return candidates[0][0], None
        # Several players share the name: prefer the one who is active, then the one
        # on the team the file names.
        active = [candidate for candidate in candidates if candidate[1]]
        if len(active) == 1:
            return active[0][0], None
        pool = active or candidates
        on_team = [
            candidate for candidate in pool if team_id is not None and candidate[2] == team_id
        ]
        if len(on_team) == 1:
            return on_team[0][0], None
        return None, f"{len(candidates)} players share this name; add a player_id column"


# --- assembling the tables --------------------------------------------------------------


def _assemble(
    resolved: list[tuple[_Entry, int, int | None]],
    caps: Mapping[str, int],
    source_label: str,
    as_of: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    grouped: dict[tuple, list[_Entry]] = {}
    for entry, player_id, team_id in resolved:
        key = (player_id, team_id, entry.status, entry.contract_type)
        grouped.setdefault(key, []).append(entry)

    contract_rows, year_rows = [], []
    for (player_id, team_id, status, contract_type), entries in grouped.items():
        entries.sort(key=lambda entry: entry.season)
        # A gap between seasons separates two agreements.
        runs: list[list[_Entry]] = []
        for entry in entries:
            if runs and entry.season == runs[-1][-1].season.next():
                runs[-1].append(entry)
            else:
                runs.append([entry])
        for run in runs:
            first, last = run[0], run[-1]
            contract_id = f"{player_id}-{team_id or 0}-{first.season.label}"
            if status == "dead_money":
                contract_id += "-dead"
            if contract_type == "two_way":
                contract_id += "-2w"
            stated = [
                entry.guaranteed_amount for entry in run if entry.guaranteed_amount is not None
            ]
            contract_rows.append(
                {
                    "contract_id": contract_id,
                    "player_id": player_id,
                    "team_id": team_id,
                    "player_name": first.player,
                    "contract_type": contract_type,
                    "status": status,
                    "first_season": first.season.label,
                    "last_season": last.season.label,
                    "seasons": len(run),
                    "total_salary": sum(entry.salary for entry in run),
                    # Only the first of a player's runs carries the stated guarantee.
                    "guaranteed_amount": stated[0] if stated and run is runs[0] else None,
                    "source_label": source_label,
                    "as_of_date": pd.Timestamp(as_of),
                }
            )
            for position, entry in enumerate(run):
                cap = caps.get(entry.season.label)
                year_rows.append(
                    {
                        "contract_id": contract_id,
                        "season": entry.season.label,
                        "player_id": player_id,
                        "team_id": team_id,
                        "salary": entry.salary,
                        "salary_cap_pct": entry.salary / cap if cap else None,
                        "option": entry.option,
                        "guarantee": entry.guarantee,
                        "years_remaining": len(run) - position - 1,
                    }
                )

    contracts = pd.DataFrame(contract_rows, columns=list(CONTRACTS.column_names))
    years = pd.DataFrame(year_rows, columns=list(CONTRACT_YEARS.column_names))
    return (
        conform_frame(contracts.sort_values("contract_id"), CONTRACTS),
        conform_frame(years.sort_values(["contract_id", "season"]), CONTRACT_YEARS),
    )
