"""What a win costs, read off the contracts on file.

Surplus value is what a player is worth less what the player is paid, and "worth" needs
a price. The lab does not bring one: it fits a straight line through the salaries and
the wins of the players whose contracts are on file - salary as the cost of a player
worth no wins, plus so much a win.

That makes surplus a statement about *these* contracts: a player with a surplus is paid
less than the players on file are paid for the same wins. With a few contracts on file
the line is rough, and it always says how many it rests on. Rookie-scale and maximum
contracts are capped by rule, not priced by a market, and the line knows nothing of that.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_CONTRACTS = 3
"""Fewer players than this cannot say anything about a slope."""

SURPLUS_COLUMNS = ("market_value", "surplus", "cost_per_win")


@dataclass(frozen=True, slots=True)
class Market:
    """The line through salary and wins."""

    contracts: int
    """Players it was fitted on."""
    replacement_cost: float
    """Salary of a player worth no wins over replacement."""
    price_per_win: float
    r2: float
    """Share of the differences in salary that wins account for."""

    def value(self, wins: pd.Series) -> pd.Series:
        """What the line pays for these wins. A player below replacement is worth the
        replacement cost: nobody is paid less for being worse than nobody."""
        return self.replacement_cost + self.price_per_win * wins.clip(lower=0)


def fit_market(salary: pd.Series, wins: pd.Series) -> Market | None:
    """Fit the line on the players who have both a salary and wins.

    ``None`` when there are too few of them, when they are all worth the same, or when
    the contracts on file do not pay more for more wins - in which case no price can be
    read off them.
    """
    both = pd.DataFrame({"salary": salary, "wins": wins}).dropna().astype("float64")
    worth = both["wins"].clip(lower=0)
    if len(both) < MIN_CONTRACTS or worth.nunique() < 2:
        return None
    centred = worth - worth.mean()
    price = float((centred * (both["salary"] - both["salary"].mean())).sum() / (centred**2).sum())
    if price <= 0:
        return None
    cost = float(both["salary"].mean() - price * worth.mean())
    residual = both["salary"] - (cost + price * worth)
    spread = ((both["salary"] - both["salary"].mean()) ** 2).sum()
    r2 = float(1 - (residual**2).sum() / spread) if spread > 0 else 0.0
    return Market(contracts=len(both), replacement_cost=cost, price_per_win=price, r2=r2)


def surplus(salary: pd.Series, wins: pd.Series, market: Market | None) -> pd.DataFrame:
    """Each player's worth at the market's price, and what is left after the salary.

    On ``salary``'s index: :data:`SURPLUS_COLUMNS`. ``cost_per_win`` is salary over
    wins, for players worth more than none; it needs no market. Without a market the
    other two columns are missing.
    """
    paid = salary.astype("float64")
    won = wins.astype("float64").reindex(paid.index)
    frame = pd.DataFrame(index=paid.index)
    frame["market_value"] = market.value(won) if market is not None else np.nan
    frame["surplus"] = frame["market_value"] - paid
    frame["cost_per_win"] = (paid / won.where(won > 0)).where(paid.notna())
    return frame[list(SURPLUS_COLUMNS)]
