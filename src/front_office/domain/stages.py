"""The stages of a postseason: the points a season can reach, each containing the later ones.

The benchmark research counts how many past teams reached each stage; the postseason
model estimates a team's chance of reaching each. Both read this one list, so that a
stage means the same thing wherever it appears.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Stage:
    """A point a season can reach. Each stage contains every later one."""

    key: str
    """Column of the research frame that says whether a team reached it."""
    label: str
    short: str
    description: str


STAGES: tuple[Stage, ...] = (
    Stage(
        "reached_postseason",
        "Reached the postseason",
        "Postseason",
        "Played in the playoffs or in the play-in tournament.",
    ),
    Stage(
        "made_playoffs",
        "Made the playoffs",
        "Playoffs",
        "Played at least one playoff game: one of the sixteen teams in the bracket.",
    ),
    Stage(
        "won_a_round",
        "Won a playoff series",
        "Second round",
        "Won the first round and reached the conference semifinals.",
    ),
    Stage(
        "made_conference_finals",
        "Reached the conference finals",
        "Conference finals",
        "One of the last four teams.",
    ),
    Stage(
        "made_finals",
        "Reached the NBA Finals",
        "NBA Finals",
        "One of the last two teams.",
    ),
    Stage(
        "won_championship",
        "Won the championship",
        "Champion",
        "Won the NBA Finals.",
    ),
)
STAGE_KEYS: tuple[str, ...] = tuple(stage.key for stage in STAGES)
BRACKET_STAGES: tuple[Stage, ...] = STAGES[1:]
"""The stages the postseason model estimates: from making the playoffs to the title. The
play-in is not modelled; a team that reaches the bracket through it has made the
playoffs like any other."""
BRACKET_STAGE_KEYS: tuple[str, ...] = tuple(stage.key for stage in BRACKET_STAGES)
ROUND_STAGE_KEYS: tuple[str, ...] = BRACKET_STAGE_KEYS[1:]
"""The stages a playoff team can still reach once the bracket is set, in order: won a
round, the conference finals, the Finals, the title."""


def stage(key: str) -> Stage:
    for candidate in STAGES:
        if candidate.key == key:
            return candidate
    raise KeyError(f"no stage named {key!r} (stages: {', '.join(STAGE_KEYS)})")
