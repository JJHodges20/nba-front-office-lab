"""Roster fit in the pipeline: every team profiled in a build, for reference."""

from __future__ import annotations

import math
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from front_office.config import (
    Settings,
    fit_evidence_path,
    load_archetypes,
    load_fit_evidence,
    load_settings,
    save_value_model,
    value_model_path,
)
from front_office.domain.archetypes import Archetype, ArchetypeSet
from front_office.domain.fit import MEASURE_KEYS
from front_office.domain.schema import validate_frame
from front_office.domain.tables.fit import TEAM_FIT_PROFILES
from front_office.pipelines.check import CHECKED_TABLES
from front_office.pipelines.fit import (
    TABLE,
    FitTestError,
    add_fit_tables,
    gather_fit_evidence,
    write_fit_evidence,
)
from front_office.pipelines.normalize import IssueSeverity, NormalizedTables
from front_office.pipelines.value import add_archetype_tables, add_value_tables
from front_office.storage import Database, Warehouse
from tests.synthetic_lab import league_frames
from tests.unit.pipelines.test_value import SPEC
from tests.value_reference import planted_league, planted_model


@pytest.fixture(scope="module")
def shipped(repo_root) -> ArchetypeSet:  # type: ignore[no-untyped-def]
    return load_archetypes(repo_root / "configs")


@pytest.fixture
def league_tables() -> NormalizedTables:
    frames = league_frames(planted_league(SPEC))
    for name in ("player_value_scores", "player_archetypes", TABLE):
        frames.pop(name, None)
    return NormalizedTables(frames)


class TestProfilingTeams:
    def test_every_team_season_is_profiled_and_stamped(
        self, league_tables: NormalizedTables, shipped: ArchetypeSet
    ) -> None:
        add_value_tables(league_tables, planted_model(SPEC))
        add_archetype_tables(league_tables, shipped)
        add_fit_tables(league_tables, shipped)
        fit = league_tables[TABLE]
        assert validate_frame(fit, TEAM_FIT_PROFILES) == []
        assert len(fit) == len(league_tables["team_seasons"])
        assert set(fit["archetype_version"]) == {"v1"} and set(fit["model_version"]) == {"r1"}
        assert fit["impact_sum"].notna().all() and fit["spacers"].notna().all()
        assert league_tables.issues == []

    def test_without_rules_the_table_is_empty_and_nothing_is_said(
        self, league_tables: NormalizedTables
    ) -> None:
        add_value_tables(league_tables, planted_model(SPEC))
        add_archetype_tables(league_tables, None)
        add_fit_tables(league_tables, None)
        assert league_tables[TABLE].empty
        assert list(league_tables[TABLE].columns) == list(TEAM_FIT_PROFILES.column_names)
        assert league_tables.issues == []

    def test_without_a_value_model_the_impacts_are_missing_and_the_rest_stands(
        self, league_tables: NormalizedTables, shipped: ArchetypeSet
    ) -> None:
        add_value_tables(league_tables, None)
        add_archetype_tables(league_tables, shipped)
        before = list(league_tables.issues)
        add_fit_tables(league_tables, shipped)
        fit = league_tables[TABLE]
        assert len(fit) == len(league_tables["team_seasons"])
        assert fit["model_version"].isna().all()
        for key in ("impact_sum", "offense_sum", "defense_sum", "bench_impact", "star_share"):
            assert fit[key].isna().all(), key
        assert fit["three_point_rate"].notna().all() and fit["spacers"].notna().all()
        assert league_tables.issues == before

    def test_rules_without_a_role_the_counts_name_are_noted(
        self, league_tables: NormalizedTables, shipped: ArchetypeSet
    ) -> None:
        kept = tuple(item for item in shipped if item.key != "rim_protector")
        fewer = ArchetypeSet(
            version=2, min_minutes=shipped.min_minutes, fills_at=shipped.fills_at, archetypes=kept
        )
        add_value_tables(league_tables, planted_model(SPEC))
        add_archetype_tables(league_tables, fewer)
        add_fit_tables(league_tables, fewer)
        fit = league_tables[TABLE]
        assert (fit["rim_protectors"] == 0).all() and fit["spacers"].sum() > 0
        (note,) = [issue for issue in league_tables.notes if issue.table == TABLE]
        assert note.severity is IssueSeverity.NOTE
        assert note.message.startswith("the fit measures count players filling rim_protector, and")
        assert set(fit["archetype_version"]) == {"v2"}

    def test_a_rule_set_of_other_roles_entirely(
        self, league_tables: NormalizedTables, shipped: ArchetypeSet
    ) -> None:
        other = ArchetypeSet(
            version=1,
            min_minutes=500,
            fills_at=67,
            archetypes=(
                Archetype(key="scorer", name="Scorer", description="Scores.", measures=("ts_pct",)),
            ),
        )
        add_value_tables(league_tables, planted_model(SPEC))
        add_archetype_tables(league_tables, other)
        add_fit_tables(league_tables, other)
        fit = league_tables[TABLE]
        counts = [
            key
            for key in MEASURE_KEYS
            if key.endswith(("creators", "spacers", "defenders", "wings", "protectors"))
        ]
        assert (fit[counts] == 0).all().all()
        (note,) = [issue for issue in league_tables.notes if issue.table == TABLE]
        assert "floor_spacer" in note.message and "secondary_creator" in note.message


class TestInABuild:
    def test_the_fixture_stores_teams_are_profiled(
        self, built_readonly: Settings, first_build_report
    ) -> None:
        with Database(built_readonly.database_path) as database:
            fit = Warehouse(database).read(TABLE).set_index("team_id")
        # Two teams' rosters are on record; the rest are fragments of players traded away.
        whole = fit[fit["players"] >= 10]
        assert len(whole) == 2 and len(fit) > 2
        assert whole["minutes_covered"].to_numpy() == pytest.approx(1.0, abs=0.01)
        assert whole["usage_sum"].to_numpy() == pytest.approx(1.0, abs=0.1)
        assert (whole["primary_creators"] >= 1).all() and (whole["creators"] >= 1).all()
        assert not math.isnan(whole["impact_sum"].iloc[0])
        checks = {check.check: check for check in first_build_report.data.checks}
        for name in ("usage_adds_up", "minutes_cover_the_season"):
            result = checks[f"{TABLE}.{name}"]
            assert result.passed and result.examined == 2, name
        assert TABLE in {contract.name for contract in CHECKED_TABLES}
        assert not [
            issue for issue in first_build_report.data.tables.issues if issue.table == TABLE
        ]


NOW = datetime(2026, 10, 4, 9, 0)


class TestGatheringEvidence:
    @pytest.fixture
    def home(self, fitted_home: Path, tmp_path: Path) -> Settings:
        target = tmp_path / "lab"
        shutil.copytree(fitted_home, target)
        return load_settings(target)

    def test_the_first_gathering_is_revision_one_and_writes_nothing(self, home: Settings) -> None:
        report = gather_fit_evidence(home, now=lambda: NOW)
        evidence = report.evidence
        assert (evidence.revision, report.previous, report.changed) == (1, None, True)
        assert evidence.fitted_at == NOW and evidence.version == "f1"
        assert evidence.spec.first_test_season == "2006-07" and evidence.spec.resamples == 100
        # Ten teams over the three seasons the quick specification can test.
        assert evidence.team_seasons == 30
        assert (evidence.first_test_season, evidence.last_test_season) == ("2006-07", "2008-09")
        assert (evidence.value_model_version, evidence.archetype_version) == ("r1", "v1")
        assert not fit_evidence_path(home.config_dir).exists()

    def test_written_evidence_is_read_back_and_gathering_again_changes_nothing(
        self, home: Settings
    ) -> None:
        first = gather_fit_evidence(home, now=lambda: NOW).evidence
        path = write_fit_evidence(home, first)
        assert path == fit_evidence_path(home.config_dir) and path.is_file()
        assert load_fit_evidence(home.config_dir) == first
        again = gather_fit_evidence(home, now=lambda: NOW)
        assert again.evidence.revision == 2 and again.previous == first
        assert not again.changed

    def test_without_a_value_model_it_says_what_to_run(self, home: Settings) -> None:
        value_model_path(home.config_dir).unlink()
        with pytest.raises(
            FitTestError, match="no value model has been fitted; run: fol value fit"
        ):
            gather_fit_evidence(home)

    def test_a_value_model_without_a_test_on_record_cannot_be_measured_beyond(
        self, home: Settings
    ) -> None:
        from tests.conftest import VALUE_SPEC
        from tests.value_reference import planted_model

        save_value_model(home.config_dir, planted_model(VALUE_SPEC))
        with pytest.raises(FitTestError, match="no test on record"):
            gather_fit_evidence(home)

    def test_without_a_database_it_says_to_build_one(self, settings: Settings) -> None:
        with pytest.raises(FitTestError, match="the database has not been built"):
            gather_fit_evidence(settings)
