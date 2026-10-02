"""Named spans of seasons for historical research.

An era is a filter, not a finding. Where "the modern era" begins is a convention, so an
era states its span and the reason for it, and the definitions live in configuration
(``configs/eras.yaml``) where they can be seen and changed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, PositiveInt, field_validator, model_validator

from front_office.domain.seasons import Season

_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class Era(BaseModel):
    """A span of seasons: between two named seasons, or the latest few on record.

    With neither a first nor a last season, and no count, an era is every season.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    first_season: str | None = None
    last_season: str | None = None
    latest_seasons: PositiveInt | None = None
    """Cover this many of the most recent seasons on record instead of a fixed span."""
    note: str = ""
    """Why the era is drawn where it is."""

    @field_validator("key")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _KEY.match(value):
            raise ValueError(f"an era key is lowercase letters, digits and underscores: {value!r}")
        return value

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an era needs a name")
        return value.strip()

    @field_validator("first_season", "last_season")
    @classmethod
    def _season_label(cls, value: str | None) -> str | None:
        return None if value is None else Season.parse(value).label

    @model_validator(mode="after")
    def _one_kind_of_span(self) -> Era:
        fixed = self.first_season is not None or self.last_season is not None
        if fixed and self.latest_seasons is not None:
            raise ValueError(
                f"era {self.key!r} names seasons and also asks for the latest "
                f"{self.latest_seasons}: it can be one or the other"
            )
        if self.first_season and self.last_season:
            if Season.parse(self.last_season) < Season.parse(self.first_season):
                raise ValueError(
                    f"era {self.key!r} is reversed: {self.first_season} to {self.last_season}"
                )
        return self

    @classmethod
    def between(cls, first_season: str, last_season: str) -> Era:
        """A span chosen on the spot rather than configured."""
        name = first_season if first_season == last_season else f"{first_season} to {last_season}"
        return cls(key="custom", name=name, first_season=first_season, last_season=last_season)

    def seasons(self, on_record: Sequence[str]) -> tuple[str, ...]:
        """The seasons of ``on_record`` this era covers, oldest first.

        ``on_record`` is the seasons there is data for, in any order. An era never
        reaches outside them: "the latest ten" of six seasons is those six.
        """
        ordered = sorted({Season.parse(label) for label in on_record})
        if self.latest_seasons is not None:
            ordered = ordered[-self.latest_seasons :]
        if self.first_season is not None:
            first = Season.parse(self.first_season)
            ordered = [season for season in ordered if season >= first]
        if self.last_season is not None:
            last = Season.parse(self.last_season)
            ordered = [season for season in ordered if season <= last]
        return tuple(season.label for season in ordered)

    def describe(self, on_record: Sequence[str]) -> str:
        """The span in words, as it falls on the seasons there is data for."""
        covered = self.seasons(on_record)
        if not covered:
            return "no seasons on record"
        if len(covered) == 1:
            return covered[0]
        return f"{covered[0]} to {covered[-1]} ({len(covered)} seasons)"


class EraSet(BaseModel):
    """The configured eras, in the order they are offered. The first is the default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eras: tuple[Era, ...]

    @model_validator(mode="after")
    def _distinct(self) -> EraSet:
        if not self.eras:
            raise ValueError("at least one era must be configured")
        keys = [era.key for era in self.eras]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"era keys are repeated: {', '.join(repeated)}")
        return self

    def __getitem__(self, key: str) -> Era:
        for era in self.eras:
            if era.key == key:
                return era
        known = ", ".join(era.key for era in self.eras)
        raise KeyError(f"no era named {key!r} (configured: {known})")

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.eras)

    def __len__(self) -> int:
        return len(self.eras)

    @property
    def default(self) -> Era:
        return self.eras[0]
