"""The lab as the workbench sees it: one object that opens the data and answers questions.

A :class:`Lab` holds the database and the configured season rules. The services hang off
it. Nothing here is cached: every answer is read fresh, so a rebuild in another process
is seen at once. A screen that wants caching keys it on :attr:`LabStatus.build_id`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

import pandas as pd

from front_office.config.season_rules import load_all_season_rules
from front_office.config.settings import Settings, load_settings
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.seasons import Season
from front_office.storage import Database, OperationsLog, RosterRepository, StorageError, Warehouse

if TYPE_CHECKING:
    from front_office.services.benchmarks import BenchmarkService
    from front_office.services.builder import BuilderService
    from front_office.services.contracts import ContractService
    from front_office.services.fit import FitService
    from front_office.services.health import HealthService
    from front_office.services.league import LeagueService
    from front_office.services.optimizer import OptimizerService
    from front_office.services.players import PlayerService
    from front_office.services.postseason import PostseasonService
    from front_office.services.teams import TeamService
    from front_office.services.value import ValueService


class LabNotBuilt(RuntimeError):
    """The database has no league data yet."""

    def __init__(self) -> None:
        super().__init__("no data has been built yet; run: fol refresh")


@dataclass(frozen=True, slots=True)
class LabStatus:
    """What the lab currently holds."""

    is_built: bool
    is_current: bool
    """Whether the tables match this version of the lab."""
    build_id: int | None
    built_at: datetime | None
    team_seasons: tuple[str, ...]
    """Seasons with team statistics, newest first."""
    player_seasons: tuple[str, ...]
    """Seasons with player statistics, newest first."""
    cap_seasons: tuple[str, ...]
    """Seasons with configured cap rules, newest first."""
    contract_seasons: tuple[str, ...]
    """Seasons the imported contract file covers, newest first."""

    @property
    def has_contracts(self) -> bool:
        return bool(self.contract_seasons)

    @property
    def latest_stats_season(self) -> str | None:
        return self.team_seasons[0] if self.team_seasons else None

    @property
    def default_payroll_season(self) -> str | None:
        """The season payroll is priced in by default.

        The earliest season in the contract file that has cap rules - that is the season
        the file was current for - or, with no contract file, the newest season with cap
        rules.
        """
        priced = [season for season in self.contract_seasons if season in self.cap_seasons]
        if priced:
            return priced[-1]
        return self.cap_seasons[0] if self.cap_seasons else None


class Lab:
    """Open access to the lab's data for the services."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings.database_path)
        self.warehouse = Warehouse(self.database)
        self.rosters = RosterRepository(self.database)
        self.operations = OperationsLog(self.database)
        self._rules = load_all_season_rules(settings.season_rules_dir)

    @classmethod
    def open(cls, project_root: Path | None = None) -> Lab:
        return cls(load_settings(project_root))

    def close(self) -> None:
        self.database.dispose()

    def __enter__(self) -> Lab:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def status(self) -> LabStatus:
        cap_seasons = tuple(season.label for season in sorted(self._rules, reverse=True))
        if not self.warehouse.is_built():
            return LabStatus(False, False, None, None, (), (), cap_seasons, ())
        build = self.operations.latest_build()
        return LabStatus(
            is_built=True,
            is_current=self.database.is_current,
            build_id=int(build["build_id"]) if build else None,
            built_at=pd.Timestamp(build["finished_at"]).to_pydatetime() if build else None,
            team_seasons=self._seasons("team_seasons"),
            player_seasons=self._seasons("player_seasons"),
            cap_seasons=cap_seasons,
            contract_seasons=self._seasons("contract_years"),
        )

    def require_built(self) -> None:
        if not self.warehouse.is_built():
            raise LabNotBuilt

    def read(self, table: str, where: dict | None = None, **kwargs: object) -> pd.DataFrame:
        """Read a table, turning "not built" into the error the workbench explains."""
        try:
            return self.warehouse.read(table, where, **kwargs)  # type: ignore[arg-type]
        except StorageError as error:
            if not self.warehouse.is_built():
                raise LabNotBuilt from error
            raise

    def rules(self, season: str) -> SeasonRules | None:
        """Cap rules for a season, or ``None`` if none are configured."""
        return self._rules.get(Season.parse(season))

    def team_labels(self) -> pd.DataFrame:
        """Current abbreviation and name of every team, indexed by ``team_id``."""
        teams = self.read("teams")
        return teams.set_index("team_id")[["abbreviation", "full_name", "conference", "division"]]

    def _seasons(self, table: str) -> tuple[str, ...]:
        return tuple(sorted(self.warehouse.distinct(table, "season"), reverse=True))

    # The services import this module, so they are imported here only when asked for.

    @property
    def players(self) -> PlayerService:
        from front_office.services.players import PlayerService

        return PlayerService(self)

    @property
    def teams(self) -> TeamService:
        from front_office.services.teams import TeamService

        return TeamService(self)

    @property
    def league(self) -> LeagueService:
        from front_office.services.league import LeagueService

        return LeagueService(self)

    @property
    def contracts(self) -> ContractService:
        from front_office.services.contracts import ContractService

        return ContractService(self)

    @property
    def builder(self) -> BuilderService:
        from front_office.services.builder import BuilderService

        return BuilderService(self)

    @property
    def health(self) -> HealthService:
        from front_office.services.health import HealthService

        return HealthService(self)

    @property
    def benchmarks(self) -> BenchmarkService:
        from front_office.services.benchmarks import BenchmarkService

        return BenchmarkService(self)

    @property
    def value(self) -> ValueService:
        from front_office.services.value import ValueService

        return ValueService(self)

    @property
    def fit(self) -> FitService:
        from front_office.services.fit import FitService

        return FitService(self)

    @property
    def optimizer(self) -> OptimizerService:
        from front_office.services.optimizer import OptimizerService

        return OptimizerService(self)

    @property
    def postseason(self) -> PostseasonService:
        from front_office.services.postseason import PostseasonService

        return PostseasonService(self)
