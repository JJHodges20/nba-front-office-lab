"""The value model worked out the slow way: plain loops over the invented league.

Nothing here imports the modeling layer. It restates the model's definitions from the
ground up - rates per 100 possessions against the league, seasons pooled by minutes,
reliability, the assumed level for the unproven part, age - so that it can do two jobs:

* plant team ratings that follow the model exactly, for a test to recover; and
* stand as an independent answer for every number the vectorised code produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from front_office.domain.value_model import (
    Availability,
    FittedOn,
    SameSeason,
    Score,
    Term,
    Validation,
    ValueModel,
    ValueSpec,
)
from tests.league import LEAGUE_RATING, TEAM_MINUTES, SyntheticLeague, make_league

COUNTED = ("ast", "fta", "fg3a", "oreb", "dreb", "tov", "stl", "blk", "pf")
FEATURES = ("score_eff", "score_vol", *COUNTED, "rel_off", "rel_def", "team_off", "team_def")
LEVELS = ("prior_level", "prior_minutes", "age", "new_player")
TERMS = (*FEATURES, *LEVELS)
# The order the model itself declares its terms in.
MODEL_TERMS = (
    "score_eff", "score_vol", "ast", "fta", "fg3a", "oreb", "dreb", "tov", "stl", "blk", "pf",
    "rel_off", "rel_def", "team_off", "team_def", *LEVELS,
)  # fmt: skip
PARTS = {
    "efficiency": ("score_eff",),
    "creation": ("score_vol", "ast", "fta"),
    "shooting": ("fg3a",),
    "rebounding": ("oreb", "dreb"),
    "ball_security": ("tov",),
    "defensive_activity": ("stl", "blk", "pf"),
    "on_court": ("rel_off", "rel_def"),
    "team_context": ("team_off", "team_def"),
}

# Weights to plant: every term matters on at least one side, none is a round number
# that a bug could produce by accident.
OFFENSE = dict(zip(MODEL_TERMS, (
    0.52, 0.17, 0.29, -0.04, 0.18, 0.37, -0.06, -0.33, 0.09, 0.07, -0.07,
    0.06, 0.11, 0.09, 0.02, 0.71, 0.15, -0.07, -1.8,
), strict=True))  # fmt: skip
DEFENSE = dict(zip(MODEL_TERMS, (
    -0.02, -0.05, 0.13, 0.03, -0.05, -0.08, 0.12, -0.13, 0.58, 0.69, 0.03,
    0.13, 0.26, -0.02, 0.19, 0.23, 0.11, -0.01, -1.0,
), strict=True))  # fmt: skip


@dataclass
class Known:
    """What one season says of one player, or what earlier seasons say entering one."""

    features: dict[str, float]
    mpg_centred: float
    evidence: float
    """Minutes with something counted (one season), or weighted minutes (pooled)."""
    minutes: float
    age: float
    seasons: int = 1

    def reliability(self, spec: ValueSpec) -> float:
        return self.evidence / (self.evidence + spec.ballast_minutes)


def season_known(league: SyntheticLeague, year: int) -> dict[int, Known]:
    """Every player's features for one season, from the records."""
    lines = league.lines[year]
    counted = [line for line in lines if line.possessions]
    possessions = sum(line.possessions for line in counted)

    def league_rate(name: str) -> float:
        return 100 * sum(line.totals[name] for line in counted) / possessions

    def attempts(line) -> float:  # type: ignore[no-untyped-def]
        return line.totals["fga"] + 0.44 * line.totals["fta"]

    league_attempts = 100 * sum(attempts(line) for line in counted) / possessions
    points_per_attempt = league_rate("pts") / league_attempts
    all_minutes = sum(line.minutes for line in lines)
    mean_mpg = sum(line.minutes / line.games * line.minutes for line in lines) / all_minutes

    known = {}
    for line in lines:
        played = [stint for stint in league.stints[year] if stint.player_id == line.player_id]
        total = sum(stint.minutes for stint in played)
        team_off = sum(stint.minutes * league.ratings[year][stint.team_id][0] for stint in played)
        team_def = sum(stint.minutes * league.ratings[year][stint.team_id][1] for stint in played)
        team_off, team_def = team_off / total, team_def / total
        features = dict.fromkeys(FEATURES, 0.0)
        if line.possessions:
            per_100 = 100 / line.possessions
            features["score_eff"] = (
                line.totals["pts"] * per_100 - points_per_attempt * attempts(line) * per_100
            )
            features["score_vol"] = attempts(line) * per_100 - league_attempts
            for name in COUNTED:
                features[name] = line.totals[name] * per_100 - league_rate(name)
            features["team_off"], features["team_def"] = team_off, team_def
            features["rel_off"] = (line.off_rating - LEAGUE_RATING) - team_off
            features["rel_def"] = (LEAGUE_RATING - line.def_rating) - team_def
        known[line.player_id] = Known(
            features=features,
            mpg_centred=line.minutes / line.games - mean_mpg,
            evidence=line.minutes if line.possessions else 0.0,
            minutes=line.minutes,
            age=float(line.age),
        )
    return known


def entering(league: SyntheticLeague, year: int, spec: ValueSpec) -> dict[int, Known]:
    """What is known of each player entering ``year``: earlier seasons pooled by minutes."""
    gathered: dict[int, list[tuple[int, float, Known]]] = {}
    for lag, season_weight in enumerate(spec.season_weights, start=1):
        if year - lag not in league.ratings:
            continue
        for player, known in season_known(league, year - lag).items():
            if known.evidence > 0:
                gathered.setdefault(player, []).append((lag, season_weight * known.evidence, known))
    pooled = {}
    for player, seasons in gathered.items():
        weight = sum(share for _, share, _ in seasons)
        newest_lag, _, newest = min(seasons, key=lambda season: season[0])
        pooled[player] = Known(
            features={
                name: sum(share * known.features[name] for _, share, known in seasons) / weight
                for name in FEATURES
            },
            mpg_centred=sum(share * known.mpg_centred for _, share, known in seasons) / weight,
            evidence=weight,
            minutes=weight,
            age=newest.age + newest_lag,
            seasons=len(seasons),
        )
    return pooled


def terms(known: Known | None, spec: ValueSpec, *, aged: bool = True) -> dict[str, float]:
    """A player's terms: what the weights multiply. ``None`` is a player never seen."""
    if known is None:
        return {**dict.fromkeys(TERMS, 0.0), "new_player": 1.0}
    trust = known.reliability(spec)
    return {
        **{name: trust * value for name, value in known.features.items()},
        "prior_level": 1 - trust,
        "prior_minutes": (1 - trust) * known.mpg_centred,
        "age": known.age - spec.age_centre if aged else 0.0,
        "new_player": 0.0,
    }


def estimate(player_terms: dict[str, float], weights: dict[str, float]) -> float:
    return sum(weights[name] * value for name, value in player_terms.items())


def team_terms(league: SyntheticLeague, year: int, spec: ValueSpec) -> dict[int, dict[str, float]]:
    """Each team's row of the regression for ``year``: players' terms summed by share."""
    pooled = entering(league, year, spec)
    rows = {team: dict.fromkeys(TERMS, 0.0) for team in league.team_ids}
    for stint in league.stints[year]:
        share = stint.minutes / TEAM_MINUTES
        for name, value in terms(pooled.get(stint.player_id), spec).items():
            rows[stint.team_id][name] += share * value
    return rows


def planted_league(
    spec: ValueSpec,
    *,
    noise: float = 0.0,
    seed: int = 0,
    offense: dict[str, float] = OFFENSE,
    defense: dict[str, float] = DEFENSE,
    **shape: int,
) -> SyntheticLeague:
    """A league whose team ratings follow the model with the given weights.

    The first season has nothing before it, so its ratings are drawn at random; every
    later season is the model applied to the seasons before, plus ``noise``.
    """
    league = make_league(seed=seed, **shape)
    generator = np.random.default_rng([seed, 99])
    league.plant_at_random(league.years[0], seed=seed)
    for year in league.years[1:]:
        rows = team_terms(league, year, spec)
        league.plant(
            year,
            {
                team: (
                    estimate(rows[team], offense) + noise * float(generator.normal()),
                    estimate(rows[team], defense) + noise * float(generator.normal()),
                )
                for team in league.team_ids
            },
        )
    return league


def season_impacts(
    league: SyntheticLeague,
    year: int,
    spec: ValueSpec,
    offense: dict[str, float] = OFFENSE,
    defense: dict[str, float] = DEFENSE,
) -> dict[int, dict[str, float]]:
    """Every player's impact in one season, with its parts, centred on the average minute."""
    known = season_known(league, year)
    raw = {}
    for player, own in known.items():
        own_terms = terms(own, spec, aged=False)
        net = {name: offense[name] + defense[name] for name in TERMS}
        raw[player] = {
            "offense": estimate(own_terms, offense),
            "defense": estimate(own_terms, defense),
            **{
                part: sum(net[name] * own_terms[name] for name in names)
                for part, names in PARTS.items()
            },
            "baseline": sum(
                net[name] * own_terms[name] for name in ("prior_level", "prior_minutes")
            ),
        }
    minutes = sum(own.minutes for own in known.values())
    centre = {
        side: sum(known[player].minutes * raw[player][side] for player in raw) / minutes
        for side in ("offense", "defense")
    }
    impacts = {}
    for player, values in raw.items():
        offense_impact = values["offense"] - centre["offense"]
        defense_impact = values["defense"] - centre["defense"]
        impacts[player] = {
            **{part: values[part] for part in PARTS},
            "baseline": values["baseline"] - centre["offense"] - centre["defense"],
            "offense": offense_impact,
            "defense": defense_impact,
            "impact": offense_impact + defense_impact,
            "reliability": known[player].reliability(spec),
        }
    return impacts


AVAILABILITY = {
    "intercept": 0.02,
    "share_1": 0.7,
    "share_2": 0.1,
    "share_3": 0.03,
    "years_over_30": -0.008,
    "years_under_25": 0.025,
}


def planted_model(
    spec: ValueSpec,
    *,
    offense: dict[str, float] = OFFENSE,
    defense: dict[str, float] = DEFENSE,
    replacement_level: float = -2.0,
    revision: int = 1,
    last_season: str = "2008-09",
) -> ValueModel:
    """A fitted model with the given weights and no evidence worth the name."""
    none = Score(rmse=0.0, mae=0.0, r2=1.0)
    return ValueModel(
        revision=revision,
        fitted_at=datetime(2026, 10, 1, 12, 0),
        spec=spec,
        fitted_on=FittedOn(
            first_season="2000-01", last_season=last_season, team_seasons=80, player_seasons=880
        ),
        terms=tuple(
            Term(
                key=name,
                offense=offense[name],
                defense=defense[name],
                offense_low=offense[name] - 0.1,
                offense_high=offense[name] + 0.1,
                defense_low=defense[name] - 0.1,
                defense_high=defense[name] + 0.1,
                net_low=offense[name] + defense[name] - 0.2,
                net_high=offense[name] + defense[name] + 0.2,
            )
            for name in MODEL_TERMS
        ),
        replacement_level=replacement_level,
        availability=Availability(
            coefficients=AVAILABILITY,
            players=100,
            rmse=0.1,
            mae=0.08,
            baseline_rmse=0.12,
            baseline_mae=0.09,
            difference=-0.02,
            low=-0.03,
            high=-0.01,
        ),
        validation=Validation(
            first_test_season="2004-05",
            last_test_season=last_season,
            team_seasons=50,
            net=none,
            offense=none,
            defense=none,
            baselines=(),
            ablations=(),
            by_season=(),
            same_season=SameSeason(slope=1.0, correlation=1.0),
        ),
        backtest=(),
    )
