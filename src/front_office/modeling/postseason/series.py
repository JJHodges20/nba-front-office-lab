"""One playoff series: a game model carried through the format it is played in.

The game model gives the home side's chance in one game from home court and the two
gaps between the sides. A series is the best of five or seven such games in a stated
home pattern, so its probability follows by enumerating how it can go - exactly, not by
simulation. Everything here works on scalars or on arrays of parameter draws alike.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from front_office.domain.postseason import home_pattern
from front_office.modeling.postseason.fitting import fit_logistic, logistic

GAME_COLUMNS = ("home", "net_rating_diff", "top_players_diff")
"""What the game model is fitted on: home court (0 on neutral ground), the gap in net
rating and the gap in top-player quality, each from the home side's point of view."""


def series_probability(
    p_home: np.ndarray | float, p_away: np.ndarray | float, pattern: Sequence[bool]
) -> np.ndarray | float:
    """The chance the home-court side wins a series, given its chance in a home game and
    in an away game and the home sequence of the format. The series ends when a side has
    won more than half of the scheduled games."""
    if len(pattern) % 2 == 0:
        raise ValueError("a series format must have an odd number of games")
    home = np.asarray(p_home, dtype="float64")
    away = np.asarray(p_away, dtype="float64")
    need = len(pattern) // 2 + 1
    states: dict[tuple[int, int], np.ndarray] = {(0, 0): np.ones_like(home)}
    total = np.zeros_like(home)
    for at_home in pattern:
        p = home if at_home else away
        following: dict[tuple[int, int], np.ndarray] = {}
        for (won, lost), mass in states.items():
            if won + 1 == need:
                total = total + mass * p
            else:
                key = (won + 1, lost)
                following[key] = following.get(key, 0.0) + mass * p
            if lost + 1 < need:
                key = (won, lost + 1)
                following[key] = following.get(key, 0.0) + mass * (1 - p)
        states = following
    return total if total.shape else float(total)


def game_probabilities(
    home_advantage: np.ndarray | float,
    net_slope: np.ndarray | float,
    top_slope: np.ndarray | float,
    net_diff: float,
    top_diff: float,
    *,
    neutral: bool,
) -> tuple[np.ndarray | float, np.ndarray | float]:
    """The home-court side's chance in one of its home games and in one of its away
    games. On neutral ground both are the same."""
    edge = np.asarray(net_slope) * net_diff + np.asarray(top_slope) * top_diff
    home = 0.0 if neutral else np.asarray(home_advantage)
    return logistic(home + edge), logistic(-home + edge)


def series_win_probability(
    home_advantage: np.ndarray | float,
    net_slope: np.ndarray | float,
    top_slope: np.ndarray | float,
    net_diff: float,
    top_diff: float,
    *,
    pattern: str,
    neutral: bool,
) -> np.ndarray | float:
    """The chance the home-court side wins the series, in the named format."""
    p_home, p_away = game_probabilities(
        home_advantage, net_slope, top_slope, net_diff, top_diff, neutral=neutral
    )
    return series_probability(p_home, p_away, home_pattern(pattern))


def fit_game_model(games: pd.DataFrame, columns: Sequence[str] = GAME_COLUMNS) -> np.ndarray:
    """Weights of the game model fitted to playoff games: one row per game from the home
    side's point of view, ``home_won`` the outcome. The first column is home court."""
    design = games[list(columns)].to_numpy(dtype="float64")
    return fit_logistic(design, games["home_won"].to_numpy(dtype="float64"))


def predict_series(
    weights: np.ndarray, series: pd.DataFrame, columns: Sequence[str] = GAME_COLUMNS
) -> np.ndarray:
    """Each series' probability for its home-court side under ``weights`` fitted on
    ``columns``, where the first column is home court and the rest are gaps; the series'
    ``pattern`` and ``neutral`` say how it is played."""
    gaps = series[list(columns[1:])].to_numpy(dtype="float64")
    edge = gaps @ np.asarray(weights[1:], dtype="float64")
    home = np.where(series["neutral"].to_numpy(dtype=bool), 0.0, float(weights[0]))
    p_home, p_away = logistic(home + edge), logistic(-home + edge)
    out = np.empty(len(series))
    for position, (name, ph, pa) in enumerate(zip(series["pattern"], p_home, p_away, strict=True)):
        out[position] = series_probability(float(ph), float(pa), home_pattern(name))
    return out
