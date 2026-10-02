"""From points to wins.

A team that outscores its opponents by a point per 100 possessions wins about two and a
half more games in 82 than one that breaks even. "About" matters: the figure has
drifted down as scoring has risen, so it is fitted for each season on that season and
its neighbours rather than fixed.
"""

from __future__ import annotations

import pandas as pd

from front_office.modeling.value.features import start_years

FULL_SEASON_GAMES = 82
EVEN_RECORD = FULL_SEASON_GAMES / 2


def wins_per_net_point(team_seasons: pd.DataFrame, *, window: int) -> pd.Series:
    """Wins over 82 games that a point of net rating was worth, by season.

    For each season with games played, the slope of wins per 82 on net rating through
    an even record, fitted on that season and ``window`` seasons either side. Indexed
    by season label, oldest first.
    """
    played = team_seasons[team_seasons["games_played"] > 0]
    decided = (played["wins"] + played["losses"]).astype("float64")
    frame = pd.DataFrame(
        {
            "season": played["season"],
            "start": start_years(played["season"]),
            "net": played["net_rating"].astype("float64"),
            "wins": FULL_SEASON_GAMES * played["wins"].astype("float64") / decided - EVEN_RECORD,
        }
    ).dropna()
    slopes = {}
    for season, start in sorted(set(zip(frame["season"], frame["start"], strict=True))):
        near = frame[(frame["start"] - start).abs() <= window]
        spread = (near["net"] ** 2).sum()
        if spread > 0:
            slopes[season] = float((near["wins"] * near["net"]).sum() / spread)
    return pd.Series(slopes, dtype="float64").sort_index().rename("wins_per_net_point")
