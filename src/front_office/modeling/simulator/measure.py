"""The few things the simulator measures for itself, each from the lab's own tables.

Nothing here is fitted to an outcome: these are standard deviations and quantiles of
what has happened, which the Monte Carlo draws from. Each takes plain frames and says
what it needs of them.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from front_office.domain.eras import Era
from front_office.domain.seasons import SeasonType
from front_office.domain.simulator import DevelopmentBand, EraNoise, MissedGames, Quantile

REGULAR = SeasonType.REGULAR.value
FULL_SEASON_GAMES = 82
EVEN_RECORD = FULL_SEASON_GAMES / 2
PER_HUNDRED = 100.0
DECIMALS = 4


def rounded(value: float) -> float:
    return round(float(value), DECIMALS) + 0.0


def season_noise(team_games: pd.DataFrame, team_seasons: pd.DataFrame) -> pd.DataFrame:
    """How far each team-season's net rating strayed from the team's strength, from the
    spread of its regular-season game margins: one row per team-season with ``season``,
    ``team_id``, ``games`` and ``noise`` (per 100 possessions).

    A team's games are a sample of its strength: the standard error of the mean margin
    is how far the season's rating could sit from the strength behind it.
    """
    games = team_games[(team_games["season_type"] == REGULAR) & team_games["won"].notna()]
    margins = games.assign(
        margin=games["pts"].astype("float64") - games["opp_pts"].astype("float64")
    )
    spread = margins.groupby(["season", "team_id"])["margin"].agg(["std", "size"])
    spread = spread.rename(columns={"std": "sd", "size": "games"})
    pace = team_seasons.set_index(["season", "team_id"])[["possessions", "games_played"]]
    joined = spread.join(pace, how="inner")
    per_game = joined["possessions"].astype("float64") / joined["games_played"].where(
        joined["games_played"] > 0
    )
    noise = joined["sd"] / np.sqrt(joined["games"]) * PER_HUNDRED / per_game
    frame = pd.DataFrame(
        {"games": joined["games"].astype("int64"), "noise": noise.astype("float64")}
    )
    frame = frame[frame["games"] > 1].dropna(subset=["noise"]).reset_index()
    frame["season"] = frame["season"].astype(str)
    return frame.sort_values(["season", "team_id"]).reset_index(drop=True)


def era_noise(noise: pd.DataFrame, eras: Sequence[Era]) -> tuple[EraNoise, ...]:
    """The season noise averaged over each era that covers a season on record."""
    on_record = sorted(set(noise["season"]))
    out = []
    for era in eras:
        covered = era.seasons(on_record)
        inside = noise["season"].isin(covered)
        if not covered or not inside.any():
            continue
        out.append(
            EraNoise(
                key=era.key,
                label=era.name,
                first_season=covered[0],
                last_season=covered[-1],
                team_seasons=int(inside.sum()),
                noise=rounded(noise.loc[inside, "noise"].mean()),
            )
        )
    return tuple(out)


def recent(seasons: Sequence[str], count: int) -> list[str]:
    """The most recent ``count`` of the seasons, oldest first."""
    return sorted(set(seasons))[-count:]


def wins_residual(
    team_seasons: pd.DataFrame, slopes: pd.Series, seasons: Sequence[str]
) -> tuple[float, int]:
    """How far wins per 82 have strayed from what a season's net rating gives: the
    standard deviation, over the team-seasons of ``seasons``, of wins less an even record
    less the season's wins-per-point times the rating; and how many team-seasons."""
    played = team_seasons[
        team_seasons["season"].isin(list(seasons)) & (team_seasons["games_played"] > 0)
    ]
    played = played[played["season"].isin(slopes.index)]
    decided = (played["wins"] + played["losses"]).astype("float64")
    wins = FULL_SEASON_GAMES * played["wins"].astype("float64") / decided
    expected = EVEN_RECORD + played["season"].map(slopes).astype("float64") * played[
        "net_rating"
    ].astype("float64")
    residual = (wins - expected).dropna()
    if len(residual) < 2:
        return 0.0, int(len(residual))
    return rounded(residual.std(ddof=0)), int(len(residual))


def development_bands(scores: pd.DataFrame, edges: Sequence[float]) -> tuple[DevelopmentBand, ...]:
    """How far projections have missed, by how well the value model knew the player.

    ``scores`` is ``player_value_scores``; a row counts when it has both what the season
    showed and what was projected going in, and the miss is weighted by the share of
    minutes the player went on to play, so that the players a team leans on count most.
    """
    rows = scores.dropna(subset=["impact", "projected_impact"])
    rows = rows[rows["minutes_share"].fillna(0) > 0]
    miss = (rows["impact"] - rows["projected_impact"]).to_numpy(dtype="float64")
    weight = rows["minutes_share"].to_numpy(dtype="float64")
    # A player the model had no history for is the least known of all.
    reliability = rows["projection_reliability"].fillna(0.0).to_numpy(dtype="float64")
    out = []
    for lower, upper in zip(edges, edges[1:], strict=False):
        inside = (reliability >= lower) & (
            (reliability < upper) if upper < 1 else (reliability <= upper)
        )
        if inside.sum() < 2:
            out.append(
                DevelopmentBand(
                    lower=lower, upper=upper, players=int(inside.sum()), mean_miss=0.0, spread=0.0
                )
            )
            continue
        w = weight[inside]
        mean = float(np.average(miss[inside], weights=w))
        spread = float(np.sqrt(np.average((miss[inside] - mean) ** 2, weights=w)))
        out.append(
            DevelopmentBand(
                lower=float(lower),
                upper=float(upper),
                players=int(inside.sum()),
                mean_miss=rounded(mean),
                spread=rounded(spread),
            )
        )
    return tuple(out)


def missed_games(
    player_seasons: pd.DataFrame,
    team_seasons: pd.DataFrame,
    *,
    rotation_minutes: int,
    quantiles: Sequence[float],
) -> MissedGames:
    """The share of the season that rotation players missed: a player's games less their
    team's, among players with at least ``rotation_minutes`` in a regular season."""
    lines = player_seasons[player_seasons["season_type"] == REGULAR]
    lines = lines[lines["minutes"].astype("float64") >= rotation_minutes]
    games = team_seasons.set_index(["season", "team_id"])["games_played"].astype("float64")
    team_games = games.reindex(
        pd.MultiIndex.from_arrays([lines["season"].astype(str), lines["team_id"].astype("int64")])
    ).to_numpy()
    played = lines["games_played"].to_numpy(dtype="float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        missed = 1.0 - played / team_games
    missed = np.clip(missed[np.isfinite(missed)], 0.0, 1.0)
    if len(missed) == 0:
        return MissedGames(
            players=0,
            mean=0.0,
            quantiles=tuple(Quantile(level=float(q), value=0.0) for q in quantiles),
        )
    return MissedGames(
        players=int(len(missed)),
        mean=rounded(missed.mean()),
        quantiles=tuple(
            Quantile(level=float(q), value=rounded(np.quantile(missed, q))) for q in quantiles
        ),
    )
