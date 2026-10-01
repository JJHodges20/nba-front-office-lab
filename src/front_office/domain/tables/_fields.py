"""Field builders shared by the table contracts."""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance
from front_office.domain.seasons import SeasonType

CONFERENCES = ("East", "West")
SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)

# The counting statistics of a box score, in the order they are stored.
BOX_SCORE: tuple[tuple[str, str], ...] = (
    ("fgm", "Field goals made"),
    ("fga", "Field goals attempted"),
    ("fg3m", "Three-point field goals made"),
    ("fg3a", "Three-point field goals attempted"),
    ("ftm", "Free throws made"),
    ("fta", "Free throws attempted"),
    ("oreb", "Offensive rebounds"),
    ("dreb", "Defensive rebounds"),
    ("reb", "Total rebounds"),
    ("ast", "Assists"),
    ("tov", "Turnovers"),
    ("stl", "Steals"),
    ("blk", "Blocks"),
    ("pf", "Personal fouls"),
    ("pts", "Points"),
)
BOX_SCORE_COLUMNS = tuple(name for name, _ in BOX_SCORE)


def season() -> Field:
    return Field(
        "season",
        DType.STRING,
        "Season label, e.g. 2025-26.",
        nullable=False,
        provenance=Provenance.IDENTIFIER,
    )


def season_type() -> Field:
    return Field(
        "season_type",
        DType.STRING,
        "Phase of the season.",
        nullable=False,
        provenance=Provenance.IDENTIFIER,
        allowed=SEASON_TYPES,
    )


def team_id(
    name: str = "team_id", description: str = "Team id.", *, nullable: bool = False
) -> Field:
    return Field(
        name,
        DType.INTEGER,
        description,
        nullable=nullable,
        provenance=Provenance.IDENTIFIER,
        references="teams.team_id",
    )


def player_id() -> Field:
    return Field(
        "player_id",
        DType.INTEGER,
        "Player id.",
        nullable=False,
        provenance=Provenance.IDENTIFIER,
        references="players.player_id",
    )


def game_id() -> Field:
    return Field(
        "game_id",
        DType.STRING,
        "Game id: ten digits, kept as text because it starts with zeros.",
        nullable=False,
        provenance=Provenance.IDENTIFIER,
    )


def label(name: str, description: str, *, nullable: bool = True, **extra: object) -> Field:
    return Field(
        name,
        DType.STRING,
        description,
        nullable=nullable,
        provenance=Provenance.IDENTIFIER,
        **extra,
    )


def count(name: str, description: str, *, nullable: bool = False, unit: str | None = None) -> Field:
    return Field(name, DType.INTEGER, description, nullable=nullable, unit=unit, minimum=0)


def box_score(prefix: str = "", subject: str = "") -> tuple[Field, ...]:
    """The box-score counting statistics, optionally prefixed (``opp_``) and described."""
    suffix = f" {subject}" if subject else ""
    return tuple(count(f"{prefix}{name}", f"{text}{suffix}.") for name, text in BOX_SCORE)


def rating(name: str, description: str, *, nullable: bool = True) -> Field:
    return Field(name, DType.FLOAT, description, nullable=nullable, unit="per 100 possessions")


def share(name: str, description: str) -> Field:
    return Field(name, DType.FLOAT, description, unit="fraction", minimum=0, maximum=1)
