"""The lab as the workbench sees it: one object that opens the data and answers questions.

A :class:`Lab` holds the database and the configured season rules. The services hang off
it. Nothing here is cached: every answer is read fresh, so a rebuild in another process
is seen at once. A screen that wants caching keys it on :attr:`LabStatus.build_id`.
Within one answer a service may ask the lab to be :meth:`Lab.remembering` what it reads,
so that a season drawn for thirty teams reads each table once.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

import pandas as pd

from front_office.config.models import (
    fit_evidence_path,
    postseason_model_path,
    simulator_model_path,
    value_model_path,
)
from front_office.config.season_rules import load_all_season_rules
from front_office.config.settings import Settings, load_settings
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.seasons import Season
from front_office.storage import Database, OperationsLog, RosterRepository, StorageError, Warehouse

if TYPE_CHECKING:
    from front_office.services.benchmarks import BenchmarkService
    from front_office.services.builder import BuilderService
    from front_office.services.contracts import ContractService
    from front_office.services.current import CurrentDataService
    from front_office.services.documents import DocumentService
    from front_office.services.entities import EntityService
    from front_office.services.experiments import ExperimentService
    from front_office.services.fit import FitService
    from front_office.services.health import HealthService
    from front_office.services.league import LeagueService
    from front_office.services.optimizer import OptimizerService
    from front_office.services.players import PlayerService
    from front_office.services.postseason import PostseasonService
    from front_office.services.proposals import ProposalService
    from front_office.services.simulator import SimulatorService
    from front_office.services.teams import TeamService
    from front_office.services.value import ValueService
    from front_office.services.workspaces import WorkspaceService


class LabNotBuilt(RuntimeError):
    """The database has no league data yet."""

    def __init__(self) -> None:
        super().__init__("no data has been built yet; run: fol refresh")


def _memo_key(table: str, where: dict | None, kwargs: dict) -> tuple | None:
    """What a read is remembered under, or ``None`` when its filters cannot be hashed."""
    try:
        filters = (
            None
            if where is None
            else tuple(
                sorted(
                    (
                        str(column),
                        tuple(wanted) if isinstance(wanted, list | tuple | set) else wanted,
                    )
                    for column, wanted in where.items()
                )
            )
        )
        key = (table, filters, tuple(kwargs.get("order_by", ())))
        hash(key)
    except TypeError:
        return None
    return key


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
    contract_as_of: date | None = None
    """The date the imported contract file was current, as stated at import."""

    @property
    def has_contracts(self) -> bool:
        return bool(self.contract_seasons)

    @property
    def latest_stats_season(self) -> str | None:
        return self.team_seasons[0] if self.team_seasons else None

    @property
    def default_payroll_season(self) -> str | None:
        """The season payroll is priced in by default.

        The season the contract file was current for: the league year (July to June) that
        holds its as-of date, when the file covers that season and it has cap rules. A
        file that looks ahead from a later season is priced in the earliest season it
        covers that has rules; a history that stops before its date, in the latest. With
        no contract file, the newest season with cap rules.
        """
        priced = [season for season in self.contract_seasons if season in self.cap_seasons]
        if not priced:
            return self.cap_seasons[0] if self.cap_seasons else None
        if self.contract_as_of is None:
            return priced[-1]
        current = Season.league_year_on(self.contract_as_of).label
        if current in priced:
            return current
        earlier = [season for season in priced if season < current]
        return earlier[0] if earlier else priced[-1]


class Lab:
    """Open access to the lab's data for the services."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings.database_path)
        self.warehouse = Warehouse(self.database)
        self.rosters = RosterRepository(self.database)
        self.operations = OperationsLog(self.database)
        self._rules = load_all_season_rules(settings.season_rules_dir)
        self._memo: dict[tuple, pd.DataFrame] | None = None

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
            contract_as_of=self._contract_as_of(),
        )

    def require_built(self) -> None:
        if not self.warehouse.is_built():
            raise LabNotBuilt

    def read(self, table: str, where: dict | None = None, **kwargs: object) -> pd.DataFrame:
        """Read a table, turning "not built" into the error the workbench explains.

        Inside a :meth:`remembering` block a read is served from what the block has
        already read, as a copy, so that what a caller does to a frame stays its own.
        """
        key = None if self._memo is None else _memo_key(table, where, kwargs)
        if key is not None and self._memo is not None and key in self._memo:
            return self._memo[key].copy()
        try:
            frame = self.warehouse.read(table, where, **kwargs)  # type: ignore[arg-type]
        except StorageError as error:
            if not self.warehouse.is_built():
                raise LabNotBuilt from error
            raise
        if key is not None and self._memo is not None:
            self._memo[key] = frame.copy()
        return frame

    @contextmanager
    def remembering(self) -> Iterator[None]:
        """Within the block, a table read once is not read again.

        For one answer that reads the same tables many times over - a season drawn for
        every team, a scenario before and after. What was read is forgotten when the
        block ends, so the next answer still sees a rebuild. Blocks nest: an inner block
        shares the memory of the outer one.
        """
        outer = self._memo
        if outer is None:
            self._memo = {}
        try:
            yield
        finally:
            self._memo = outer

    def model_stamp(self) -> str:
        """When the fitted files last changed: the value model, the fit evidence, the
        postseason model and the simulator. Fitting or measuring again changes a file
        without a build, so a screen keys what it caches of them on this as well."""
        config_dir = self.settings.config_dir
        parts = []
        for path in (
            value_model_path(config_dir),
            fit_evidence_path(config_dir),
            postseason_model_path(config_dir),
            simulator_model_path(config_dir),
        ):
            try:
                stat = path.stat()
            except FileNotFoundError:
                parts.append(f"{path.name}:-")
            else:
                parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        return "|".join(parts)

    def rules(self, season: str) -> SeasonRules | None:
        """Cap rules for a season, or ``None`` if none are configured."""
        return self._rules.get(Season.parse(season))

    def team_labels(self) -> pd.DataFrame:
        """Current abbreviation and name of every team, indexed by ``team_id``."""
        teams = self.read("teams")
        return teams.set_index("team_id")[["abbreviation", "full_name", "conference", "division"]]

    def _seasons(self, table: str) -> tuple[str, ...]:
        return tuple(sorted(self.warehouse.distinct(table, "season"), reverse=True))

    def _contract_as_of(self) -> date | None:
        """The date the contracts were current: the newest as-of date stated at import."""
        stated = self.warehouse.distinct("contracts", "as_of_date")
        return pd.Timestamp(max(stated)).date() if stated else None

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
    def current(self) -> CurrentDataService:
        from front_office.services.current import CurrentDataService

        return CurrentDataService(self)

    @property
    def documents(self) -> DocumentService:
        from front_office.services.documents import DocumentService

        return DocumentService(self)

    @property
    def entities(self) -> EntityService:
        from front_office.services.entities import EntityService

        return EntityService(self)

    @property
    def experiments(self) -> ExperimentService:
        from front_office.services.experiments import ExperimentService

        return ExperimentService(self)

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

    @property
    def proposals(self) -> ProposalService:
        from front_office.services.proposals import ProposalService

        return ProposalService(self)

    @property
    def workspaces(self) -> WorkspaceService:
        from front_office.services.workspaces import WorkspaceService

        return WorkspaceService(self)

    @property
    def simulator(self) -> SimulatorService:
        from front_office.services.simulator import SimulatorService

        return SimulatorService(self)
