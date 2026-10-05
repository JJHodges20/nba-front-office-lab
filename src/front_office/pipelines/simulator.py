"""The simulator's parameters, measured on request from the built database.

Nothing here runs in a build. ``fol simulate fit`` reads the tables the parameters are
measured on, measures and tests them as ``configs/models/simulator.yaml`` specifies, and
with ``--write`` saves the file the services read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from front_office.config.eras import load_eras
from front_office.config.models import (
    load_postseason_model,
    load_simulator_model,
    load_simulator_spec,
    load_value_model,
    save_simulator_model,
)
from front_office.config.settings import Settings
from front_office.domain.simulator import SimulatorModel
from front_office.modeling.simulator import FEATURE_TABLES, NotEnoughHistory, fit_simulator_model
from front_office.pipelines.value import utc_now
from front_office.storage import Database, StorageError, Warehouse

FIT_COMMAND = "fol simulate fit --write"


@dataclass(frozen=True, slots=True)
class SimulatorFitReport:
    model: SimulatorModel
    previous: SimulatorModel | None

    @property
    def changed(self) -> bool:
        """Whether this fit differs from the file in anything but its stamp."""
        if self.previous is None:
            return True
        stamp = {"revision", "fitted_at"}
        return self.model.model_dump(exclude=stamp) != self.previous.model_dump(exclude=stamp)


class SimulatorFitError(RuntimeError):
    """The parameters could not be measured; the message says what is missing."""


def fit_simulator(
    settings: Settings, *, now: Callable[[], datetime] = utc_now
) -> SimulatorFitReport:
    """Measure and test the simulator's parameters on the built database. Nothing is
    written."""
    spec = load_simulator_spec(settings.config_dir)
    previous = load_simulator_model(settings.config_dir)
    value_model = load_value_model(settings.config_dir)
    if value_model is None:
        raise SimulatorFitError(
            "the simulator draws from the value model's projections and its error, and no "
            "value model has been fitted; run: fol value fit --write, then fol build"
        )
    if not settings.database_path.is_file():
        raise SimulatorFitError("the database has not been built; run: fol refresh")
    postseason = load_postseason_model(settings.config_dir)
    eras = list(load_eras(settings.config_dir))
    try:
        with Database(settings.database_path) as database:
            warehouse = Warehouse(database)
            tables = {name: warehouse.read(name) for name in FEATURE_TABLES}
        revision = 1 if previous is None else previous.revision + 1
        model = fit_simulator_model(
            tables,
            spec,
            eras,
            value_model,
            revision=revision,
            fitted_at=now(),
            postseason_model_version=None if postseason is None else postseason.version,
        )
    except (StorageError, NotEnoughHistory) as error:
        raise SimulatorFitError(str(error)) from error
    return SimulatorFitReport(model, previous)


def write_simulator_model(settings: Settings, model: SimulatorModel) -> Path:
    return save_simulator_model(settings.config_dir, model)
