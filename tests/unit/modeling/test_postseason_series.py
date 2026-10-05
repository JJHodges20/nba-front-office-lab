"""One playoff series from a game model: enumerated exactly, checked against a reference that
walks every way a series can go."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.postseason import home_pattern
from front_office.modeling.postseason import (
    GAME_COLUMNS,
    fit_game_model,
    game_probabilities,
    predict_series,
    series_probability,
    series_win_probability,
)
from front_office.modeling.postseason.fitting import logistic
from tests import postseason_reference as reference

PATTERNS = ("2-2-1-1-1", "2-3-2", "2-2-1", "1-1-1")


class TestSeriesProbability:
    @pytest.mark.parametrize("name", PATTERNS)
    @pytest.mark.parametrize(
        ("p_home", "p_away"),
        [(0.5, 0.5), (0.7, 0.4), (0.9, 0.8), (0.3, 0.1), (1.0, 1.0), (0.0, 0.0)],
    )
    def test_matches_walking_every_way_the_series_can_go(
        self, name: str, p_home: float, p_away: float
    ) -> None:
        pattern = home_pattern(name)
        assert series_probability(p_home, p_away, pattern) == pytest.approx(
            reference.series_probability(p_home, p_away, pattern), abs=1e-12
        )

    def test_even_sides_split_a_series_evenly_whatever_the_format(self) -> None:
        for name in PATTERNS:
            assert series_probability(0.5, 0.5, home_pattern(name)) == pytest.approx(0.5)

    def test_the_other_side_has_the_complementary_chance(self) -> None:
        pattern = home_pattern("2-2-1-1-1")
        mirrored = tuple(not at_home for at_home in pattern)
        mine = series_probability(0.7, 0.4, pattern)
        theirs = series_probability(1 - 0.4, 1 - 0.7, mirrored)
        assert mine + theirs == pytest.approx(1.0)

    def test_hosting_the_odd_game_helps_only_when_home_games_are_easier(self) -> None:
        pattern = home_pattern("2-2-1-1-1")
        mirrored = tuple(not at_home for at_home in pattern)
        assert series_probability(0.6, 0.6, pattern) == pytest.approx(
            series_probability(0.6, 0.6, mirrored)
        )
        assert series_probability(0.65, 0.45, pattern) > series_probability(0.65, 0.45, mirrored)

    def test_an_even_number_of_games_is_refused(self) -> None:
        with pytest.raises(ValueError, match="odd"):
            series_probability(0.5, 0.5, (True, False))

    def test_arrays_of_draws_come_back_elementwise(self) -> None:
        p_home = np.array([0.5, 0.7, 0.9])
        p_away = np.array([0.5, 0.4, 0.8])
        pattern = home_pattern("2-2-1-1-1")
        out = series_probability(p_home, p_away, pattern)
        assert isinstance(out, np.ndarray) and out.shape == (3,)
        assert out == pytest.approx(
            [series_probability(h, a, pattern) for h, a in zip(p_home, p_away, strict=True)]
        )


class TestGameModel:
    def test_home_and_away_chances_from_the_parameters(self) -> None:
        home, away = game_probabilities(0.5, 0.1, 0.2, 3.0, 1.0, neutral=False)
        edge = 0.1 * 3.0 + 0.2 * 1.0
        assert home == pytest.approx(logistic(0.5 + edge))
        assert away == pytest.approx(logistic(-0.5 + edge))
        both = game_probabilities(0.5, 0.1, 0.2, 3.0, 1.0, neutral=True)
        assert both[0] == both[1] == pytest.approx(logistic(edge))

    def test_a_series_carries_the_game_model_through_its_format(self) -> None:
        p_home, p_away = game_probabilities(0.4, 0.1, 0.3, 2.0, -1.0, neutral=False)
        assert series_win_probability(
            0.4, 0.1, 0.3, 2.0, -1.0, pattern="2-3-2", neutral=False
        ) == pytest.approx(series_probability(p_home, p_away, home_pattern("2-3-2")))

    def test_fitting_recovers_a_planted_game_model(self) -> None:
        generator = np.random.default_rng(1)
        count = 20000
        games = pd.DataFrame(
            {
                "home": generator.integers(0, 2, count).astype(float),
                "net_rating_diff": generator.normal(0, 5, count),
                "top_players_diff": generator.normal(0, 2, count),
            }
        )
        z = 0.5 * games["home"] + 0.09 * games["net_rating_diff"] + 0.25 * games["top_players_diff"]
        games["home_won"] = (generator.random(count) < logistic(z.to_numpy())).astype(float)
        assert fit_game_model(games, GAME_COLUMNS) == pytest.approx([0.5, 0.09, 0.25], abs=0.03)

    def test_predicting_series_is_the_series_chance_row_by_row(self) -> None:
        weights = np.array([0.5, 0.09, 0.25])
        series = pd.DataFrame(
            {
                "net_rating_diff": [3.0, -2.0, 0.0],
                "top_players_diff": [1.0, 0.5, -1.0],
                "pattern": ["2-2-1-1-1", "2-2-1", "2-3-2"],
                "neutral": [False, False, True],
            }
        )
        expected = [
            series_win_probability(0.5, 0.09, 0.25, net, top, pattern=name, neutral=neutral)
            for net, top, name, neutral in series.itertuples(index=False)
        ]
        assert predict_series(weights, series, GAME_COLUMNS) == pytest.approx(expected)
        assert expected[2] < 0.5 < expected[0]
