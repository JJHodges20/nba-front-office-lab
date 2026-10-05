"""The postseason model's quantities as metrics: labels and formats for every screen."""

from __future__ import annotations

from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance
from front_office.domain.stages import BRACKET_STAGES

CATEGORY = "Postseason"
TOP_PLAYERS = "top_players"
SERIES_PROBABILITY = "series_probability"


def probability_key(stage_key: str) -> str:
    """The metric key of a stage's estimated chance."""
    return f"p_{stage_key}"


POSTSEASON_METRICS = MetricCatalog(
    (
        MetricSpec(
            TOP_PLAYERS,
            "Top-3 IMP",
            "Top-player quality",
            "The mean impact, by the value model, of the three players with the highest "
            "impact who finished the regular season with the team: the quality of the "
            "players a playoff rotation leans on.",
            CATEGORY,
            MetricFormat.SIGNED,
            Provenance.MODELED,
            decimals=2,
        ),
        MetricSpec(
            SERIES_PROBABILITY,
            "P(series)",
            "Series probability",
            "The estimated chance that the home-court side wins the series, from the gap "
            "in net rating, the gap in top-player quality and home court, carried through "
            "the series format.",
            CATEGORY,
            MetricFormat.PERCENT,
            Provenance.MODELED,
            higher_is_better=None,
        ),
        *(
            MetricSpec(
                probability_key(stage.key),
                f"P({stage.short})",
                f"Chance: {stage.label[0].lower()}{stage.label[1:]}",
                f"The estimated chance that the team {stage.label[0].lower()}{stage.label[1:]}"
                f" - {stage.description[0].lower()}{stage.description[1:]} An estimate "
                "with an interval, never a guarantee.",
                CATEGORY,
                MetricFormat.PERCENT,
                Provenance.MODELED,
            )
            for stage in BRACKET_STAGES
        ),
    )
)
