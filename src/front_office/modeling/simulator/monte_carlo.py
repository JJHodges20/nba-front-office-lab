"""Seasons drawn for a roster.

Each simulated season draws, for every player, how far their impact comes out from the
projection (by how well the value model knew them) and how many games they miss; adds
up the parts for the minutes drawn, the way the optimizer and the fit page do; draws
the team-level miss the value model's test leaves unexplained; adds a season's own
noise to get the rating the season shows; turns that into wins with the wins-per-point
figure and the residual wins carry; and reads the postseason model's season steps for
the chance of each stage. Nothing here is fitted: every parameter comes in as a value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from front_office.domain.postseason import Step
from front_office.domain.scenario import Availability, Development
from front_office.domain.simulator import SimulatorModel
from front_office.domain.stages import BRACKET_STAGE_KEYS
from front_office.modeling.postseason.fitting import logistic, percentile_interval
from front_office.modeling.postseason.hierarchy import step_weights

ON_COURT = 5
FULL_SEASON_GAMES = 82
EVEN_RECORD = FULL_SEASON_GAMES / 2
TOP_PLAYERS = 3
ROSTER_COLUMNS: tuple[str, ...] = (
    "projected_impact",
    "projected_share",
    "projection_reliability",
    "games_missed",
    "development",
    "share",
)
"""What :func:`simulate` reads of each player, indexed by ``player_id``: the value
model's projection and reliability (missing for a player it never saw), then the user's
assumptions - games missed, points of development, a share of minutes - each missing
where the preset or the projection stands."""


@dataclass(frozen=True, slots=True)
class Simulation:
    """What the seasons drawn for one roster came to, one entry per season."""

    strength: np.ndarray
    """The team's net rating relative to the league: what the roster is."""
    rating: np.ndarray
    """The net rating the season shows: strength plus a season's own noise."""
    wins: np.ndarray
    """Wins per 82, as the season gave them."""
    top_players: np.ndarray
    shares: np.ndarray
    """What the players' shares of the minutes add up to; five is a season."""
    chances: dict[str, np.ndarray]
    """Stage key -> the chance of the stage in each season, under the fitted steps."""
    intervals: dict[str, tuple[float, float]]
    """Stage key -> the interval the postseason model's resampled steps give the mean
    chance."""
    players: int
    projected: int
    """Players the value model has a projection for; the rest play at replacement level."""

    @property
    def seasons(self) -> int:
        return len(self.wins)

    def stage_probability(self, key: str) -> float:
        return float(self.chances[key].mean())


def expected_rating(roster: pd.DataFrame, replacement: float) -> float:
    """The sum of the parts without a draw: five slots of replacement level plus each
    projected player's projected impact above it for the projected share, scaled down
    where the shares add up to more than a season. What the optimizer maximises."""
    known = roster.dropna(subset=["projected_impact"])
    shares = known["share"].fillna(known["projected_share"]).to_numpy(dtype="float64")
    impacts = known["projected_impact"].to_numpy(dtype="float64")
    total = float(((impacts - replacement) * shares).sum())
    covered = float(shares.sum())
    scale = min(1.0, ON_COURT / covered) if covered > 0 else 1.0
    return ON_COURT * replacement + scale * total


def draw_missed(model: SimulatorModel, draws: np.ndarray) -> np.ndarray:
    """The share of a season missed, read off the measured distribution at uniform
    ``draws``: the inverse of the distribution's quantile function, interpolated."""
    levels = np.array([item.level for item in model.missed.quantiles])
    values = np.array([item.value for item in model.missed.quantiles])
    return np.interp(draws, levels, values)


def simulate(
    roster: pd.DataFrame,
    *,
    model: SimulatorModel,
    steps: Sequence[Step],
    replacement: float,
    availability: Availability = Availability.AS_PROJECTED,
    development: Development = Development.EXPECTED,
    simulations: int,
    seed: int = 0,
    intervals: bool = True,
) -> Simulation:
    """Draw ``simulations`` seasons for ``roster`` (:data:`ROSTER_COLUMNS`).

    ``steps`` are the postseason model's season steps and ``replacement`` the value
    model's replacement level. The same roster, model, steps and seed always give the
    same seasons. Without ``intervals`` the chances come without the interval the
    resampled steps give them, which is most of the work; a table that does not show
    the intervals leaves them out.
    """
    generator = np.random.default_rng(seed)
    count = int(simulations)
    known = roster["projected_impact"].notna().to_numpy()
    players = len(roster)
    impact0 = roster["projected_impact"].to_numpy(dtype="float64")
    impact0 = np.where(known, impact0, replacement)
    share0 = roster["share"].fillna(roster["projected_share"]).to_numpy(dtype="float64")
    share0 = np.where(known | roster["share"].notna().to_numpy(), np.nan_to_num(share0), 0.0)
    reliability = roster["projection_reliability"].fillna(0.0).to_numpy(dtype="float64")

    # How each player's impact moves: the band's typical miss and spread by how well the
    # player was known, shifted by the preset or by the user's own figure.
    bands = [model.band(float(min(max(value, 0.0), 1.0))) for value in reliability]
    spread = np.array([band.spread for band in bands]) * known
    shift = np.array([band.mean_miss for band in bands])
    if development is Development.OPTIMISTIC:
        shift = shift + spread
    elif development is Development.REGRESSION:
        shift = shift - spread
    own = roster["development"].to_numpy(dtype="float64")
    shift = np.where(np.isnan(own), shift, own) * known
    impacts = impact0[None, :] + shift[None, :] + generator.normal(size=(count, players)) * spread

    # How many games each player misses: the measured distribution, shifted so that its
    # mean sits where the preset or the user's figure puts it.
    typical = model.missed.mean
    if availability is Availability.HEALTHY:
        target = np.zeros(players)
    elif availability is Availability.HIGH_INJURY:
        target = np.full(players, model.missed.at(model.spec.high_injury_quantile))
    else:
        target = np.full(players, typical)
    asked = roster["games_missed"].to_numpy(dtype="float64") / FULL_SEASON_GAMES
    target = np.where(np.isnan(asked), target, asked)
    drawn = draw_missed(model, generator.random(size=(count, players)))
    missed = np.clip(drawn - typical + target[None, :], 0.0, 1.0)
    fixed = roster["share"].notna().to_numpy() | ~known
    missed = np.where(fixed[None, :], 0.0, missed)
    # A projected share already allows for the games rotation players typically miss.
    scale_up = 1.0 / (1.0 - typical) if typical < 1 else 1.0
    base_share = np.where(fixed, share0, share0 * scale_up)
    shares = base_share[None, :] * (1.0 - missed)

    # The parts added up for the minutes drawn, scaled down where they run over a season.
    covered = shares.sum(axis=1)
    scale = np.where(covered > ON_COURT, ON_COURT / np.where(covered > 0, covered, 1.0), 1.0)
    total = ((impacts - replacement) * shares).sum(axis=1)
    sum_of_parts = ON_COURT * replacement + scale * total
    # What the value model's test leaves unexplained once the players' own spread and a
    # season's noise are taken out: the rest of the miss on a team's strength.
    explained = float(((base_share * (1.0 - target)) ** 2 * spread**2).sum())
    team_error = float(np.sqrt(max(model.strength_error**2 - explained, 0.0)))
    strength = sum_of_parts + generator.normal(size=count) * team_error
    rating = strength + generator.normal(size=count) * model.season_noise
    wins = EVEN_RECORD + model.wins_per_point * rating
    wins = wins + generator.normal(size=count) * model.wins_residual
    wins = np.clip(wins, 0.0, FULL_SEASON_GAMES)

    # The three best players, as the season drew them, among those who play.
    playing = np.where(shares > 0, impacts, -np.inf)
    best = -np.sort(-playing, axis=1)[:, :TOP_PLAYERS]
    counted = np.isfinite(best).sum(axis=1)
    summed = np.where(np.isfinite(best), best, 0.0).sum(axis=1)
    # Nobody playing - an emptied roster - is five replacement players.
    top = np.where(counted > 0, summed / np.maximum(counted, 1), replacement)

    chances, stage_intervals = _postseason(steps, rating, top, intervals=intervals)
    return Simulation(
        strength=strength,
        rating=rating,
        wins=wins,
        top_players=top,
        shares=covered,
        chances=chances,
        intervals=stage_intervals,
        players=players,
        projected=int(known.sum()),
    )


def _postseason(
    steps: Sequence[Step], rating: np.ndarray, top: np.ndarray, *, intervals: bool = True
) -> tuple[dict[str, np.ndarray], dict[str, tuple[float, float]]]:
    """The season model's chance of each stage in every season drawn, under the fitted
    steps; and the interval the resampled steps give the mean chance, or an unknown
    interval when none is asked for."""
    design = np.column_stack([np.ones(len(rating)), rating, top])  # (seasons, 3)
    fitted = step_weights(steps)  # (stages, 3)
    chance = np.cumprod(logistic(design @ fitted.T), axis=1)  # (seasons, stages)
    chances = {key: chance[:, position] for position, key in enumerate(BRACKET_STAGE_KEYS)}
    if not intervals:
        return chances, {key: (np.nan, np.nan) for key in BRACKET_STAGE_KEYS}
    draws = step_weights(steps, draws=True)  # (draws, stages, 3)
    means = np.empty((len(draws), len(BRACKET_STAGE_KEYS)))
    for number, weights in enumerate(draws):
        means[number] = np.cumprod(logistic(design @ weights.T), axis=1).mean(axis=0)
    intervals = {}
    for position, key in enumerate(BRACKET_STAGE_KEYS):
        intervals[key] = percentile_interval(means[:, position], 0.95)
    return chances, intervals


def summarise_wins(wins: np.ndarray) -> pd.DataFrame:
    """How often each win total came up: ``wins`` and ``share``, for a chart."""
    totals = np.clip(np.rint(wins), 0, FULL_SEASON_GAMES).astype(int)
    counts = np.bincount(totals, minlength=FULL_SEASON_GAMES + 1)
    return pd.DataFrame(
        {"wins": np.arange(FULL_SEASON_GAMES + 1), "share": counts / max(len(wins), 1)}
    )


def interval(values: np.ndarray, confidence: float) -> tuple[float, float]:
    return percentile_interval(values, confidence)


def stage_frame(simulation: Simulation, labels: Mapping[str, str]) -> pd.DataFrame:
    """Each stage's chance and interval as a table: ``key``, ``label``, ``probability``,
    ``low``, ``high``."""
    rows = []
    for key in BRACKET_STAGE_KEYS:
        low, high = simulation.intervals[key]
        rows.append(
            {
                "key": key,
                "label": labels[key],
                "probability": simulation.stage_probability(key),
                "low": low,
                "high": high,
            }
        )
    return pd.DataFrame(rows, columns=["key", "label", "probability", "low", "high"])
