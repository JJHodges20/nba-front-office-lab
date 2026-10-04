"""The fit measures as metrics: labels, formats and directions for every screen."""

from __future__ import annotations

from front_office.domain.fit import MEASURES, Area, Kind, Measure
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance

_FORMATS = {
    Kind.COUNT: MetricFormat.COUNT,
    Kind.SHARE: MetricFormat.PERCENT,
    Kind.RATE: MetricFormat.DECIMAL,
    Kind.SIGNED: MetricFormat.SIGNED,
    Kind.INCHES: MetricFormat.DECIMAL,
}


def _spec(item: Measure) -> MetricSpec:
    return MetricSpec(
        item.key,
        item.label,
        item.name,
        item.description,
        str(item.area),
        _FORMATS[item.kind],
        Provenance.MODELED,
        higher_is_better=item.higher_is_better,
        decimals=1,
    )


FIT_METRICS = MetricCatalog(tuple(_spec(item) for item in MEASURES))
AREAS: tuple[Area, ...] = tuple(Area)
