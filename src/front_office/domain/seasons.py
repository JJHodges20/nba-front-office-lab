"""NBA season identifiers.

A season is named for the two calendar years it spans ("2025-26"). Everything in the
lab that is season-specific - statistics, salaries, cap rules - is keyed by that label,
so parsing and ordering live in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

_LABEL = re.compile(r"^(\d{4})-(\d{2})$")

FIRST_SEASON_START_YEAR = 1946
"""The league's first season was 1946-47."""

LEAGUE_YEAR_START_MONTH = 7
"""The NBA league year - and with it a new salary cap - begins on July 1."""


class SeasonType(StrEnum):
    """The competition phases the lab stores."""

    REGULAR = "regular"
    PLAYOFFS = "playoffs"
    PLAY_IN = "playin"

    @property
    def title(self) -> str:
        return {"regular": "Regular Season", "playoffs": "Playoffs", "playin": "Play-In"}[
            self.value
        ]


@dataclass(frozen=True, order=True, slots=True)
class Season:
    """One NBA season, identified by the calendar year in which it starts."""

    start_year: int

    def __post_init__(self) -> None:
        if isinstance(self.start_year, bool) or not isinstance(self.start_year, int):
            raise TypeError(f"start_year must be an int, got {type(self.start_year).__name__}")
        if not FIRST_SEASON_START_YEAR <= self.start_year <= 9998:
            raise ValueError(
                f"start_year {self.start_year} is outside the NBA's history "
                f"(first season started in {FIRST_SEASON_START_YEAR})"
            )

    @classmethod
    def parse(cls, label: str) -> Season:
        """Parse a label such as ``"2025-26"`` or ``"1999-00"``."""
        match = _LABEL.match(label.strip()) if isinstance(label, str) else None
        if match is None:
            raise ValueError(f"not a season label (expected e.g. '2025-26'): {label!r}")
        start_year = int(match.group(1))
        if int(match.group(2)) != (start_year + 1) % 100:
            raise ValueError(f"season label years are not consecutive: {label!r}")
        return cls(start_year)

    @classmethod
    def coerce(cls, value: Season | str | int) -> Season:
        """Accept a ``Season``, a label, or a start year."""
        if isinstance(value, Season):
            return value
        if isinstance(value, str):
            return cls.parse(value)
        return cls(value)

    @classmethod
    def league_year_on(cls, day: date) -> Season:
        """The season whose league year (July 1 - June 30) contains ``day``.

        This is the season whose salary cap applies on that date. It says nothing about
        whether games have been played yet: on 1 October the league year has already
        rolled over, but the regular season has not started.
        """
        start_year = day.year if day.month >= LEAGUE_YEAR_START_MONTH else day.year - 1
        return cls(start_year)

    @classmethod
    def span(cls, first: Season | str | int, last: Season | str | int) -> list[Season]:
        """Every season from ``first`` to ``last`` inclusive, oldest first."""
        start, end = cls.coerce(first), cls.coerce(last)
        if end < start:
            raise ValueError(f"season span is reversed: {start} to {end}")
        return [cls(year) for year in range(start.start_year, end.start_year + 1)]

    @property
    def end_year(self) -> int:
        return self.start_year + 1

    @property
    def label(self) -> str:
        return f"{self.start_year}-{self.end_year % 100:02d}"

    def next(self) -> Season:
        return Season(self.start_year + 1)

    def previous(self) -> Season:
        return Season(self.start_year - 1)

    def offset(self, seasons: int) -> Season:
        return Season(self.start_year + seasons)

    def __str__(self) -> str:
        return self.label
