"""How two metrics move together across a group of players or teams.

A correlation describes this sample. It says nothing about cause, and on a few dozen
rows it moves a good deal by chance; callers should show the sample size beside it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from front_office.analytics.formulas import NAN

MIN_SAMPLE = 3


@dataclass(frozen=True, slots=True)
class Relationship:
    """The association between two columns over the rows that have both."""

    x: str
    y: str
    sample: int
    """Rows with a value in both columns."""
    pearson: float
    """Linear correlation, -1 to 1. Missing when the sample is too small or one column is constant."""
    spearman: float
    """Rank correlation, -1 to 1: whether one rises with the other, linear or not."""


def relationship(frame: pd.DataFrame, x: str, y: str) -> Relationship:
    """Pearson and Spearman correlation of two columns of ``frame``."""
    pairs = pd.DataFrame({"x": frame[x], "y": frame[y]}).astype("float64").dropna()
    sample = len(pairs)
    if sample < MIN_SAMPLE or pairs["x"].nunique() < 2 or pairs["y"].nunique() < 2:
        return Relationship(x, y, sample, NAN, NAN)
    pearson = float(pairs["x"].corr(pairs["y"]))
    spearman = float(pairs["x"].rank().corr(pairs["y"].rank()))
    return Relationship(x, y, sample, pearson, spearman)
