"""The span of games a view covers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True, slots=True)
class Window:
    """The span of games a comparison covers: a whole season unless narrowed."""

    last_games: int | None = None
    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        if self.last_games is not None and self.last_games < 1:
            raise ValueError("a window must cover at least one game")
        if self.start and self.end and self.start > self.end:
            raise ValueError("a window cannot end before it starts")

    @property
    def is_full_season(self) -> bool:
        return self.last_games is None and self.start is None and self.end is None

    @property
    def start_timestamp(self) -> pd.Timestamp | None:
        return pd.Timestamp(self.start) if self.start else None

    @property
    def end_timestamp(self) -> pd.Timestamp | None:
        return pd.Timestamp(self.end) if self.end else None

    def describe(self) -> str:
        if self.is_full_season:
            return "Full season"
        parts = []
        if self.last_games is not None:
            parts.append(f"last {self.last_games} games")
        if self.start and self.end:
            parts.append(f"{self.start:%b %d, %Y} to {self.end:%b %d, %Y}")
        elif self.start:
            parts.append(f"from {self.start:%b %d, %Y}")
        elif self.end:
            parts.append(f"through {self.end:%b %d, %Y}")
        text = ", ".join(parts)
        return text[0].upper() + text[1:]
