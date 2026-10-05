"""The simulator's files in ``configs/models``: a specification people edit, parameters the
lab measures - and the parameters the lab ships, measured on the real league."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from front_office.config import (
    load_simulator_model,
    load_simulator_spec,
    save_simulator_model,
    simulator_model_path,
    simulator_spec_path,
)
from front_office.config.settings import ConfigError
from front_office.domain.simulator import SimulatorModel


@pytest.fixture(scope="module")
def shipped(repo_root: Path) -> SimulatorModel:
    model = load_simulator_model(repo_root / "configs")
    assert model is not None, "the lab ships measured simulator parameters"
    return model


class TestTheFiles:
    def test_the_files_live_in_configs_models(self, project: Path) -> None:
        configs = project / "configs"
        assert simulator_spec_path(configs) == configs / "models" / "simulator.yaml"
        assert simulator_model_path(configs) == configs / "models" / "simulator.json"

    def test_an_edited_specification_is_read(self, project: Path) -> None:
        simulator_spec_path(project / "configs").write_text(
            "noise_seasons: 4\nsimulations: 500\n", encoding="utf-8"
        )
        spec = load_simulator_spec(project / "configs")
        assert (spec.noise_seasons, spec.simulations, spec.rotation_minutes) == (4, 500, 1000)

    @pytest.mark.parametrize(
        "document", ["noise_seasons: 0\n", "seasons: 3\n", "high_injury_quantile: 0.7\n"]
    )
    def test_an_invalid_specification_names_the_file(self, project: Path, document: str) -> None:
        simulator_spec_path(project / "configs").write_text(document, encoding="utf-8")
        with pytest.raises(ConfigError, match="invalid simulator specification in .*simulator"):
            load_simulator_spec(project / "configs")

    def test_no_file_means_no_parameters(self, project: Path) -> None:
        simulator_model_path(project / "configs").unlink()
        assert load_simulator_model(project / "configs") is None

    def test_saved_parameters_are_read_back_exactly(
        self, project: Path, shipped: SimulatorModel
    ) -> None:
        changed = shipped.model_copy(update={"revision": 7})
        path = save_simulator_model(project / "configs", changed)
        assert path == simulator_model_path(project / "configs")
        assert load_simulator_model(project / "configs") == changed
        assert path.read_text(encoding="utf-8").endswith("\n}\n")

    def test_a_file_this_version_cannot_read_says_how_to_replace_it(self, project: Path) -> None:
        path = simulator_model_path(project / "configs")
        path.write_text('{"revision": 1}', encoding="utf-8")
        with pytest.raises(ConfigError, match=r"simulator.json is not a simulator model"):
            load_simulator_model(project / "configs")
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(ConfigError, match="fol simulate fit --write"):
            load_simulator_model(project / "configs")
        with pytest.raises(ValidationError):
            SimulatorModel.model_validate({"revision": 1})


class TestTheShippedParameters:
    """What the lab ships: measured on the real league against the models it also ships."""

    def test_measured_as_the_shipped_specification_says_against_the_shipped_models(
        self, shipped: SimulatorModel, repo_root: Path
    ) -> None:
        assert shipped.spec == load_simulator_spec(repo_root / "configs"), (
            "the specification changed: measure again"
        )
        assert shipped.value_model_version == "r1" and shipped.postseason_model_version == "p1"
        assert shipped.fitted_on.first_season == "1996-97" and shipped.fitted_on.team_seasons >= 850

    def test_the_figures_make_basketball_sense(self, shipped: SimulatorModel) -> None:
        assert 2.5 < shipped.value_error < 3.5
        assert 1.0 < shipped.season_noise < 2.0 < shipped.strength_error < shipped.value_error
        assert 2.0 < shipped.wins_per_point < 2.8 and 2.0 < shipped.wins_residual < 4.5
        assert [item.key for item in shipped.noise_by_era][0] == "all"
        spreads = [band.spread for band in shipped.development]
        # The less the model knew a player, the further the projection has missed.
        assert spreads == sorted(spreads, reverse=True) and all(s > 0 for s in spreads)
        assert sum(band.players for band in shipped.development) > 10_000
        assert 0.05 < shipped.missed.mean < 0.25 and shipped.missed.players > 5000
        assert shipped.missed.at(0.0) == 0.0 and shipped.missed.at(1.0) <= 1.0

    def test_the_wins_it_draws_hold_up_out_of_sample(self, shipped: SimulatorModel) -> None:
        test = shipped.test
        assert test.team_seasons == 600 and test.first_test_season == "2006-07"
        assert test.mae < test.rmse < test.baseline_rmse
        for item in test.coverage:
            # The interval held the wins that happened about as often as it claims.
            assert abs(item.share - item.level) < 0.06, item
        assert [item.level for item in test.coverage] == [0.5, 0.8, 0.95]

    def test_the_file_is_exactly_what_saving_it_would_write(
        self, shipped: SimulatorModel, repo_root: Path
    ) -> None:
        on_disk = simulator_model_path(repo_root / "configs").read_text(encoding="utf-8")
        assert on_disk == shipped.model_dump_json(indent=1) + "\n"
