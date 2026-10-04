"""Data contract for roster fit: every real team-season's profile, for comparison.

A roster built by the user is measured the same way and placed among these rows, so the
table is the reference every "where does this roster stand" question is answered from.
Everything in it is modeled: it rests on the value model and the archetype rules.
"""

from __future__ import annotations

from front_office.domain.fit import MEASURES, Kind, Measure
from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables import _fields as f

_UNITS = {
    Kind.COUNT: "players",
    Kind.SHARE: "share",
    Kind.RATE: "per 100 possessions",
    Kind.SIGNED: "points per 100 possessions",
    Kind.INCHES: "inches",
}


def _field(item: Measure) -> Field:
    limits = {"minimum": 0} if item.kind in (Kind.COUNT, Kind.SHARE) else {}
    return Field(
        item.key,
        DType.FLOAT,
        item.description,
        provenance=Provenance.MODELED,
        unit=_UNITS[item.kind],
        **limits,
    )


TEAM_FIT_PROFILES = TableContract(
    name="team_fit_profiles",
    domain="roster_fit",
    description=(
        "What each team's players added up to in a regular season, in the roadmap's areas "
        "of fit: role coverage, shooting, defense, the possession battle, structure, depth "
        "and usage, each player weighted by the minutes played for the team. The reference "
        "a built roster is placed among."
    ),
    grain="One row per team per regular season with player statistics.",
    fields=(
        f.season(),
        f.team_id(),
        Field(
            "archetype_version",
            DType.STRING,
            "Version of the archetype definitions the role counts come from.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "model_version",
            DType.STRING,
            "Version of the value model the impacts come from; missing when none was fitted.",
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "players",
            DType.INTEGER,
            "Players who played a minute for the team in the season.",
            nullable=False,
            provenance=Provenance.DERIVED,
            minimum=0,
        ),
        *(_field(item) for item in MEASURES),
    ),
    primary_key=("season", "team_id"),
    introduced_in="V4",
)

TABLES: tuple[TableContract, ...] = (TEAM_FIT_PROFILES,)
