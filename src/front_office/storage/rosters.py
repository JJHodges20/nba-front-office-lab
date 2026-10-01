"""The user's rosters: the only league-facing data the lab writes on a user's behalf."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from front_office.domain.seasons import Season
from front_office.domain.tables.rosters import CUSTOM_ROSTERS, ROSTER_PLAYERS, ROSTER_SLOTS
from front_office.storage.database import Database, StorageError
from front_office.storage.warehouse import frame_from_rows

MAX_NAME_LENGTH = 80


class RosterNotFound(StorageError):
    pass


def _utc_now() -> datetime:
    """Now, as naive UTC: the form every stored datetime takes."""
    return datetime.now(UTC).replace(tzinfo=None)


class RosterRepository:
    """Create, change and read user-built rosters."""

    def __init__(self, database: Database, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._rosters = database.kept[CUSTOM_ROSTERS.name]
        self._players = database.kept[ROSTER_PLAYERS.name]
        self._now = now

    def create(self, name: str, *, stats_season: str, payroll_season: str) -> int:
        """Create an empty roster and return its id."""
        moment = self._now()
        with self._database.begin() as connection:
            result = connection.execute(
                self._rosters.insert().values(
                    name=_clean_name(name),
                    stats_season=Season.parse(stats_season).label,
                    payroll_season=Season.parse(payroll_season).label,
                    notes=None,
                    created_at=moment,
                    updated_at=moment,
                )
            )
            return int(result.inserted_primary_key[0])

    def list(self) -> pd.DataFrame:
        """Every roster, most recently changed first."""
        statement = select(self._rosters).order_by(
            self._rosters.c.updated_at.desc(), self._rosters.c.roster_id.desc()
        )
        with self._database.connect() as connection:
            return frame_from_rows(connection.execute(statement).mappings().all(), CUSTOM_ROSTERS)

    def get(self, roster_id: int) -> dict:
        with self._database.connect() as connection:
            row = (
                connection.execute(
                    select(self._rosters).where(self._rosters.c.roster_id == roster_id)
                )
                .mappings()
                .first()
            )
        if row is None:
            raise RosterNotFound(f"no roster with id {roster_id}")
        return dict(row)

    def players(self, roster_id: int) -> pd.DataFrame:
        """The roster's players in the order they were added."""
        self.get(roster_id)
        statement = (
            select(self._players)
            .where(self._players.c.roster_id == roster_id)
            .order_by(self._players.c.added_at, self._players.c.player_id)
        )
        with self._database.connect() as connection:
            return frame_from_rows(connection.execute(statement).mappings().all(), ROSTER_PLAYERS)

    def update(
        self,
        roster_id: int,
        *,
        name: str | None = None,
        stats_season: str | None = None,
        payroll_season: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Change a roster's details. Arguments left as ``None`` are not changed."""
        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = _clean_name(name)
        if stats_season is not None:
            changes["stats_season"] = Season.parse(stats_season).label
        if payroll_season is not None:
            changes["payroll_season"] = Season.parse(payroll_season).label
        if notes is not None:
            changes["notes"] = notes.strip() or None
        with self._database.begin() as connection:
            self._touch(connection, roster_id, **changes)

    def delete(self, roster_id: int) -> None:
        """Remove a roster and its players."""
        with self._database.begin() as connection:
            removed = connection.execute(
                delete(self._rosters).where(self._rosters.c.roster_id == roster_id)
            )
            if removed.rowcount == 0:
                raise RosterNotFound(f"no roster with id {roster_id}")

    def set_player(
        self,
        roster_id: int,
        player_id: int,
        *,
        slot: str = "BENCH",
        assumed_salary: int | None = None,
    ) -> None:
        """Add a player, or change the slot or assumed salary of one already there."""
        if slot not in ROSTER_SLOTS:
            raise StorageError(f"slot must be one of {list(ROSTER_SLOTS)}, not {slot!r}")
        if assumed_salary is not None and assumed_salary < 0:
            raise StorageError("an assumed salary cannot be negative")
        with self._database.begin() as connection:
            self._touch(connection, roster_id)
            exists = connection.execute(
                select(func.count())
                .select_from(self._players)
                .where(
                    self._players.c.roster_id == roster_id, self._players.c.player_id == player_id
                )
            ).scalar_one()
            if exists:
                connection.execute(
                    update(self._players)
                    .where(
                        self._players.c.roster_id == roster_id,
                        self._players.c.player_id == player_id,
                    )
                    .values(slot=slot, assumed_salary=assumed_salary)
                )
            else:
                connection.execute(
                    self._players.insert().values(
                        roster_id=roster_id,
                        player_id=int(player_id),
                        slot=slot,
                        assumed_salary=assumed_salary,
                        added_at=self._now(),
                    )
                )

    def remove_player(self, roster_id: int, player_id: int) -> None:
        with self._database.begin() as connection:
            self._touch(connection, roster_id)
            connection.execute(
                delete(self._players).where(
                    self._players.c.roster_id == roster_id, self._players.c.player_id == player_id
                )
            )

    def clear(self, roster_id: int) -> None:
        """Remove every player from a roster."""
        with self._database.begin() as connection:
            self._touch(connection, roster_id)
            connection.execute(delete(self._players).where(self._players.c.roster_id == roster_id))

    def _touch(self, connection, roster_id: int, **changes: object) -> None:  # type: ignore[no-untyped-def]
        """Apply changes to a roster and mark it as just updated; fail if it is gone."""
        try:
            result = connection.execute(
                update(self._rosters)
                .where(self._rosters.c.roster_id == roster_id)
                .values(updated_at=self._now(), **changes)
            )
        except IntegrityError as error:
            raise StorageError(f"could not update roster {roster_id}: {error.orig}") from error
        if result.rowcount == 0:
            raise RosterNotFound(f"no roster with id {roster_id}")


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise StorageError("a roster needs a name")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise StorageError(f"a roster name can be at most {MAX_NAME_LENGTH} characters")
    return cleaned
