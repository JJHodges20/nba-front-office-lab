"""The postseason model's answers worked out the slow, obvious way, and a league to test it on.

The invented league (``tests.league``) plays its playoffs by a *planted* series model: a
home advantage and two slopes chosen here, applied game by game with a seeded random
draw. A test can therefore ask the lab's model to find those numbers again. Beside it
are reference computations that share no code with ``front_office.modeling.postseason``:
the chance of a series by enumerating how it can go, the chance of each round by
simulating a bracket many times, and a chain of conditional chances integrated over an
uncertain rating by a plain grid.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from math import exp, isnan

import numpy as np
import pandas as pd

from front_office.domain.seasons import Season
from front_office.domain.value_model import ValueModel, ValueSpec
from tests.league import SyntheticLeague
from tests.synthetic_lab import league_frames
from tests.value_reference import planted_league, planted_model

PLANTED = {"home_advantage": 0.45, "net_slope": 0.11, "top_slope": 0.3}
"""The series model the invented league's playoffs are played by."""
TOP_PLAYERS = 3
REGULAR = "regular"
ROUND_KEYS = ("won_a_round", "made_conference_finals", "made_finals", "won_championship")


def logistic(z: float) -> float:
    return 1.0 / (1.0 + exp(-z))


# --- the league ------------------------------------------------------------------------------


def team_strengths(frames: dict[str, pd.DataFrame], year: int) -> dict[int, tuple[float, float]]:
    """Each team's net rating and top-player quality in a season, read from the frames the
    way the model reads them: the mean impact of the three best players who finished the
    regular season with the team."""
    label = Season(year).label
    teams = frames["team_seasons"]
    teams = teams[teams["season"] == label]
    lines = frames["player_seasons"]
    lines = lines[(lines["season"] == label) & (lines["season_type"] == REGULAR)]
    scores = frames["player_value_scores"]
    impact = scores[scores["season"] == label].set_index("player_id")["impact"]
    strengths = {}
    for row in teams.itertuples(index=False):
        mine = lines.loc[lines["team_id"] == row.team_id, "player_id"]
        impacts = sorted(
            (float(impact[player]) for player in mine if player in impact.index),
            reverse=True,
        )
        impacts = [value for value in impacts if not isnan(value)]
        top = float(np.mean(impacts[:TOP_PLAYERS])) if impacts else float("nan")
        strengths[int(row.team_id)] = (float(row.net_rating), top)
    return strengths


def plant_postseasons(
    league: SyntheticLeague, frames: dict[str, pd.DataFrame], *, seed: int = 0, **parameters: float
) -> None:
    """Play every finished season's playoffs by the planted series model (or the
    ``parameters`` given), reading each team's strength from ``frames``."""
    chosen = {**PLANTED, **parameters}
    for year in sorted(league.ratings):
        if year in league.unfinished:
            continue
        league.plant_postseason(year, team_strengths(frames, year), seed=seed, **chosen)


def postseason_league(
    spec: ValueSpec,
    *,
    seed: int = 0,
    teams: int = 30,
    seasons: int = 14,
    noise: float = 1.0,
    **parameters: float,
) -> tuple[SyntheticLeague, ValueModel, dict[str, pd.DataFrame]]:
    """A league of invented players valued by the planted value model, whose playoffs are
    played by the planted series model: the league, the model, and the frames a build
    would hold."""
    league = planted_league(spec, noise=noise, seed=seed, teams=teams, seasons=seasons)
    model = planted_model(spec, replacement_level=-2.0)
    plant_postseasons(league, league_frames(league, model), seed=seed, **parameters)
    return league, model, league_frames(league, model)


# --- reference computations ----------------------------------------------------------------


def series_probability(p_home: float, p_away: float, pattern: Sequence[bool]) -> float:
    """The chance the home-court side wins the series, by walking every way it can go."""
    need = len(pattern) // 2 + 1

    def go(game: int, won: int, lost: int) -> float:
        if won == need:
            return 1.0
        if lost == need:
            return 0.0
        p = p_home if pattern[game] else p_away
        return p * go(game + 1, won + 1, lost) + (1 - p) * go(game + 1, won, lost + 1)

    return go(0, 0, 0)


def simulate_bracket(
    pairs: Sequence[Sequence[tuple[int, int]]],
    strength: dict[int, tuple[float, float]],
    holds_home: Callable[[int, int], bool],
    *,
    home_advantage: float,
    net_slope: float,
    top_slope: float,
    pattern: Sequence[bool],
    neutral: bool = False,
    sims: int,
    seed: int,
) -> dict[int, dict[str, float]]:
    """Play a sixteen-team bracket ``sims`` times and count how often each team reached
    each round. ``pairs`` is two conferences of four first-round pairs in slot order, the
    home-court side first; ``strength`` maps a team to its net rating and top-player
    quality; ``holds_home`` says who hosts a later-round series."""
    generator = np.random.default_rng(seed)
    need = len(pattern) // 2 + 1

    def play(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Winners of a series between ``a`` (home court) and ``b``, one sim per row."""
        net = np.array([strength[t][0] for t in a]) - np.array([strength[t][0] for t in b])
        top = np.array([strength[t][1] for t in a]) - np.array([strength[t][1] for t in b])
        edge = net_slope * net + top_slope * top
        won = np.zeros(len(a), dtype=int)
        lost = np.zeros(len(a), dtype=int)
        for at_home in pattern:
            alive = (won < need) & (lost < need)
            home = 0.0 if neutral else (home_advantage if at_home else -home_advantage)
            p = 1.0 / (1.0 + np.exp(-(home + edge)))
            a_won = generator.random(len(a)) < p
            won += alive & a_won
            lost += alive & ~a_won
        return np.where(won == need, a, b)

    def meet(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """A later-round series between whoever came through on each side."""
        host_is_x = np.array([holds_home(int(i), int(j)) for i, j in zip(x, y, strict=True)])
        a, b = np.where(host_is_x, x, y), np.where(host_is_x, y, x)
        return play(a, b)

    def tally(winners: np.ndarray, key: str) -> None:
        for team, count in zip(*np.unique(winners, return_counts=True), strict=True):
            reached[int(team)][key] += int(count)

    reached: dict[int, dict[str, int]] = {}
    for conference in pairs:
        for a, b in conference:
            for team in (a, b):
                reached[team] = dict.fromkeys(ROUND_KEYS, 0)
    finalists = []
    for conference in pairs:
        first = [play(np.full(sims, a), np.full(sims, b)) for a, b in conference]
        for winners in first:
            tally(winners, "won_a_round")
        semis = [meet(first[0], first[1]), meet(first[2], first[3])]
        for winners in semis:
            tally(winners, "made_conference_finals")
        champion = meet(semis[0], semis[1])
        tally(champion, "made_finals")
        finalists.append(champion)
    tally(meet(finalists[0], finalists[1]), "won_championship")
    return {team: {k: v / sims for k, v in counts.items()} for team, counts in reached.items()}


def chain_probabilities(
    weights: Sequence[Sequence[float]], net_rating: float, top_players: float
) -> list[float]:
    """A team's chance of each stage from conditional steps - intercept, net rating and
    top-player weights per step - multiplied up."""
    out, running = [], 1.0
    for intercept, net, top in weights:
        running *= logistic(intercept + net * net_rating + top * top_players)
        out.append(running)
    return out


def integrated_chain(
    weights: Sequence[Sequence[float]],
    net_rating: float,
    top_players: float,
    error: float,
    *,
    points: int = 4001,
    reach: float = 6.0,
) -> list[float]:
    """The same chances averaged over a normal distribution of the true net rating, by a
    plain grid: the reference for the model's quadrature."""
    grid = np.linspace(net_rating - reach * error, net_rating + reach * error, points)
    density = np.exp(-0.5 * ((grid - net_rating) / error) ** 2)
    density /= density.sum()
    totals = np.zeros(len(weights))
    for rating, weight in zip(grid, density, strict=True):
        totals += weight * np.array(chain_probabilities(weights, float(rating), top_players))
    return totals.tolist()
