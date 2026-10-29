"""Convert the MrBridge salary table into a contract file the lab can import.

MrBridge's "NBA Salary Cap & Contracts 2016-2026" dataset (mr-bridge.com; salaries from
HoopsHype's public data, snapshot of 2026-07-07) lists salaries in ``player_salaries.csv``
as one row per player per team per season::

    season_year,season,player_id,player,salary,team_id,team,team_option,player_option,
    qualifying_offer,two_way,terminated,notes,source

The lab's long layout (``docs/CONTRACT_DATA.md``) wants ``player,team,season,salary`` with
an optional ``type`` and ``option``. This script writes that file. On the way it:

* leaves HoopsHype's player and team ids out, since they are not the league's: the lab
  matches a row by name and team, and a ``player_id`` column would be read as the
  league's id. ``season_year``, ``notes`` and ``source`` are left out too; the lab has no
  column for them, and the source is stated at import;
* writes ``two_way`` as the contract type, and a team or player option as the option;
* adds up the rows that list one player twice for the same team, season and kind of
  contract: a player signed, waived and signed again, or on successive ten-day contracts.
  The lab's row is what the team owed the player that season, and the lab's duplicate
  check would otherwise reject the file. Every such merge is reported;
* names a team as the league's team index names it (``TEAM_ALIASES``), spells a name the
  way the league's player index spells it where the snapshot differs (``ALIASES``), and
  gives the league's player id where the name alone fits two players, or the index has
  since renamed the player (``PLAYER_IDS``);
* leaves out a row whose player the league index does not hold and whose name the lab
  would otherwise hand to a namesake (``LEFT_OUT``), and says so.

The lists were made from the lab's own unmatched-row report on the 2026-07-07 snapshot;
a later snapshot may need more, and so may a later copy of the league's index: the one
fetched on 2026-10-29 no longer called Kevin Porter Jr. active, which left his name to
two players, and renamed RJ Nembhard Jr.; the one of 2026-10-01 called a camp invitee,
Jameer Nelson Jr., the active Jameer Nelson, and the import gave him his namesake's
salaries of 2015-16 to 2017-18. Players the league index does not hold at all -
camp signings who never played a game - are written as they are; the import reports
them and leaves them out.

A ``qualifying_offer`` or ``terminated`` flag has no counterpart in the lab's file: rows
carrying one are listed in the report and written like any other.

Run from the project root, then import the file it wrote and rebuild::

    .venv\\Scripts\\python.exe scripts\\convert_salary_dataset.py data\\imports\\nba-salary-cap-contracts-2016-2026\\player_salaries.csv data\\imports\\contracts_mrbridge_2026-07-07.csv
    .venv\\Scripts\\fol.exe contracts import data\\imports\\contracts_mrbridge_2026-07-07.csv --source "..." --as-of 2026-07-07
    .venv\\Scripts\\fol.exe build
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

EXPECTED_COLUMNS = frozenset(
    {
        "season_year",
        "season",
        "player_id",
        "player",
        "salary",
        "team_id",
        "team",
        "team_option",
        "player_option",
        "qualifying_offer",
        "two_way",
        "terminated",
        "notes",
        "source",
    }
)
OUTPUT_COLUMNS = ("player_id", "player", "team", "season", "salary", "type", "option")
UNCARRIED_FLAGS = ("qualifying_offer", "terminated")
_SEASON = re.compile(r"^\d{4}-\d{2}$")
_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no", ""}

# The snapshot's name for a team -> the league's full name, as the team index writes it.
TEAM_ALIASES: dict[str, str] = {"Los Angeles Clippers": "LA Clippers"}

# The snapshot's spelling of a name -> the league's, as the player index writes it.
ALIASES: dict[str, str] = {
    "Anthony Barber": "Cat Barber",
    "BJ Boston": "Brandon Boston",
    "Cameron Whitmore": "Cam Whitmore",
    "Carlton Carrington": "Bub Carrington",
    "Cui Yongxi": "Yongxi Cui",
    "David Jones": "David Jones Garcia",
    "Dennis Schroeder": "Dennis Schröder",
    "Enes Kanter": "Enes Freedom",
    "Hansen Yang": "Yang Hansen",
    "Herb Jones": "Herbert Jones",
    "Ishmael Smith": "Ish Smith",
    "Ishmail Wainright": "Ish Wainright",
    "Jose Juan Barea": "J.J. Barea",
    "Joseph Young": "Joe Young",
    "Josh Primo": "Joshua Primo",
    "Juan Hernangomez": "Juancho Hernangomez",
    "Louis Amundson": "Lou Amundson",
    "Louis Williams": "Lou Williams",
    "Matthew Hurt": "Matt Hurt",
    "Maurice Williams": "Mo Williams",
    "Mitch Creek": "Mitchell Creek",
    "Moe Harkless": "Maurice Harkless",
    "Naz Long": "Naz Mitrou-Long",
    "Nicolas Claxton": "Nic Claxton",
    "Nigel Hayes": "Nigel Hayes-Davis",
    "Patrick Mills": "Patty Mills",
    "Raymond Spalding": "Ray Spalding",
    "Ron Holland": "Ronald Holland II",
    "Santiago Aldama": "Santi Aldama",
    # Written without a HoopsHype id in 2022-23; by name alone the lab would match the
    # elder Scottie Pippen.
    "Scottie Pippen Jr": "Scotty Pippen Jr.",
    "Sviatoslav Mykhailiuk": "Svi Mykhailiuk",
    "Timothe Luwawu": "Timothe Luwawu-Cabarrot",
    "Tre Scott": "Trevon Scott",
    "Vince Hunter": "Vincent Hunter",
    "Walter Lemon Jr": "Walt Lemon Jr.",
    "Walter Tavares": "Edy Tavares",
    "Wesley Iwundu": "Wes Iwundu",
    "Yanic Niederhauser": "Yanic Konan Niederhäuser",
}

# The snapshot's spelling of a name -> the league's player id, where the name alone fits
# two players in the league's index and the import's rule (the active one wins) would not
# find the player meant, or where the index has since renamed the player.
PLAYER_IDS: dict[str, int] = {
    "Christapher Johnson": 203187,  # the LSU Chris Johnson, 2012-13 to 2015-16
    "David Johnson": 1630525,
    "Duane Washington Jr": 1630613,
    "George King": 1628994,
    "Gerald Henderson": 201945,
    "Glenn Robinson III": 203922,
    "Greg Smith": 202962,
    "Jameer Nelson": 2749,  # not Jameer Nelson Jr., a camp invitee in the index of 2026-10-01
    "Jeenathan Williams": 1631466,  # the snapshot writes him as Nate Williams from 2023-24
    "John Lucas": 101249,  # John Lucas III
    "Johnny Davis": 1631098,
    "Kevin Porter": 1629645,  # Kevin Porter Jr., not the Kevin Porter of 1972-82
    "Larry Drew II": 203580,
    "Mike Dunleavy": 2399,
    "Mike James": 1628455,
    "Nate Williams": 1631466,
    "Reggie Williams": 202130,
    "RJ Nembhard": 1630612,  # the index renamed him Ruben Nembhard Jr. in October 2026
}

# The snapshot's spelling of a name -> why its rows are left out of the file.
LEFT_OUT: dict[str, str] = {
    "Marcus Thornton II": (
        "played no NBA game, so the league index holds only the elder Marcus Thornton, "
        "and the lab would hand the row to him"
    ),
}


class ConversionError(ValueError):
    """The file is not the dataset's salary table, or a row in it cannot be read."""


@dataclass(frozen=True, slots=True)
class Merge:
    """Rows that listed one player twice for the same team, season and kind of contract."""

    season: str
    player: str
    team: str
    kind: str
    lines: tuple[int, ...]
    salaries: tuple[int, ...]

    @property
    def total(self) -> int:
        return sum(self.salaries)


@dataclass(frozen=True, slots=True)
class FlaggedRow:
    """A row carrying a flag the lab's file has no column for."""

    line: int
    player: str
    team: str
    season: str
    flag: str


@dataclass(frozen=True, slots=True)
class LeftOutRow:
    """A row left out of the file, with the reason."""

    line: int
    player: str
    team: str
    season: str
    salary: int
    reason: str


@dataclass(slots=True)
class Report:
    rows_read: int = 0
    rows_written: int = 0
    seasons: Counter[str] = field(default_factory=Counter)
    merges: list[Merge] = field(default_factory=list)
    aliases: Counter[str] = field(default_factory=Counter)
    ids: Counter[str] = field(default_factory=Counter)
    flagged: list[FlaggedRow] = field(default_factory=list)
    left_out: list[LeftOutRow] = field(default_factory=list)

    def render(self, source: Path, output: Path) -> str:
        lines = [
            f"Read {self.rows_read:,} rows from {source.name}; "
            f"wrote {self.rows_written:,} rows to {output.name}.",
            "Seasons: "
            + ", ".join(f"{season} ({count:,})" for season, count in sorted(self.seasons.items())),
        ]
        if self.merges:
            lines.append(
                f"Added up {len(self.merges)} case(s) of one player listed twice for the same "
                "team, season and kind of contract:"
            )
            for merge in self.merges:
                amounts = " + ".join(f"${salary:,}" for salary in merge.salaries)
                lines.append(
                    f"  {merge.season} {merge.player} ({merge.team}, {merge.kind}; "
                    f"lines {', '.join(map(str, merge.lines))}): {amounts} = ${merge.total:,}"
                )
        if self.aliases:
            lines.append("Names written as the league spells them:")
            for name, count in sorted(self.aliases.items()):
                lines.append(f"  {name} -> {ALIASES.get(name, '?')} ({count} row(s))")
        if self.ids:
            lines.append("Names given the league's player id:")
            for name, count in sorted(self.ids.items()):
                lines.append(f"  {name} -> {PLAYER_IDS.get(name, '?')} ({count} row(s))")
        if self.left_out:
            lines.append(f"{len(self.left_out)} row(s) left out:")
            for row in self.left_out:
                lines.append(
                    f"  line {row.line}: {row.player} ({row.team}, {row.season}, "
                    f"${row.salary:,}) {row.reason}"
                )
        if self.flagged:
            lines.append(
                f"{len(self.flagged)} row(s) carry a flag the lab's file cannot "
                "(written like any other row):"
            )
            for row in self.flagged:
                lines.append(
                    f"  line {row.line}: {row.player} ({row.team}, {row.season}) {row.flag}"
                )
        return "\n".join(lines)


@dataclass(slots=True)
class _Group:
    player: str
    identity: str
    team: str
    season: str
    kind: str
    lines: list[int]
    salaries: list[int]
    options: set[str]


def _flag(row: Mapping[str, str], column: str, line: int) -> bool:
    value = row[column].strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConversionError(f"line {line}: {column} is {row[column]!r}, not true or false")


def convert(
    rows: Iterable[Mapping[str, str]],
    *,
    aliases: Mapping[str, str] | None = None,
    player_ids: Mapping[str, int] | None = None,
    team_aliases: Mapping[str, str] | None = None,
    left_out: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, str]], Report]:
    """The dataset's rows as the lab's long-layout rows, with a report of what was done.

    ``rows`` are the dataset's rows as dictionaries, in file order; the first is line 2.
    """
    aliases = ALIASES if aliases is None else aliases
    player_ids = PLAYER_IDS if player_ids is None else player_ids
    team_aliases = TEAM_ALIASES if team_aliases is None else team_aliases
    left_out = LEFT_OUT if left_out is None else left_out
    report = Report()
    groups: dict[tuple[str, str, str, str], _Group] = {}

    for line, row in enumerate(rows, start=2):
        missing = EXPECTED_COLUMNS - set(row)
        if missing:
            raise ConversionError(f"line {line} lacks column(s) {sorted(missing)}")
        report.rows_read += 1
        player = row["player"].strip()
        team = row["team"].strip()
        season = row["season"].strip()
        if not player:
            raise ConversionError(f"line {line} names no player")
        if not team:
            raise ConversionError(f"line {line} ({player}) names no team")
        if not _SEASON.match(season):
            raise ConversionError(f"line {line} ({player}): season {season!r} is not like 2025-26")
        try:
            salary = int(row["salary"].strip())
        except ValueError:
            raise ConversionError(
                f"line {line} ({player}): salary {row['salary']!r} is not a whole number"
            ) from None
        if salary < 0:
            raise ConversionError(f"line {line} ({player}): salary {salary} is negative")
        if player in left_out:
            report.left_out.append(LeftOutRow(line, player, team, season, salary, left_out[player]))
            continue
        kind = "two-way" if _flag(row, "two_way", line) else "standard"
        options = set()
        if _flag(row, "team_option", line):
            options.add("team")
        if _flag(row, "player_option", line):
            options.add("player")
        for flag in UNCARRIED_FLAGS:
            if _flag(row, flag, line):
                report.flagged.append(FlaggedRow(line, player, team, season, flag))

        # HoopsHype's id tells two spellings of one player apart within the snapshot; it
        # is never written out.
        identity = row["player_id"].strip() or player.lower()
        key = (season, team, kind, identity)
        group = groups.get(key)
        if group is None:
            groups[key] = _Group(player, identity, team, season, kind, [line], [salary], options)
        else:
            group.lines.append(line)
            group.salaries.append(salary)
            group.options |= options

    written: list[dict[str, str]] = []
    for group in groups.values():
        if len(group.lines) > 1:
            report.merges.append(
                Merge(
                    group.season,
                    group.player,
                    group.team,
                    group.kind,
                    tuple(group.lines),
                    tuple(group.salaries),
                )
            )
        if len(group.options) > 1:
            raise ConversionError(
                f"lines {', '.join(map(str, group.lines))} give {group.player} both a team "
                f"and a player option for {group.season}; the lab's file takes one"
            )
        name = aliases.get(group.player, group.player)
        if name != group.player:
            report.aliases[group.player] += 1
        league_id = player_ids.get(group.player)
        if league_id is not None:
            report.ids[group.player] += 1
        written.append(
            {
                "player_id": "" if league_id is None else str(league_id),
                "player": name,
                "team": team_aliases.get(group.team, group.team),
                "season": group.season,
                "salary": str(sum(group.salaries)),
                "type": "" if group.kind == "standard" else group.kind,
                "option": next(iter(group.options), ""),
            }
        )
        report.seasons[group.season] += 1

    written.sort(key=lambda row: (row["season"], row["team"], -int(row["salary"]), row["player"]))
    report.rows_written = len(written)
    return written, report


def convert_file(source: Path, output: Path) -> Report:
    """Read the dataset's salary table and write the lab's contract file."""
    with open(source, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        if columns != EXPECTED_COLUMNS:
            raise ConversionError(
                f"{source.name} is not the dataset's salary table: it has columns "
                f"{sorted(columns)}, expected {sorted(EXPECTED_COLUMNS)}"
            )
        rows, report = convert(reader)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="the dataset's player_salaries.csv")
    parser.add_argument("output", type=Path, help="the contract file to write")
    args = parser.parse_args(argv)
    try:
        report = convert_file(args.source, args.output)
    except (OSError, ConversionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    # A Windows console may not be UTF-8, and the report quotes accented names.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(report.render(args.source, args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
