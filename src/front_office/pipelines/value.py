"""The player value model in the pipeline: applied by every build, fitted on request.

A build *applies* the fitted model it finds in ``configs/models`` and never fits one, so
the same raw store and the same model file always give the same values. Fitting is a
separate, deliberate step - ``fol value fit --write`` - whose result is a file that
shows up in version control.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from front_office.config.models import load_value_model, load_value_spec, save_value_model
from front_office.config.settings import Settings
from front_office.domain.schema import ContractViolationError, conform_frame
from front_office.domain.seasons import Season
from front_office.domain.tables.value import PLAYER_VALUE_SCORES
from front_office.domain.value_model import ValueModel
from front_office.modeling.value import (
    ModelMismatch,
    NotEnoughData,
    fit_value_model,
    score_players,
)
from front_office.pipelines.normalize import (
    ALL_SEASONS,
    BuildIssue,
    IssueSeverity,
    NormalizedTables,
)
from front_office.storage import Database, StorageError, Warehouse

TABLE = PLAYER_VALUE_SCORES.name
FIT_COMMAND = "fol value fit --write"
FITTED_FROM = ("player_seasons", "player_game_logs", "team_seasons")


def add_value_tables(tables: NormalizedTables, model: ValueModel | None) -> None:
    """Score every player with the fitted model, adding the table and anything to report.

    Without a fitted model, or with one this version of the lab cannot apply, the table
    is empty and an issue says why; the rest of the build is unaffected.
    """
    frames = tables.frames
    frames[TABLE] = PLAYER_VALUE_SCORES.empty_frame()
    if model is None:
        tables.issues.append(
            BuildIssue(
                ALL_SEASONS,
                TABLE,
                f"no value model has been fitted, so player value is unavailable. Run: {FIT_COMMAND}",
                IssueSeverity.NOTE,
            )
        )
        return
    try:
        frames[TABLE] = conform_frame(score_players(frames, model), PLAYER_VALUE_SCORES)
    except (ModelMismatch, ContractViolationError) as error:
        tables.issues.append(BuildIssue(ALL_SEASONS, TABLE, str(error)))
        return
    newer = _finished_since(tables, model)
    if newer:
        tables.issues.append(
            BuildIssue(
                ALL_SEASONS,
                TABLE,
                f"the value model was fitted on seasons to {model.fitted_on.last_season}; "
                f"{_listed(newer)} finished since and "
                f"{'is' if len(newer) == 1 else 'are'} valued with the old weights. "
                f"Run: {FIT_COMMAND}",
                IssueSeverity.NOTE,
            )
        )


def _finished_since(tables: NormalizedTables, model: ValueModel) -> list[str]:
    """Finished seasons with player statistics that the model was not fitted on."""
    teams = tables["team_seasons"]
    finished = set(teams.loc[teams["won_championship"].notna(), "season"])
    with_players = set(tables["player_seasons"]["season"])
    last = Season.parse(model.fitted_on.last_season)
    return sorted(season for season in finished & with_players if Season.parse(season) > last)


def _listed(seasons: list[str]) -> str:
    return seasons[0] if len(seasons) == 1 else f"{seasons[0]} to {seasons[-1]}"


@dataclass(frozen=True, slots=True)
class FitReport:
    model: ValueModel
    previous: ValueModel | None
    """The fitted model already on file, if there is one."""

    @property
    def changed(self) -> bool:
        """Whether this fit differs from the one on file in anything but its stamp."""
        if self.previous is None:
            return True
        stamp = {"revision", "fitted_at"}
        return self.model.model_dump(exclude=stamp) != self.previous.model_dump(exclude=stamp)


class ValueFitError(RuntimeError):
    """The value model could not be fitted; the message says what is missing."""


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def fit_value(settings: Settings, *, now: Callable[[], datetime] = utc_now) -> FitReport:
    """Fit the value model on the built database, as ``configs/models`` specifies it.

    Nothing is written. Raises :class:`ValueFitError` if the database has not been built
    or cannot support the fit.
    """
    spec = load_value_spec(settings.config_dir)
    previous = load_value_model(settings.config_dir)
    if not settings.database_path.is_file():
        raise ValueFitError("the database has not been built; run: fol refresh")
    try:
        with Database(settings.database_path) as database:
            warehouse = Warehouse(database)
            tables = {name: warehouse.read(name) for name in FITTED_FROM}
        revision = 1 if previous is None else previous.revision + 1
        model = fit_value_model(tables, spec, revision=revision, fitted_at=now())
    except (StorageError, NotEnoughData) as error:
        raise ValueFitError(str(error)) from error
    return FitReport(model, previous)


def write_value_model(settings: Settings, model: ValueModel) -> Path:
    return save_value_model(settings.config_dir, model)
