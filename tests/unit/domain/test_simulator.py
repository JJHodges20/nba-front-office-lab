"""The simulator's specification and the file a fit writes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from front_office.config import load_simulator_spec
from front_office.domain.simulator import (
    Coverage,
    DevelopmentBand,
    FittedOn,
    MissedGames,
    Quantile,
    SimulatorModel,
    SimulatorSpec,
    WinsTest,
)


def model_from(bands: tuple[DevelopmentBand, ...]) -> SimulatorModel:
    return SimulatorModel(
        revision=1,
        fitted_at=datetime(2026, 10, 5, 12),
        spec=SimulatorSpec(),
        value_model_version="r1",
        postseason_model_version="p1",
        fitted_on=FittedOn(
            first_season="2000-01", last_season="2013-14", team_seasons=1, games=1, player_seasons=1
        ),
        value_error=3.0,
        season_noise=1.5,
        strength_error=2.6,
        noise_by_era=(),
        wins_season="2013-14",
        wins_per_point=2.4,
        wins_residual=3.0,
        development=bands,
        missed=MissedGames(
            players=10,
            mean=0.1,
            quantiles=(Quantile(level=0.0, value=0.0), Quantile(level=1.0, value=0.5)),
        ),
        test=WinsTest(
            team_seasons=2,
            first_test_season="2006-07",
            last_test_season="2007-08",
            mae=5.0,
            rmse=6.0,
            baseline_rmse=12.0,
            coverage=(Coverage(level=0.8, cases=4, covered=3),),
        ),
    )


class TestSpecification:
    def test_the_shipped_specification_is_the_documented_default(self, repo_root: Path) -> None:
        assert load_simulator_spec(repo_root / "configs") == SimulatorSpec()
        text = (repo_root / "configs" / "models" / "simulator.yaml").read_text(encoding="utf-8")
        for setting in SimulatorSpec.model_fields:
            assert f"\n{setting}:" in text, setting
        assert "fol simulate fit --write" in text

    def test_the_fingerprint_changes_with_any_choice(self) -> None:
        base = SimulatorSpec()
        assert base.fingerprint == SimulatorSpec().fingerprint
        assert SimulatorSpec(noise_seasons=5).fingerprint != base.fingerprint
        assert SimulatorSpec(seed=3).fingerprint != base.fingerprint

    @pytest.mark.parametrize(
        "bad",
        [
            {"reliability_edges": (0.0, 0.5)},
            {"reliability_edges": (0.0, 0.6, 0.4, 1.0)},
            {"missed_quantiles": (0.0, 0.5)},
            {"missed_quantiles": (0.0, 0.5, 0.25, 1.0)},
            {"high_injury_quantile": 0.7},
            {"coverage_levels": (0.0, 0.5)},
            {"coverage_levels": ()},
            {"wins_interval": 0.4},
            {"noise_seasons": 0},
            {"nonsense": 1},
        ],
    )
    def test_an_impossible_specification_is_refused(self, bad: dict) -> None:
        with pytest.raises((ValidationError, ValueError)):
            SimulatorSpec(**bad)


class TestTheFittedPieces:
    def test_a_band_is_found_by_reliability_including_the_ends(self) -> None:
        bands = (
            DevelopmentBand(lower=0.0, upper=0.5, players=3, mean_miss=0.1, spread=2.0),
            DevelopmentBand(lower=0.5, upper=1.0, players=4, mean_miss=-0.2, spread=1.0),
        )
        model = model_from(bands)
        assert model.band(0.0) is bands[0] and model.band(0.49) is bands[0]
        assert model.band(0.5) is bands[1] and model.band(1.0) is bands[1]
        assert model.version == "s1"
        with pytest.raises(KeyError):
            model.band(1.5)

    def test_missed_games_and_coverage_are_read_by_level(self) -> None:
        model = model_from(())
        assert model.missed.at(1.0) == 0.5
        with pytest.raises(KeyError):
            model.missed.at(0.3)
        assert model.test.at(0.8).share == 0.75
        with pytest.raises(KeyError):
            model.test.at(0.5)
        assert Coverage(level=0.5, cases=0, covered=0).share == 0.0
