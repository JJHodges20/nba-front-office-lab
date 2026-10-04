"""Roster fit: the measures a group of players is described by, and the conventions.

Version 4 of the roadmap asks whether a roster's players make sense together, in six
areas: offense, defense, the possession battle, structure, depth and usage. Each measure
here answers one of those questions from what the lab knows of each player - the season
line, the roles filled, the value model's estimate - weighted by the minutes the player
plays for the roster. The measures describe. Whether any of them says something the sum
of the players' impacts does not is a separate, tested question
(``docs/decisions/0012-roster-fit.md``).

The definitions live here, in the domain, so that the table that stores them, the
catalog that labels them and the code that computes them are all read off one list.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

ROTATION_SIZE = 10
"""The rotation: the ten players with the most minutes. Roles are counted among them."""
STARTERS = 5
"""The bench begins after the five players with the most minutes."""
ON_COURT = 5
"""Players on the court: a lineup's sum is five times the minutes-weighted average."""
TOP_USAGE = 3
"""How many of the highest usage rates are added up to ask whether stars can coexist."""


class Area(StrEnum):
    """The roadmap's areas of fit, plus the sum the fit is measured beyond."""

    OFFENSE = "Offense"
    DEFENSE = "Defense"
    POSSESSION = "Possession battle"
    STRUCTURE = "Structure"
    DEPTH = "Depth"
    USAGE = "Usage"
    PARTS = "Sum of parts"


class Kind(StrEnum):
    """What a measure's number is, which decides how it is stored and shown."""

    COUNT = "count"
    """Whole players."""
    SHARE = "share"
    """A fraction, shown as a percentage. May exceed one where the text says so."""
    RATE = "rate"
    """A rate per 100 possessions."""
    SIGNED = "signed"
    """Points per 100 possessions whose sign matters."""
    INCHES = "inches"


class Method(StrEnum):
    """How a measure is computed from the players and their minutes."""

    COUNT = "count"
    """Players in the rotation (or on the bench) who fill any of the roles, or are in the group."""
    MEAN = "mean"
    """Minutes-weighted average of the source column over everyone (or the bench)."""
    LINEUP = "lineup"
    """Five times the minutes-weighted average: what five players on the court add up to."""
    SHARE = "share"
    """Share of the profiled minutes played by players for whom the source column is true."""
    TOP = "top"
    """The highest few values of the source column in the rotation, added up."""
    STAR = "star"
    """The top player's share of the rotation's positive total of the source column."""
    COVERED = "covered"
    """The players' minutes over the minutes a team has to fill."""
    UNPROFILED = "unprofiled"
    """Share of the minutes played by players with no profile."""


@dataclass(frozen=True, slots=True)
class Measure:
    key: str
    label: str
    name: str
    description: str
    area: Area
    kind: Kind
    method: Method
    source: str | None = None
    """The profile column the method reads, where it reads one."""
    roles: tuple[str, ...] = ()
    """For a count: the archetypes a player is counted for filling."""
    group: str | None = None
    """For a count: the profile flag a player is counted for instead of, or as well as, a role."""
    bench: bool = False
    """Computed over the bench (the sixth to tenth players by minutes) rather than everyone."""
    higher_is_better: bool | None = None


_PRIMARY = ("primary_creator",)
_CREATORS = ("primary_creator", "secondary_creator")
_DEFENDERS = ("perimeter_defender", "switchable_wing", "rim_protector")
_PER_100 = "per 100 possessions on the court"
_WEIGHTED = "Minutes-weighted average of the players'"

MEASURES: tuple[Measure, ...] = (
    # --- offense: creation, shooting, rim pressure, passing ---------------------------------
    Measure(
        "primary_creators", "Primary", "Primary creators",
        "Players in the rotation who fill the primary creator role.",
        Area.OFFENSE, Kind.COUNT, Method.COUNT, roles=_PRIMARY,
    ),
    Measure(
        "creators", "Creators", "Creators",
        "Players in the rotation who fill the primary or the secondary creator role.",
        Area.OFFENSE, Kind.COUNT, Method.COUNT, roles=_CREATORS,
    ),
    Measure(
        "spacers", "Spacers", "Floor spacers",
        "Players in the rotation who fill the floor spacer role.",
        Area.OFFENSE, Kind.COUNT, Method.COUNT, roles=("floor_spacer",),
    ),
    Measure(
        "three_point_rate", "3PA/100", "Three-point attempts",
        f"{_WEIGHTED} three-point attempts {_PER_100}.",
        Area.OFFENSE, Kind.RATE, Method.MEAN, source="fg3a_per_100",
    ),
    Measure(
        "three_point_accuracy", "3P% reg.", "Three-point accuracy, regressed",
        f"{_WEIGHTED} three-point percentage with league-average attempts mixed in, so "
        "that a few hot nights do not make a shooter.",
        Area.OFFENSE, Kind.SHARE, Method.MEAN, source="fg3_pct_regressed", higher_is_better=True,
    ),
    Measure(
        "free_throw_rate", "FT rate", "Free-throw rate",
        f"{_WEIGHTED} free-throw attempts per field-goal attempt: the nearest a box score "
        "comes to pressure on the rim.",
        Area.OFFENSE, Kind.SHARE, Method.MEAN, source="free_throw_rate",
    ),
    Measure(
        "assist_rate", "AST%", "Assist percentage",
        f"{_WEIGHTED} share of teammates' baskets assisted while on the court.",
        Area.OFFENSE, Kind.SHARE, Method.MEAN, source="assist_pct", higher_is_better=True,
    ),
    Measure(
        "offense_sum", "O-SUM", "Offense, sum of parts",
        "The players' offensive impacts added up for the minutes given: the points per 100 "
        "possessions a team would gain on offense if its players simply added up.",
        Area.OFFENSE, Kind.SIGNED, Method.LINEUP, source="impact_offense", higher_is_better=True,
    ),
    # --- defense: perimeter, switching, rim protection ----------------------------------------
    Measure(
        "perimeter_defenders", "Perimeter", "Perimeter defenders",
        "Players in the rotation who fill the perimeter defender role.",
        Area.DEFENSE, Kind.COUNT, Method.COUNT, roles=("perimeter_defender",),
    ),
    Measure(
        "switchable_wings", "Wings", "Switchable wings",
        "Players in the rotation who fill the switchable wing role.",
        Area.DEFENSE, Kind.COUNT, Method.COUNT, roles=("switchable_wing",),
    ),
    Measure(
        "rim_protectors", "Rim", "Rim protectors",
        "Players in the rotation who fill the rim protector role.",
        Area.DEFENSE, Kind.COUNT, Method.COUNT, roles=("rim_protector",),
    ),
    Measure(
        "steal_rate", "STL/100", "Steals",
        f"{_WEIGHTED} steals {_PER_100}.",
        Area.DEFENSE, Kind.RATE, Method.MEAN, source="stl_per_100", higher_is_better=True,
    ),
    Measure(
        "block_rate", "BLK/100", "Blocks",
        f"{_WEIGHTED} blocks {_PER_100}.",
        Area.DEFENSE, Kind.RATE, Method.MEAN, source="blk_per_100", higher_is_better=True,
    ),
    Measure(
        "defense_sum", "D-SUM", "Defense, sum of parts",
        "The players' defensive impacts added up for the minutes given: the points per 100 "
        "possessions a team would save if its players simply added up.",
        Area.DEFENSE, Kind.SIGNED, Method.LINEUP, source="impact_defense", higher_is_better=True,
    ),
    # --- the possession battle: rebounding, turnovers ---------------------------------------
    Measure(
        "rebound_rate", "REB%", "Rebound percentage",
        f"{_WEIGHTED} share of available rebounds taken while on the court.",
        Area.POSSESSION, Kind.SHARE, Method.MEAN, source="reb_pct", higher_is_better=True,
    ),
    Measure(
        "turnover_rate", "TOV%", "Turnover percentage",
        f"{_WEIGHTED} turnovers per play used.",
        Area.POSSESSION, Kind.SHARE, Method.MEAN, source="turnover_pct", higher_is_better=False,
    ),
    # --- structure: size, positions, flexibility --------------------------------------------
    Measure(
        "height", "Height", "Height, minutes-weighted",
        "Average listed height in inches, each player weighted by minutes.",
        Area.STRUCTURE, Kind.INCHES, Method.MEAN, source="height_inches",
    ),
    Measure(
        "guard_minutes", "G min", "Minutes by guards",
        "Share of the minutes played by players listed at guard, alone or with another "
        "position.",
        Area.STRUCTURE, Kind.SHARE, Method.SHARE, source="in_guards",
    ),
    Measure(
        "wing_minutes", "Wing min", "Minutes by wings",
        "Share of the minutes played by players of wing size listed at forward or at "
        "guard-forward. Guards and big men of that size are not wings here.",
        Area.STRUCTURE, Kind.SHARE, Method.SHARE, source="in_wings",
    ),
    Measure(
        "big_minutes", "Big min", "Minutes by big men",
        "Share of the minutes played by players listed at center or standing 6'11\" and "
        "taller.",
        Area.STRUCTURE, Kind.SHARE, Method.SHARE, source="in_bigs",
    ),
    Measure(
        "multi_position", "Two-pos", "Minutes by two-position players",
        "Share of the minutes played by players listed at two positions: the nearest the "
        "listings come to positional flexibility. Athleticism is not in the data at all.",
        Area.STRUCTURE, Kind.SHARE, Method.SHARE, source="two_positions",
    ),
    # --- depth: the bench, and how much rests on one player ---------------------------------
    Measure(
        "bench_impact", "Bench IMP", "Bench impact",
        "Minutes-weighted average impact of the sixth to tenth players by minutes.",
        Area.DEPTH, Kind.SIGNED, Method.MEAN, source="impact", bench=True, higher_is_better=True,
    ),
    Measure(
        "bench_creators", "Bench cre.", "Bench creators",
        "Players among the sixth to tenth by minutes who fill a creator role.",
        Area.DEPTH, Kind.COUNT, Method.COUNT, roles=_CREATORS, bench=True,
    ),
    Measure(
        "bench_bigs", "Bench bigs", "Bench big men",
        "Players among the sixth to tenth by minutes who are big men.",
        Area.DEPTH, Kind.COUNT, Method.COUNT, group="in_bigs", bench=True,
    ),
    Measure(
        "bench_defenders", "Bench def.", "Bench defenders",
        "Players among the sixth to tenth by minutes who fill a defensive role: perimeter "
        "defender, switchable wing or rim protector.",
        Area.DEPTH, Kind.COUNT, Method.COUNT, roles=_DEFENDERS, bench=True,
    ),
    Measure(
        "unprofiled_share", "No profile", "Minutes without a profile",
        "Share of the minutes played by players with no statistics to build a profile from: "
        "in a real season, newcomers to the league.",
        Area.DEPTH, Kind.SHARE, Method.UNPROFILED,
    ),
    Measure(
        "star_share", "Star share", "Reliance on one player",
        "The top player's wins above replacement as a share of the rotation's, counting "
        "only players above replacement. The higher, the more rests on one player staying "
        "fit.",
        Area.DEPTH, Kind.SHARE, Method.STAR, source="wins_added", higher_is_better=False,
    ),
    # --- usage: can the stars coexist? ---------------------------------------------------------
    Measure(
        "usage_sum", "USG sum", "Usage on the floor",
        "Five times the minutes-weighted average usage rate: what the players' usage adds "
        "up to with five of them on the court. A real team's adds up to 100%. A roster "
        "assembled from several teams can ask for more plays than a game has, or fewer.",
        Area.USAGE, Kind.SHARE, Method.LINEUP, source="usage_pct",
    ),
    Measure(
        "usage_top", "USG top 3", "Usage of the three highest-usage players",
        "The three highest usage rates in the rotation added up: how much of the offense "
        "three players are used to running.",
        Area.USAGE, Kind.SHARE, Method.TOP, source="usage_pct",
    ),
    # --- the sum of parts: what the fit is measured beyond ----------------------------------
    Measure(
        "impact_sum", "IMP sum", "Impact, sum of parts",
        "The players' impacts added up for the minutes given: the net rating, relative to "
        "the league, a team would have if its players simply added up.",
        Area.PARTS, Kind.SIGNED, Method.LINEUP, source="impact", higher_is_better=True,
    ),
    Measure(
        "projected_sum", "P-IMP sum", "Projected impact, sum of parts",
        "The same with each player's projection going into the season instead of what the "
        "season showed.",
        Area.PARTS, Kind.SIGNED, Method.LINEUP, source="projected_impact", higher_is_better=True,
    ),
    Measure(
        "minutes_covered", "MIN cov.", "Minutes covered",
        "The players' minutes as a share of the minutes a team has to fill in the season.",
        Area.PARTS, Kind.SHARE, Method.COVERED,
    ),
)  # fmt: skip

MEASURE_KEYS: tuple[str, ...] = tuple(item.key for item in MEASURES)
COVERAGE_ROLES: tuple[str, ...] = tuple(sorted({role for item in MEASURES for role in item.roles}))
"""Every archetype the counts refer to. A set of rules without one of them counts nobody."""


def measure(key: str) -> Measure:
    for item in MEASURES:
        if item.key == key:
            return item
    raise KeyError(f"no fit measure named {key!r}")


def measures_in(area: Area) -> tuple[Measure, ...]:
    return tuple(item for item in MEASURES if item.area is area)
