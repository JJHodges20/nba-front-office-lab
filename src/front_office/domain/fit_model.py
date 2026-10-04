"""The roster fit evidence: whether fit measures explain what the sum of the parts misses.

The value model predicts a team's rating from its players, each taken alone, and its test
records what every prediction missed. Fit would show in those misses, if it shows
anywhere. The evidence here is the outcome of asking each measure, and then all of them
together, whether they explain the misses on seasons they had not seen - with intervals
from resampling seasons, and a plain answer to whether anything is usable.

Like the value model, the evidence is a file written on request (``fol fit test
--write``) and read by the services, never computed inside a page.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FitSpec(_Frozen):
    """How the evidence is gathered: the choices made before looking."""

    first_test_season: str = "2009-10"
    """First season the fit measures are tested on. The value model's own test begins in
    2006-07, and the fit test needs a few seasons of its misses to learn from first."""
    min_training_seasons: PositiveInt = 3
    resamples: PositiveInt = 2000
    seed: int = 0
    confidence: float = Field(default=0.95, gt=0.5, lt=1)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]


class Interval(_Frozen):
    """A difference in root mean squared error with its interval: negative means the
    method it belongs to misses by less."""

    difference: float
    low: float
    high: float

    @property
    def is_clear(self) -> bool:
        """Whether the interval keeps clear of zero, on the side that helps."""
        return self.high < 0


class MeasureEvidence(_Frozen):
    """One measure, on its own, beside the sum of the parts."""

    key: str
    name: str
    area: str
    teams: int
    """Team-seasons the measure was known for."""
    coefficient: float
    """Points of net rating per standard deviation of the measure, fitted on every season."""
    coefficient_low: float
    coefficient_high: float
    rmse: float
    """Out-of-sample error of the sum of the parts corrected by this measure alone."""
    change: Interval
    """That error less the sum of the parts' own."""

    @property
    def is_distinguishable(self) -> bool:
        return self.change.is_clear


class Term(_Frozen):
    """One measure's weight in the combined correction, per standard deviation."""

    key: str
    coefficient: float
    low: float
    high: float
    mean: float
    scale: float
    """The measure is standardised with these before the coefficient applies."""


class AreaEvidence(_Frozen):
    """The combined correction fitted again without one area's measures."""

    key: str
    label: str
    rmse: float
    change: Interval
    """Error without the area, less the error with everything: positive means missed."""


class CombinedEvidence(_Frozen):
    """Every measure together: the correction that would be applied, if any is."""

    rmse: float
    change: Interval
    intercept: float
    terms: tuple[Term, ...]
    ablations: tuple[AreaEvidence, ...]

    @property
    def is_usable(self) -> bool:
        """Whether applying the correction leaves the sum of the parts missing by clearly
        less. Nothing is applied to a roster otherwise."""
        return self.change.is_clear


class FitEvidence(_Frozen):
    revision: PositiveInt
    fitted_at: datetime
    spec: FitSpec
    value_model_version: str
    """The value model whose test supplied the misses."""
    archetype_version: str
    first_test_season: str
    last_test_season: str
    team_seasons: int
    baseline_rmse: float
    """What the sum of the parts missed by, on the team-seasons tested."""
    tested: tuple[str, ...]
    """The measures put to the test, in the order they are reported."""
    measures: tuple[MeasureEvidence, ...]
    combined: CombinedEvidence

    @property
    def version(self) -> str:
        return f"f{self.revision}"

    def measure(self, key: str) -> MeasureEvidence:
        for item in self.measures:
            if item.key == key:
                return item
        raise KeyError(f"no evidence on a measure named {key!r}")

    @property
    def distinguishable(self) -> tuple[MeasureEvidence, ...]:
        return tuple(item for item in self.measures if item.is_distinguishable)
