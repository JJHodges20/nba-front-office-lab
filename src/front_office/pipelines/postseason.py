"""The postseason model, fitted on request from the built database.

Nothing here runs in a build. ``fol playoffs fit`` reads the tables the model is fitted
on, fits and tests it as ``configs/models/postseason.yaml`` specifies, and with
``--write`` saves it where the services read it. A build never fits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from front_office.config.eras import load_eras
from front_office.config.models import (
    load_postseason_model,
    load_postseason_spec,
    load_value_model,
    save_postseason_model,
)
from front_office.config.settings import Settings
from front_office.domain.postseason import PostseasonModel
from front_office.modeling.postseason import FEATURE_TABLES, NotEnoughHistory, fit_postseason_model
from front_office.pipelines.value import utc_now
from front_office.storage import Database, StorageError, Warehouse

FIT_COMMAND = "fol playoffs fit --write"


@dataclass(frozen=True, slots=True)
class PostseasonFitReport:
    model: PostseasonModel
    previous: PostseasonModel | None
    """The model already on file, if there is one."""

    @property
    def changed(self) -> bool:
        """Whether this fit differs from the file in anything but its stamp."""
        if self.previous is None:
            return True
        stamp = {"revision", "fitted_at"}
        return self.model.model_dump(exclude=stamp) != self.previous.model_dump(exclude=stamp)


class PostseasonFitError(RuntimeError):
    """The model could not be fitted; the message says what is missing."""


def fit_postseason(
    settings: Settings, *, now: Callable[[], datetime] = utc_now
) -> PostseasonFitReport:
    """Fit and test the postseason model on the built database. Nothing is written."""
    spec = load_postseason_spec(settings.config_dir)
    previous = load_postseason_model(settings.config_dir)
    value_model = load_value_model(settings.config_dir)
    if value_model is None:
        raise PostseasonFitError(
            "the postseason model reads each team's top players by the value model's impact, "
            "and no value model has been fitted; run: fol value fit --write, then fol build"
        )
    if not settings.database_path.is_file():
        raise PostseasonFitError("the database has not been built; run: fol refresh")
    eras = list(load_eras(settings.config_dir))
    try:
        with Database(settings.database_path) as database:
            warehouse = Warehouse(database)
            tables = {name: warehouse.read(name) for name in FEATURE_TABLES}
        applied = tables["player_value_scores"]["model_version"].dropna().unique()
        if len(applied) == 0:
            raise PostseasonFitError(
                "no player has been valued in the database; run: fol build with the value "
                "model on file"
            )
        revision = 1 if previous is None else previous.revision + 1
        model = fit_postseason_model(
            tables,
            spec,
            eras,
            revision=revision,
            fitted_at=now(),
            value_model_version=str(applied[0]),
        )
    except (StorageError, NotEnoughHistory) as error:
        raise PostseasonFitError(str(error)) from error
    return PostseasonFitReport(model, previous)


def write_postseason_model(settings: Settings, model: PostseasonModel) -> Path:
    return save_postseason_model(settings.config_dir, model)
