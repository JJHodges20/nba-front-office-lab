"""Player archetypes: how a role is defined.

An archetype is a rule, not a discovery. Each names the measures a player has to be
strong on *together* and the group of players it is open to, and a player's score for
it is the weakest of their percentiles on those measures among that group, in that
season. The definitions live in configuration (``configs/archetypes.yaml``) where they
can be read and changed, and every assignment is stamped with their version.

The cut-off at which a player "fills" a role is a convention. The score beneath it is
kept so that anything built on roles can draw its own line.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

_KEY = re.compile(r"^[a-z][a-z0-9_]*$")

EVERYONE = "everyone"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Archetype(_Frozen):
    key: str
    name: str
    description: str
    """The role in words, as the roadmap gives it."""
    measures: tuple[str, ...]
    """What a player must be strong on together. The score is the weakest of them."""
    among: str = EVERYONE
    """The group the archetype is open to, and within which percentiles are taken."""
    fills_at: float | None = Field(default=None, gt=0, le=100)
    """Score from which a player fills the role; the set's own cut-off if not given."""
    fills_below: float | None = Field(default=None, gt=0, le=100)
    """Score from which the role is no longer this one: a secondary creator stops where
    a primary one begins."""
    note: str = ""
    """What the measures stand in for, and what they cannot see."""

    @field_validator("key")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _KEY.match(value):
            raise ValueError(
                f"an archetype key is lowercase letters, digits, underscores: {value!r}"
            )
        return value

    @field_validator("name", "description")
    @classmethod
    def _worded(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an archetype needs a name and a description")
        return value.strip()

    @field_validator("measures")
    @classmethod
    def _measured(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("an archetype needs at least one measure")
        if len(set(value)) != len(value):
            raise ValueError(f"an archetype repeats a measure: {list(value)}")
        return value


class ArchetypeSet(_Frozen):
    """Every archetype, the cut-off they share, and who is judged at all."""

    version: PositiveInt
    min_minutes: float = Field(ge=0)
    """Minutes in a season below which a player is not given a role: too little to go on."""
    fills_at: float = Field(gt=0, le=100)
    """Score from which a player fills a role, unless the archetype says otherwise."""
    archetypes: tuple[Archetype, ...]

    @model_validator(mode="after")
    def _consistent(self) -> ArchetypeSet:
        keys = [archetype.key for archetype in self.archetypes]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"archetype keys repeat: {repeated}")
        if not keys:
            raise ValueError("at least one archetype is needed")
        for archetype in self.archetypes:
            low, high = self.cut(archetype), archetype.fills_below
            if high is not None and high <= low:
                raise ValueError(
                    f"{archetype.key}: fills_below ({high:g}) must be above fills_at ({low:g})"
                )
        return self

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.archetypes)

    def __len__(self) -> int:
        return len(self.archetypes)

    def __getitem__(self, key: str) -> Archetype:
        for archetype in self.archetypes:
            if archetype.key == key:
                return archetype
        raise KeyError(f"no archetype named {key!r}; known: {self.keys}")

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(archetype.key for archetype in self.archetypes)

    @property
    def label(self) -> str:
        """What an assignment made with these definitions is stamped with."""
        return f"v{self.version}"

    def cut(self, archetype: Archetype) -> float:
        """The score from which a player fills this archetype."""
        return self.fills_at if archetype.fills_at is None else archetype.fills_at
