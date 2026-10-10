"""Data contracts for current information: what has happened since the build.

The AI research assistant's cache (decision 0018), kept in ``data/current.sqlite`` and
not in the lab's database: a refresh never touches what a build made, and a build never
drops what a refresh fetched. The games are the season in progress as last fetched, in the
lab's own box-score shape; the transactions and the injury report are as the league
publishes them. The refresh log is only ever added to.
"""

from __future__ import annotations

from dataclasses import replace

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables.teams import TEAM_GAMES

_ID = Provenance.IDENTIFIER
_MEASURED = Provenance.MEASURED
_OPS = Provenance.OPERATIONAL
_KEPT = "Kept in data/current.sqlite, not the lab's database."

SOURCES = ("games", "transactions", "injuries")
REFRESH_STATUSES = ("stored", "unchanged", "none", "failed")
INJURY_STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available", "Not Yet Submitted")

CURRENT_GAMES = replace(
    TEAM_GAMES,
    name="current_games",
    domain="current",
    description=(
        "The season in progress's team box scores as last fetched from stats.nba.com: the "
        f"games the assistant can report before a build takes them in. {_KEPT}"
    ),
    introduced_in="A2",
)

TRANSACTIONS = TableContract(
    name="transactions",
    domain="current",
    description=f"Signings, trades, waivers and other moves as the league's player-movement file lists them. {_KEPT}",
    grain="One row per line of the league's file.",
    fields=(
        Field(
            "transaction_key",
            DType.STRING,
            "Fingerprint of the line: its date, type, description, team and player.",
            nullable=False,
            provenance=_ID,
        ),
        Field(
            "transaction_date",
            DType.DATE,
            "Date the league gives the move.",
            nullable=False,
            provenance=_MEASURED,
        ),
        Field(
            "transaction_type",
            DType.STRING,
            "The league's type: Signing, Trade, Waive...",
            nullable=False,
            provenance=_MEASURED,
        ),
        Field(
            "description",
            DType.STRING,
            "The league's description, as written.",
            nullable=False,
            provenance=_MEASURED,
        ),
        Field("team_id", DType.INTEGER, "Team, by the league's id.", nullable=True, provenance=_ID),
        Field(
            "player_id", DType.INTEGER, "Player, by the league's id.", nullable=True, provenance=_ID
        ),
        Field(
            "group_key",
            DType.STRING,
            "The league's grouping of the lines that make one move.",
            nullable=True,
            provenance=_ID,
        ),
        Field(
            "retrieved_at",
            DType.DATETIME,
            "When the lab fetched the file.",
            nullable=False,
            provenance=_OPS,
        ),
    ),
    primary_key=("transaction_key",),
    indexes=(("transaction_date",), ("team_id",), ("player_id",)),
    introduced_in="A2",
)

INJURY_REPORTS = TableContract(
    name="injury_reports",
    domain="current",
    description=f"The league's official injury report - the latest one fetched - line by line. {_KEPT}",
    grain="One row per player, or per team not yet submitted, in one report.",
    fields=(
        Field(
            "report_time",
            DType.DATETIME,
            "When the report was issued, in UTC; the league names its reports in Eastern time.",
            nullable=False,
            provenance=_MEASURED,
        ),
        Field(
            "row_number",
            DType.INTEGER,
            "Position in the report.",
            nullable=False,
            provenance=_ID,
            minimum=1,
        ),
        Field(
            "game_date",
            DType.DATE,
            "Day of the game, as the report gives it.",
            nullable=False,
            provenance=_MEASURED,
        ),
        Field(
            "game_time",
            DType.STRING,
            "Tip-off as the report writes it, Eastern time.",
            nullable=True,
            provenance=_MEASURED,
        ),
        Field(
            "matchup",
            DType.STRING,
            "Away@Home, as the report writes it.",
            nullable=True,
            provenance=_MEASURED,
        ),
        Field(
            "team_name",
            DType.STRING,
            "Team, as the report names it.",
            nullable=False,
            provenance=_MEASURED,
        ),
        Field(
            "player_name",
            DType.STRING,
            "Player as the report writes it: last name, first name.",
            nullable=True,
            provenance=_MEASURED,
        ),
        Field(
            "status",
            DType.STRING,
            "The player's status that day.",
            nullable=False,
            provenance=_MEASURED,
            allowed=INJURY_STATUSES,
        ),
        Field(
            "reason",
            DType.STRING,
            "Reason, as the report writes it.",
            nullable=True,
            provenance=_MEASURED,
        ),
        Field(
            "source_url",
            DType.STRING,
            "The report file's address.",
            nullable=False,
            provenance=_OPS,
        ),
        Field(
            "retrieved_at",
            DType.DATETIME,
            "When the lab fetched it.",
            nullable=False,
            provenance=_OPS,
        ),
    ),
    primary_key=("report_time", "row_number"),
    introduced_in="A2",
)

CURRENT_REFRESHES = TableContract(
    name="current_refreshes",
    domain="current",
    description=f"Every attempt to refresh a current source: when, what happened, from where. Never dropped. {_KEPT}",
    grain="One row per attempt.",
    fields=(
        Field(
            "refresh_id",
            DType.INTEGER,
            "Attempt id, assigned when recorded.",
            nullable=False,
            provenance=_OPS,
            minimum=0,
        ),
        Field(
            "source",
            DType.STRING,
            "Which source.",
            nullable=False,
            provenance=_OPS,
            allowed=SOURCES,
        ),
        Field(
            "attempted_at",
            DType.DATETIME,
            "When the attempt was made.",
            nullable=False,
            provenance=_OPS,
        ),
        Field(
            "status",
            DType.STRING,
            "What happened.",
            nullable=False,
            provenance=_OPS,
            allowed=REFRESH_STATUSES,
        ),
        Field("rows", DType.INTEGER, "Rows stored.", nullable=True, provenance=_OPS, minimum=0),
        Field(
            "detail",
            DType.STRING,
            "What the attempt found, or why it failed.",
            nullable=True,
            provenance=_OPS,
        ),
        Field("url", DType.STRING, "Where it fetched from.", nullable=True, provenance=_OPS),
        Field(
            "content_hash",
            DType.STRING,
            "Fingerprint of what was fetched.",
            nullable=True,
            provenance=_OPS,
        ),
    ),
    primary_key=("refresh_id",),
    indexes=(("source", "attempted_at"),),
    introduced_in="A2",
)

TABLES: tuple[TableContract, ...] = (CURRENT_GAMES, TRANSACTIONS, INJURY_REPORTS, CURRENT_REFRESHES)
