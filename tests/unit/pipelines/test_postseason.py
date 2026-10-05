"""The postseason model in the pipeline: fitted from the database on request, and written
only when asked."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from front_office.config import (
    Settings,
    load_eras,
    load_postseason_model,
    load_postseason_spec,
    load_settings,
    postseason_model_path,
    postseason_spec_path,
    value_model_path,
)
from front_office.modeling.postseason import fit_postseason_model
from front_office.pipelines.postseason import (
    FIT_COMMAND,
    PostseasonFitError,
    PostseasonFitReport,
    fit_postseason,
    write_postseason_model,
)
from front_office.storage import Database

NOW = datetime(2026, 10, 5, 9, 30)


@pytest.fixture
def played(postseason_home: Path, tmp_path: Path) -> Settings:
    """A private copy of the project with the invented league's playoffs and no postseason
    model on file yet."""
    target = tmp_path / "played"
    shutil.copytree(postseason_home, target)
    postseason_model_path(target / "configs").unlink()
    return load_settings(target)


class TestFitting:
    def test_the_first_fit_is_revision_one_and_is_the_modeling_fit(
        self, played: Settings, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        report = fit_postseason(played, now=lambda: NOW)
        assert isinstance(report, PostseasonFitReport)
        assert report.previous is None and report.changed
        model = report.model
        assert (model.revision, model.fitted_at, model.value_model_version) == (1, NOW, "r1")
        assert model.spec == load_postseason_spec(played.config_dir)
        direct = fit_postseason_model(
            postseason_league[2],
            model.spec,
            list(load_eras(played.config_dir)),
            revision=1,
            fitted_at=NOW,
            value_model_version="r1",
        )
        assert model == direct

    def test_fitting_writes_nothing(self, played: Settings) -> None:
        fit_postseason(played, now=lambda: NOW)
        assert not postseason_model_path(played.config_dir).exists()

    def test_a_written_model_is_the_one_the_services_read(self, played: Settings) -> None:
        model = fit_postseason(played, now=lambda: NOW).model
        path = write_postseason_model(played, model)
        assert path == postseason_model_path(played.config_dir)
        assert load_postseason_model(played.config_dir) == model

    def test_fitting_again_on_the_same_data_changes_nothing_but_the_stamp(
        self, played: Settings
    ) -> None:
        first = fit_postseason(played, now=lambda: NOW).model
        write_postseason_model(played, first)
        later = datetime(2026, 11, 1)
        again = fit_postseason(played, now=lambda: later)
        assert again.previous == first
        assert (again.model.revision, again.model.fitted_at) == (2, later)
        assert not again.changed

    def test_a_changed_specification_is_a_changed_model(self, played: Settings) -> None:
        write_postseason_model(played, fit_postseason(played, now=lambda: NOW).model)
        path = postseason_spec_path(played.config_dir)
        path.write_text(path.read_text(encoding="utf-8") + "top_players: 2\n", encoding="utf-8")
        again = fit_postseason(played, now=lambda: NOW)
        assert again.changed and again.model.revision == 2
        assert again.model.spec.top_players == 2

    def test_without_a_value_model_it_says_what_to_do_first(self, played: Settings) -> None:
        value_model_path(played.config_dir).unlink()
        with pytest.raises(PostseasonFitError, match="no value model has been fitted"):
            fit_postseason(played)

    def test_without_a_database_it_says_to_build_one(self, settings: Settings) -> None:
        with pytest.raises(PostseasonFitError, match="has not been built; run: fol refresh"):
            fit_postseason(settings)
        assert not settings.database_path.exists()

    def test_a_database_nobody_was_valued_in_says_so(self, played: Settings) -> None:
        with Database(played.database_path) as database, database.begin() as connection:
            connection.execute(text("DELETE FROM player_value_scores"))
        with pytest.raises(PostseasonFitError, match="no player has been valued"):
            fit_postseason(played)

    def test_a_database_that_cannot_support_the_test_says_what_is_missing(
        self, built_lab: Settings
    ) -> None:
        # The fixture store values two teams of one season: no game has both sides known.
        with pytest.raises(PostseasonFitError, match="no decided playoff games"):
            fit_postseason(built_lab)

    def test_the_command_is_named_for_every_message(self) -> None:
        assert FIT_COMMAND == "fol playoffs fit --write"


def test_a_fit_report_without_a_previous_model_is_a_change(postseason_home: Path) -> None:
    model = load_postseason_model(postseason_home / "configs")
    assert model is not None
    assert PostseasonFitReport(model, None).changed
    assert not PostseasonFitReport(model.model_copy(update={"revision": 2}), model).changed
    other = model.model_copy(update={"value_model_version": "r2"})
    assert PostseasonFitReport(other, model).changed
