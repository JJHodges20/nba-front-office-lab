"""Data contracts for the player value domain: what the value model says of each player.

Everything here is an estimate. The columns are marked ``modeled`` so that no screen can
show one as if it had been counted, and every row names the fitted model it came from.
"""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables import _fields as f

_PER_100 = "points per 100 possessions"

# The parts a season's impact is built from, in the order they are shown. The keys match
# the components of the value model; ``baseline`` is what is assumed where the player's
# own numbers run out.
IMPACT_PARTS: tuple[tuple[str, str], ...] = (
    ("efficiency", "scoring efficiency"),
    ("creation", "creation: scoring attempts, assists and free throws"),
    ("shooting", "spacing: three-point attempts"),
    ("rebounding", "rebounding"),
    ("ball_security", "ball security: turnovers"),
    ("defensive_activity", "defensive activity: steals, blocks and fouls"),
    ("on_court", "the team's results with the player on the court"),
    ("team_context", "the results of the teams played for"),
)
BASELINE_PART = "baseline"
PART_PREFIX = "impact_from_"
PART_COLUMNS: tuple[str, ...] = tuple(
    f"{PART_PREFIX}{key}" for key in (*(key for key, _ in IMPACT_PARTS), BASELINE_PART)
)


def _modeled(name: str, description: str, *, unit: str | None = _PER_100, **limits: float) -> Field:
    return Field(name, DType.FLOAT, description, provenance=Provenance.MODELED, unit=unit, **limits)


PLAYER_VALUE_SCORES = TableContract(
    name="player_value_scores",
    domain="player_value",
    description=(
        "The value model's estimate of each player in each regular season: what the "
        "season showed, what was expected going into it, and what both are worth in "
        "wins. A row for a season the player has not played holds the projection alone."
    ),
    grain="One row per player per season.",
    fields=(
        f.player_id(),
        f.season(),
        Field(
            "model_version",
            DType.STRING,
            "Revision of the fitted value model that produced the row.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "age",
            DType.INTEGER,
            "Age in the season: as published if the player appeared, otherwise carried "
            "forward from the last season played.",
            provenance=Provenance.DERIVED,
            unit="years",
            minimum=15,
            maximum=60,
        ),
        Field(
            "minutes_share",
            DType.FLOAT,
            "Minutes played as a share of the team's game minutes, added up over every "
            "team played for: 1 is every minute of every game.",
            provenance=Provenance.DERIVED,
            unit="fraction",
            minimum=0,
        ),
        Field(
            "reliability",
            DType.FLOAT,
            "Share of the season's estimate that rests on the player's own numbers; the "
            "rest is what is assumed of any player used that much.",
            provenance=Provenance.DERIVED,
            unit="fraction",
            minimum=0,
            maximum=1,
        ),
        _modeled(
            "impact",
            "Estimated effect on a team's net rating while on the court, against the "
            "league's average minute, from this season alone.",
        ),
        _modeled("impact_offense", "The part of impact that is points added on offense."),
        _modeled("impact_defense", "The part of impact that is points saved on defense."),
        *(
            _modeled(f"{PART_PREFIX}{key}", f"The part of impact that comes from {text}.")
            for key, text in IMPACT_PARTS
        ),
        _modeled(
            f"{PART_PREFIX}{BASELINE_PART}",
            "The part of impact that is assumed rather than shown: the level given to the "
            "share of the estimate the minutes do not vouch for, less the constant that "
            "puts the league's average minute at zero.",
        ),
        _modeled(
            "wins_added",
            "Wins the season was worth over a replacement player in the same minutes.",
            unit="wins",
        ),
        _modeled(
            "projected_impact",
            "Impact expected going into the season, from the seasons before it and age.",
        ),
        _modeled("projected_offense", "The offensive part of projected impact."),
        _modeled("projected_defense", "The defensive part of projected impact."),
        Field(
            "projection_reliability",
            DType.FLOAT,
            "Share of the projection that rests on the player's own earlier numbers. "
            "Null for a player with no earlier season.",
            provenance=Provenance.DERIVED,
            unit="fraction",
            minimum=0,
            maximum=1,
        ),
        Field(
            "projection_seasons",
            DType.INTEGER,
            "Earlier seasons the projection draws on; 0 for a player with none.",
            nullable=False,
            provenance=Provenance.DERIVED,
            minimum=0,
        ),
        _modeled(
            "projected_share",
            "Share of team minutes expected going into the season.",
            unit="fraction",
            minimum=0,
            maximum=1,
        ),
        _modeled(
            "projected_wins",
            "Wins over a replacement player expected going into the season, over 82 games.",
            unit="wins",
        ),
    ),
    primary_key=("player_id", "season"),
    indexes=(("season",),),
    introduced_in="V3",
)

TABLES: tuple[TableContract, ...] = (PLAYER_VALUE_SCORES,)
