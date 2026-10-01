"""The basketball formulas, each defined exactly once.

Every function here is pure arithmetic on totals: it accepts numbers or pandas series
and returns the same kind. A rate whose denominator is zero or missing is *missing*
(NaN), never zero and never infinite: a player who has taken no shots does not have a
0% shooting percentage, he has no shooting percentage.

Nothing else in the lab may re-derive these. A screen, a value model or an optimiser
that needs true shooting calls :func:`true_shooting_pct`.
"""

from __future__ import annotations

import pandas as pd

Numeric = float | int | pd.Series

FREE_THROW_POSSESSION_WEIGHT = 0.44
"""Share of free-throw attempts that end a possession.

Not every free throw uses a possession: and-ones, technicals and the first of two shots
do not. 0.44 is the long-standing league-wide estimate, used by the league itself.
"""

GAME_MINUTES = 48
STARTER_MINUTES = 36
NAN = float("nan")


def _number(value: Numeric | None) -> float | pd.Series:
    """The value as a float, or as a float series with missing values as NaN."""
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors="coerce").astype("float64")
    return NAN if value is None else float(value)


def safe_divide(numerator: Numeric | None, denominator: Numeric | None) -> float | pd.Series:
    """``numerator / denominator``, missing where the denominator is zero or missing."""
    top, bottom = _number(numerator), _number(denominator)
    if isinstance(bottom, pd.Series):
        return top / bottom.where(bottom != 0)
    if bottom == 0 or bottom != bottom:  # zero, or NaN (the only value unequal to itself)
        return top * NAN
    return top / bottom


def scoring_attempts(fga: Numeric, fta: Numeric) -> float | pd.Series:
    """Possessions a player or team used to try to score: FGA + 0.44 x FTA."""
    return _number(fga) + FREE_THROW_POSSESSION_WEIGHT * _number(fta)


def shooting_pct(made: Numeric, attempted: Numeric) -> float | pd.Series:
    """Makes divided by attempts: field goal, three-point or free-throw percentage."""
    return safe_divide(made, attempted)


def effective_fg_pct(fgm: Numeric, fg3m: Numeric, fga: Numeric) -> float | pd.Series:
    """Field goal percentage with a three counted as one and a half makes.

    (FGM + 0.5 x 3PM) / FGA. Puts shooters who take threes and shooters who do not on
    the same scale.
    """
    return safe_divide(_number(fgm) + 0.5 * _number(fg3m), fga)


def true_shooting_pct(pts: Numeric, fga: Numeric, fta: Numeric) -> float | pd.Series:
    """Points per scoring attempt, halved so that it reads like a shooting percentage.

    PTS / (2 x (FGA + 0.44 x FTA)). Accounts for threes and free throws together.
    """
    return safe_divide(pts, 2 * scoring_attempts(fga, fta))


def three_point_attempt_rate(fg3a: Numeric, fga: Numeric) -> float | pd.Series:
    """Share of field goal attempts taken from three: 3PA / FGA."""
    return safe_divide(fg3a, fga)


def free_throw_rate(fta: Numeric, fga: Numeric) -> float | pd.Series:
    """Free throw attempts per field goal attempt: FTA / FGA."""
    return safe_divide(fta, fga)


def turnover_pct(tov: Numeric, fga: Numeric, fta: Numeric) -> float | pd.Series:
    """Share of a player's or team's plays that end in a turnover.

    TOV / (FGA + 0.44 x FTA + TOV).
    """
    return safe_divide(tov, scoring_attempts(fga, fta) + _number(tov))


def assist_to_turnover(ast: Numeric, tov: Numeric) -> float | pd.Series:
    """Assists per turnover. Missing for a player with no turnovers."""
    return safe_divide(ast, tov)


def per_game(total: Numeric, games: Numeric) -> float | pd.Series:
    return safe_divide(total, games)


def per_36(total: Numeric, minutes: Numeric) -> float | pd.Series:
    """A total scaled to 36 minutes: roughly a starter's night."""
    return safe_divide(_number(total) * STARTER_MINUTES, minutes)


def per_100(total: Numeric, possessions: Numeric) -> float | pd.Series:
    """A total scaled to 100 possessions, which removes the effect of pace."""
    return safe_divide(_number(total) * 100, possessions)


def rating(points: Numeric, possessions: Numeric) -> float | pd.Series:
    """Points per 100 possessions: offensive rating for points scored, defensive for allowed."""
    return per_100(points, possessions)


def estimated_possessions(
    fga: Numeric, fta: Numeric, oreb: Numeric, tov: Numeric
) -> float | pd.Series:
    """Possessions estimated from a box score: FGA + 0.44 x FTA - OREB + TOV.

    An *estimate*. A possession ends with a made shot, a defensive rebound, a turnover
    or free throws, and an offensive rebound extends it. Use the league's counted
    possessions where they exist; this is for box scores that come without them, such
    as a single game or a span of games.
    """
    return scoring_attempts(fga, fta) - _number(oreb) + _number(tov)


def pace(possessions: Numeric, game_minutes: Numeric) -> float | pd.Series:
    """Possessions per 48 minutes of game time.

    ``game_minutes`` is clock time (48 per regulation game), not player-minutes.
    """
    return safe_divide(_number(possessions) * GAME_MINUTES, game_minutes)


def rebound_pct(rebounds: Numeric, opponent_rebounds_at_that_end: Numeric) -> float | pd.Series:
    """Share of the rebounds available at one end of the floor that a team secured.

    Offensive: OREB / (OREB + opponent DREB). Defensive: DREB / (DREB + opponent OREB).
    """
    return safe_divide(rebounds, _number(rebounds) + _number(opponent_rebounds_at_that_end))


def share(part: Numeric, whole: Numeric) -> float | pd.Series:
    """A part as a fraction of a whole: games started of games played, salary of the cap."""
    return safe_divide(part, whole)
