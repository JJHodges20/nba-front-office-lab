"""The value model in the pipeline: applied by a build, fitted from the database."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from front_office.config import Settings, load_value_model, value_model_path, value_spec_path
from front_office.domain.schema import validate_frame
from front_office.domain.tables.value import PLAYER_VALUE_SCORES
from front_office.domain.value_model import ValueModel, ValueSpec
from front_office.pipelines.build import build_database
from front_office.pipelines.check import CHECKED_TABLES, check_store
from front_office.pipelines.normalize import IssueSeverity, NormalizedTables
from front_office.pipelines.value import (
    FIT_COMMAND,
    TABLE,
    FitReport,
    ValueFitError,
    add_value_tables,
    fit_value,
    write_value_model,
)
from front_office.rawstore import RawStore
from front_office.storage import Database, Warehouse
from tests.league import SyntheticLeague
from tests.synthetic_lab import league_frames, write_lab
from tests.value_reference import DEFENSE, OFFENSE, planted_league, planted_model

SPEC = ValueSpec(first_test_season="2004-05", resamples=100)
SPEC_FILE = 'first_test_season: "2004-05"\nresamples: 100\n'
NOW = datetime(2026, 10, 2, 9, 30)


@pytest.fixture(scope="module")
def league() -> SyntheticLeague:
    return planted_league(SPEC)


@pytest.fixture
def league_tables(league: SyntheticLeague) -> NormalizedTables:
    frames = league_frames(league)
    del frames[TABLE]
    return NormalizedTables(frames)


@pytest.fixture
def synthetic(project: Path, league: SyntheticLeague) -> Settings:
    """A project whose database holds the invented league and whose model files are
    a specification that fits it and no fitted model."""
    value_spec_path(project / "configs").write_text(SPEC_FILE, encoding="utf-8")
    value_model_path(project / "configs").unlink()
    return write_lab(project, league)


class TestApplyingTheModel:
    def test_every_player_season_is_scored(self, league_tables: NormalizedTables) -> None:
        model = planted_model(SPEC)
        add_value_tables(league_tables, model)
        scores = league_tables[TABLE]
        assert validate_frame(scores, PLAYER_VALUE_SCORES) == []
        played = league_tables["player_seasons"]
        assert len(scores[scores["impact"].notna()]) == len(played)
        assert set(scores["model_version"]) == {"r1"}
        assert league_tables.issues == []

    def test_without_a_fitted_model_the_table_is_empty_and_a_note_says_why(
        self, league_tables: NormalizedTables
    ) -> None:
        add_value_tables(league_tables, None)
        assert league_tables[TABLE].empty
        assert list(league_tables[TABLE].columns) == list(PLAYER_VALUE_SCORES.column_names)
        (issue,) = league_tables.issues
        assert (issue.table, issue.scope, issue.severity) == (
            TABLE,
            "all seasons",
            IssueSeverity.NOTE,
        )
        assert issue.message == (
            "no value model has been fitted, so player value is unavailable. "
            "Run: fol value fit --write"
        )
        assert league_tables.errors == []

    def test_a_model_from_another_version_is_an_error_not_a_crash(
        self, league_tables: NormalizedTables
    ) -> None:
        model = planted_model(SPEC)
        stale = model.model_copy(update={"terms": model.terms[:-1]})
        add_value_tables(league_tables, stale)
        assert league_tables[TABLE].empty
        (issue,) = league_tables.errors
        assert issue.table == TABLE and "missing terms ['new_player']" in issue.message
        assert FIT_COMMAND in issue.message

    @pytest.mark.parametrize(
        ("fitted_through", "expected"),
        [
            ("2008-09", None),
            ("2007-08", "2008-09 finished since and is valued with the old weights."),
            ("2005-06", "2006-07 to 2008-09 finished since and are valued with the old weights."),
        ],
    )
    def test_seasons_finished_since_the_fit_are_noted(
        self, league_tables: NormalizedTables, fitted_through: str, expected: str | None
    ) -> None:
        add_value_tables(league_tables, planted_model(SPEC, last_season=fitted_through))
        assert not league_tables[TABLE].empty  # valued all the same
        if expected is None:
            assert league_tables.issues == []
            return
        (issue,) = league_tables.notes
        assert issue.message == (
            f"the value model was fitted on seasons to {fitted_through}; {expected} "
            "Run: fol value fit --write"
        )

    def test_a_season_still_being_played_is_not_one_the_model_missed(
        self, league: SyntheticLeague
    ) -> None:
        unfinished = planted_league(SPEC)
        unfinished.unfinished = {2008}
        frames = league_frames(unfinished)
        del frames[TABLE]
        tables = NormalizedTables(frames)
        add_value_tables(tables, planted_model(SPEC, last_season="2007-08"))
        assert tables.issues == []


class TestInABuild:
    def test_the_fixture_store_is_valued_by_the_shipped_model(
        self, built_readonly: Settings, first_build_report
    ) -> None:
        with Database(built_readonly.database_path) as database:
            warehouse = Warehouse(database)
            scores = warehouse.read(TABLE)
            regular = warehouse.read("player_seasons", {"season_type": "regular"})
        shipped = load_value_model(built_readonly.config_dir)
        played = scores[scores["impact"].notna()]
        assert set(zip(played["player_id"], played["season"], strict=True)) == set(
            zip(regular["player_id"], regular["season"], strict=True)
        )
        assert set(scores["model_version"]) == {shipped.version}
        # The players of 2025-26 are projected into the season that follows it.
        assert set(scores["season"]) == {"2025-26", "2026-27"}
        ahead = scores[scores["season"] == "2026-27"]
        assert ahead["impact"].isna().all() and ahead["projected_impact"].notna().all()
        assert not [
            issue for issue in first_build_report.data.tables.issues if issue.table == TABLE
        ]

    def test_the_value_checks_run_and_pass(self, first_build_report) -> None:
        checks = {check.check: check for check in first_build_report.data.checks}
        for name in (
            "impact_parts_add_up",
            "every_season_is_valued",
            "average_minute_has_no_impact",
        ):
            result = checks[f"{TABLE}.{name}"]
            assert result.passed and result.examined > 0, name
        assert checks[f"{TABLE}.player_id_exists"].passed
        assert TABLE in {contract.name for contract in CHECKED_TABLES}

    def test_a_project_without_a_model_still_builds(
        self, settings: Settings, repo_root: Path
    ) -> None:
        import shutil

        from tests.conftest import FIXTURE_RAW

        shutil.copytree(FIXTURE_RAW, settings.raw_dir)
        value_model_path(settings.config_dir).unlink()
        report = build_database(settings)
        assert report.loaded
        notes = [issue for issue in report.data.tables.notes if issue.table == TABLE]
        assert len(notes) == 1 and "no value model has been fitted" in notes[0].message
        with Database(settings.database_path) as database:
            assert Warehouse(database).row_counts()[TABLE] == 0

    def test_a_build_that_loses_its_model_is_not_refused(self, built_lab: Settings) -> None:
        # Refusing to empty a table protects against a broken raw store. A missing model
        # file is not that: the league tables are whole, and the note says what to do.
        value_model_path(built_lab.config_dir).unlink()
        report = build_database(built_lab)
        assert report.loaded and report.refused_because is None

    def test_check_store_takes_the_model_it_is_given(self, fixture_store: RawStore) -> None:
        without = check_store(fixture_store)
        assert without.tables[TABLE].empty
        scored = check_store(fixture_store, value_model=planted_model(ValueSpec()))
        assert set(scored.tables[TABLE]["model_version"]) == {"r1"}


class TestFitting:
    def test_the_first_fit_is_revision_one_and_recovers_what_was_planted(
        self, synthetic: Settings
    ) -> None:
        report = fit_value(synthetic, now=lambda: NOW)
        assert isinstance(report, FitReport)
        assert report.previous is None and report.changed
        model = report.model
        assert (model.revision, model.fitted_at, model.spec) == (1, NOW, SPEC)
        for term in model.terms:
            assert term.offense == pytest.approx(OFFENSE[term.key], abs=2e-5)
            assert term.defense == pytest.approx(DEFENSE[term.key], abs=2e-5)

    def test_fitting_writes_nothing(self, synthetic: Settings) -> None:
        fit_value(synthetic, now=lambda: NOW)
        assert not value_model_path(synthetic.config_dir).exists()

    def test_a_written_model_is_the_one_a_build_applies(self, synthetic: Settings) -> None:
        model = fit_value(synthetic, now=lambda: NOW).model
        path = write_value_model(synthetic, model)
        assert path == value_model_path(synthetic.config_dir)
        assert load_value_model(synthetic.config_dir) == model

    def test_fitting_again_on_the_same_data_changes_nothing_but_the_stamp(
        self, synthetic: Settings
    ) -> None:
        first = fit_value(synthetic, now=lambda: NOW).model
        write_value_model(synthetic, first)
        later = datetime(2026, 11, 1)
        again = fit_value(synthetic, now=lambda: later)
        assert again.previous == first
        assert (again.model.revision, again.model.fitted_at) == (2, later)
        assert not again.changed

    def test_a_changed_specification_is_a_changed_model(self, synthetic: Settings) -> None:
        write_value_model(synthetic, fit_value(synthetic, now=lambda: NOW).model)
        value_spec_path(synthetic.config_dir).write_text(
            SPEC_FILE + "ballast_minutes: 1500\n", encoding="utf-8"
        )
        again = fit_value(synthetic, now=lambda: NOW)
        assert again.changed and again.model.revision == 2
        assert again.model.spec.ballast_minutes == 1500

    def test_without_a_database_it_says_to_build_one(self, settings: Settings) -> None:
        with pytest.raises(ValueFitError, match="has not been built; run: fol refresh"):
            fit_value(settings)
        assert not settings.database_path.exists()

    def test_a_database_that_cannot_support_the_fit_says_what_is_missing(
        self, built_lab: Settings
    ) -> None:
        # The fixture store: one season of players for two teams.
        with pytest.raises(ValueFitError, match="tested from 2006-07 and needs at least 3"):
            fit_value(built_lab)

    def test_an_empty_database_is_reported_not_raised_from_storage(
        self, settings: Settings
    ) -> None:
        with Database(settings.database_path):
            pass  # creates the kept tables only: nothing has been built
        with pytest.raises(ValueFitError, match="has not been built"):
            fit_value(settings)


def test_the_synthetic_lab_reads_back_what_the_league_holds(synthetic, league) -> None:
    with Database(synthetic.database_path) as database:
        counts = Warehouse(database).row_counts()
        seasons = Warehouse(database).read("player_seasons")
    assert counts["team_seasons"] == 90 and counts["teams"] == 10
    assert counts["player_seasons"] == len(seasons) == 990
    pd.testing.assert_frame_equal(seasons, league.tables()["player_seasons"])


def test_a_fit_report_without_a_previous_model_is_a_change() -> None:
    model: ValueModel = planted_model(SPEC)
    assert FitReport(model, None).changed
    assert not FitReport(model.model_copy(update={"revision": 2}), model).changed
    other = model.model_copy(update={"replacement_level": -1.0})
    assert FitReport(other, model).changed
