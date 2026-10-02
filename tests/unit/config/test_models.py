"""The model files in ``configs/models``: a specification people edit, a fit the lab writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from front_office.config import (
    load_value_model,
    load_value_spec,
    save_value_model,
    value_model_path,
    value_spec_path,
)
from front_office.config.models import render_value_model
from front_office.config.settings import ConfigError
from front_office.domain.value_model import BacktestRow, ValueModel, ValueSpec
from front_office.modeling.value import TERM_KEYS
from tests.value_reference import planted_model


@pytest.fixture(scope="module")
def shipped(repo_root: Path) -> ValueModel:
    model = load_value_model(repo_root / "configs")
    assert model is not None, "the lab ships a fitted value model"
    return model


def with_backtest(model: ValueModel) -> ValueModel:
    rows = (
        BacktestRow(
            season="2006-07", team_id=101, predicted_offense=1.5, predicted_defense=-0.25,
            actual_offense=2.0, actual_defense=0.5,
        ),
        BacktestRow(
            season="2006-07", team_id=102, predicted_offense=-1.0, predicted_defense=0.0,
            actual_offense=-2.5, actual_defense=1.0,
        ),
    )  # fmt: skip
    return model.model_copy(update={"backtest": rows})


class TestSpecification:
    def test_the_files_live_in_configs_models(self, project: Path) -> None:
        configs = project / "configs"
        assert value_spec_path(configs) == configs / "models" / "player_value.yaml"
        assert value_model_path(configs) == configs / "models" / "player_value.json"

    def test_the_shipped_specification_is_the_documented_default(self, repo_root: Path) -> None:
        # Written out in full in the file so that every choice can be seen and changed.
        assert load_value_spec(repo_root / "configs") == ValueSpec()
        text = value_spec_path(repo_root / "configs").read_text(encoding="utf-8")
        for setting in ValueSpec.model_fields:
            assert f"\n{setting}:" in text, setting
        assert "fol value fit --write" in text

    def test_an_edited_specification_is_read(self, project: Path) -> None:
        path = value_spec_path(project / "configs")
        path.write_text("ballast_minutes: 500\nseason_weights: [1.0, 0.6]\n", encoding="utf-8")
        spec = load_value_spec(project / "configs")
        assert (spec.ballast_minutes, spec.season_weights) == (500, (1.0, 0.6))
        assert spec.first_test_season == "2006-07"  # everything else keeps its default

    @pytest.mark.parametrize(
        "document", ["ballast_minutes: -1\n", "ballast: 500\n", "season_weights: [0.5, 1.0]\n"]
    )
    def test_an_invalid_specification_names_the_file(self, project: Path, document: str) -> None:
        path = value_spec_path(project / "configs")
        path.write_text(document, encoding="utf-8")
        with pytest.raises(
            ConfigError, match="invalid value model specification in .*player_value"
        ):
            load_value_spec(project / "configs")

    def test_a_missing_specification_is_an_error(self, project: Path) -> None:
        value_spec_path(project / "configs").unlink()
        with pytest.raises(ConfigError, match="configuration file not found"):
            load_value_spec(project / "configs")


class TestFittedModel:
    def test_no_file_means_no_model(self, project: Path) -> None:
        value_model_path(project / "configs").unlink()
        assert load_value_model(project / "configs") is None

    def test_a_saved_model_is_read_back_exactly(self, project: Path) -> None:
        model = with_backtest(planted_model(ValueSpec(seed=9), revision=4))
        path = save_value_model(project / "configs", model)
        assert path == value_model_path(project / "configs")
        assert load_value_model(project / "configs") == model

    def test_saving_creates_the_directory(self, tmp_path: Path) -> None:
        path = save_value_model(tmp_path / "configs", planted_model(ValueSpec()))
        assert path.is_file() and path.parent.name == "models"

    def test_the_file_is_json_with_one_backtest_row_to_a_line(self) -> None:
        model = with_backtest(planted_model(ValueSpec()))
        text = render_value_model(model)
        assert text.endswith("\n}\n") and "\r" not in text
        document = json.loads(text)
        assert list(document)[-1] == "backtest" and len(document["backtest"]) == 2
        assert document["revision"] == 1 and document["spec"]["ballast_minutes"] == 750
        lines = text.splitlines()
        rows = [line for line in lines if line.startswith('  {"season"')]
        assert len(rows) == 2 and rows[0].endswith(",") and not rows[1].endswith(",")
        assert ' "revision": 1,' in lines

    def test_a_model_with_no_backtest_still_renders_as_json(self) -> None:
        document = json.loads(render_value_model(planted_model(ValueSpec())))
        assert document["backtest"] == []

    def test_a_file_this_version_cannot_read_says_how_to_replace_it(self, project: Path) -> None:
        path = value_model_path(project / "configs")
        path.write_text('{"revision": 1}', encoding="utf-8")
        with pytest.raises(ConfigError, match=r"player_value.json is not a fitted value model"):
            load_value_model(project / "configs")
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(ConfigError, match="fol value fit --write"):
            load_value_model(project / "configs")


class TestTheShippedModel:
    """The model in the repository: fitted on the real league, and worth applying."""

    def test_it_has_the_terms_this_version_computes(self, shipped: ValueModel) -> None:
        assert shipped.keys == TERM_KEYS

    def test_it_was_fitted_as_the_shipped_specification_says(
        self, shipped: ValueModel, repo_root: Path
    ) -> None:
        spec = load_value_spec(repo_root / "configs")
        assert shipped.spec == spec, "the specification changed: fit the model again"

    def test_it_was_tested_on_seasons_it_had_not_seen(self, shipped: ValueModel) -> None:
        tested = shipped.validation
        assert tested.first_test_season == shipped.spec.first_test_season
        assert tested.team_seasons == len(shipped.backtest) >= 500
        assert shipped.fitted_on.first_season < tested.first_test_season
        assert sum(score.teams for score in tested.by_season) == tested.team_seasons

    def test_it_beats_every_simpler_method_beyond_doubt(self, shipped: ValueModel) -> None:
        tested = shipped.validation
        assert len(tested.baselines) == 6
        for baseline in tested.baselines:
            assert tested.net.rmse < baseline.rmse, baseline.key
            assert baseline.high < 0, baseline.key

    def test_no_part_of_it_makes_the_prediction_worse(self, shipped: ValueModel) -> None:
        for ablation in shipped.validation.ablations:
            assert ablation.difference > -0.01, ablation.key

    def test_its_levels_make_basketball_sense(self, shipped: ValueModel) -> None:
        assert -3.5 < shipped.replacement_level < -1.0
        assert shipped.term("new_player").net < shipped.replacement_level + 1
        assert shipped.term("age").net < 0 and shipped.term("prior_minutes").net > 0
        for key in ("score_eff", "ast", "stl", "blk"):
            assert shipped.term(key).net_low > 0, key
        assert shipped.term("tov").net_high < 0
        minutes = shipped.availability
        assert minutes.rmse < minutes.baseline_rmse and minutes.high < 0
        assert 0.5 < minutes.coefficients["share_1"] < 1

    def test_the_file_is_exactly_what_saving_it_would_write(
        self, shipped: ValueModel, repo_root: Path
    ) -> None:
        on_disk = value_model_path(repo_root / "configs").read_text(encoding="utf-8")
        assert on_disk == render_value_model(shipped)
