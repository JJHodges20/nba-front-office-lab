"""The simulator's parameters in the pipeline: measured from the database on request, and
written only when asked."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pytest

from front_office.config import (
    Settings,
    load_eras,
    load_settings,
    load_simulator_model,
    load_simulator_spec,
    load_value_model,
    postseason_model_path,
    simulator_model_path,
    simulator_spec_path,
    value_model_path,
)
from front_office.modeling.simulator import fit_simulator_model
from front_office.pipelines.simulator import (
    FIT_COMMAND,
    SimulatorFitError,
    SimulatorFitReport,
    fit_simulator,
    write_simulator_model,
)

NOW = datetime(2026, 10, 5, 9, 30)


@pytest.fixture
def played(simulator_home: Path, tmp_path: Path) -> Settings:
    """A private copy of the simulator project with no parameters on file yet."""
    target = tmp_path / "played"
    shutil.copytree(simulator_home, target)
    simulator_model_path(target / "configs").unlink()
    return load_settings(target)


class TestFitting:
    def test_the_first_fit_is_revision_one_and_is_the_modeling_fit(
        self, played: Settings, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        report = fit_simulator(played, now=lambda: NOW)
        assert isinstance(report, SimulatorFitReport)
        assert report.previous is None and report.changed
        model = report.model
        assert (model.revision, model.fitted_at) == (1, NOW)
        assert (model.value_model_version, model.postseason_model_version) == ("r1", "p1")
        assert model.spec == load_simulator_spec(played.config_dir)
        direct = fit_simulator_model(
            postseason_league[2],
            model.spec,
            list(load_eras(played.config_dir)),
            load_value_model(played.config_dir),
            revision=1,
            fitted_at=NOW,
            postseason_model_version="p1",
        )
        assert model == direct

    def test_fitting_writes_nothing(self, played: Settings) -> None:
        fit_simulator(played, now=lambda: NOW)
        assert not simulator_model_path(played.config_dir).exists()

    def test_a_written_model_is_the_one_the_services_read(self, played: Settings) -> None:
        model = fit_simulator(played, now=lambda: NOW).model
        path = write_simulator_model(played, model)
        assert path == simulator_model_path(played.config_dir)
        assert load_simulator_model(played.config_dir) == model

    def test_fitting_again_on_the_same_data_changes_nothing_but_the_stamp(
        self, played: Settings
    ) -> None:
        first = fit_simulator(played, now=lambda: NOW).model
        write_simulator_model(played, first)
        later = datetime(2026, 11, 1)
        again = fit_simulator(played, now=lambda: later)
        assert again.previous == first
        assert (again.model.revision, again.model.fitted_at) == (2, later)
        assert not again.changed

    def test_a_changed_specification_is_a_changed_model(self, played: Settings) -> None:
        write_simulator_model(played, fit_simulator(played, now=lambda: NOW).model)
        path = simulator_spec_path(played.config_dir)
        path.write_text(path.read_text(encoding="utf-8") + "noise_seasons: 3\n", encoding="utf-8")
        again = fit_simulator(played, now=lambda: NOW)
        assert again.changed and again.model.revision == 2
        assert again.model.spec.noise_seasons == 3

    def test_without_a_postseason_model_the_parameters_still_measure(
        self, played: Settings
    ) -> None:
        postseason_model_path(played.config_dir).unlink()
        model = fit_simulator(played, now=lambda: NOW).model
        assert model.postseason_model_version is None and model.revision == 1

    def test_without_a_value_model_it_says_what_to_do_first(self, played: Settings) -> None:
        value_model_path(played.config_dir).unlink()
        with pytest.raises(SimulatorFitError, match="no value model has been fitted"):
            fit_simulator(played)

    def test_without_a_database_it_says_to_build_one(self, settings: Settings) -> None:
        with pytest.raises(SimulatorFitError, match="has not been built; run: fol refresh"):
            fit_simulator(settings)
        assert not settings.database_path.exists()

    def test_the_fixture_store_measures_what_it_can(self, built_lab: Settings) -> None:
        # Three seasons of teams and one of players: little, but enough. Players the value
        # model never saw count as the least reliable projections, so they are measured too.
        report = fit_simulator(built_lab)
        model = report.model
        assert report.previous is not None and model.revision == report.previous.revision + 1
        assert model.fitted_on.team_seasons > 0 and model.test.team_seasons > 0
        assert sum(band.players for band in model.development) > 0
        assert report.changed
        # Measuring writes nothing: the file on hand is still the one shipped.
        assert load_simulator_model(built_lab.config_dir).revision == report.previous.revision

    def test_the_command_is_named_for_every_message(self) -> None:
        assert FIT_COMMAND == "fol simulate fit --write"


def test_a_fit_report_without_a_previous_model_is_a_change(simulator_home: Path) -> None:
    model = load_simulator_model(simulator_home / "configs")
    assert model is not None
    assert SimulatorFitReport(model, None).changed
    assert not SimulatorFitReport(model.model_copy(update={"revision": 2}), model).changed
    other = model.model_copy(update={"season_noise": model.season_noise + 1})
    assert SimulatorFitReport(other, model).changed
