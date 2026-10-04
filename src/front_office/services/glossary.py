"""The metric glossary: every metric the lab shows, from the catalogs that define them."""

from __future__ import annotations

from front_office.analytics.benchmarks import RESEARCH_METRICS
from front_office.analytics.players import PLAYER_METRICS
from front_office.analytics.rosters import ROSTER_METRICS
from front_office.analytics.teams import TEAM_METRICS
from front_office.domain.glossary import render_metric_glossary
from front_office.domain.metrics import MetricCatalog
from front_office.modeling.value.catalog import VALUE_METRICS

METRIC_CATALOGS: dict[str, MetricCatalog] = {
    "Player metrics": PLAYER_METRICS,
    "Team metrics": TEAM_METRICS,
    "Roster indicators": ROSTER_METRICS,
    "Benchmark measures": RESEARCH_METRICS,
    "Player value": VALUE_METRICS,
}


def metric_glossary() -> str:
    """The glossary as Markdown, the content of ``docs/METRICS.md``."""
    return render_metric_glossary(METRIC_CATALOGS)
