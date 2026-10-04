"""The value model's outputs as metrics: what each is called, means and looks like.

One entry per column of ``player_value_scores`` that a screen shows. Everything a model
produced is marked ``modeled``; the two columns that are plain arithmetic on minutes are
``derived``.
"""

from __future__ import annotations

from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance
from front_office.domain.tables.value import BASELINE_PART, PART_PREFIX
from front_office.modeling.value.features import COMPONENTS

VALUE = "Value"
PARTS = "Value: where impact comes from"
PROJECTION = "Value: going into the season"

_MODELED, _DERIVED = Provenance.MODELED, Provenance.DERIVED
_SIGNED, _PCT = MetricFormat.SIGNED, MetricFormat.PERCENT

_PART_LABELS = {
    "efficiency": "EFF",
    "creation": "CRE",
    "shooting": "SPC",
    "rebounding": "REB",
    "ball_security": "TOV",
    "defensive_activity": "D-ACT",
    "on_court": "ON",
    "team_context": "TEAM",
}

_PER_100 = "Points per 100 possessions on the court."


def _part(key: str, label: str, name: str, description: str) -> MetricSpec:
    return MetricSpec(f"{PART_PREFIX}{key}", label, name, description, PARTS, _SIGNED, _MODELED)


VALUE_METRICS = MetricCatalog(
    (
        MetricSpec(
            "impact",
            "IMP",
            "Impact",
            "Estimated effect on a team's net rating while the player is on the court, "
            "against the league's average minute, from this season alone. The player's "
            f"own numbers are trusted in proportion to the minutes behind them. {_PER_100}",
            VALUE,
            _SIGNED,
            _MODELED,
        ),
        MetricSpec(
            "impact_offense",
            "O-IMP",
            "Offensive impact",
            f"The part of impact that is points added on offense. {_PER_100}",
            VALUE,
            _SIGNED,
            _MODELED,
        ),
        MetricSpec(
            "impact_defense",
            "D-IMP",
            "Defensive impact",
            f"The part of impact that is points saved on defense. {_PER_100}",
            VALUE,
            _SIGNED,
            _MODELED,
        ),
        MetricSpec(
            "wins_added",
            "WAR",
            "Wins above replacement",
            "Wins the season was worth over a replacement player in the same minutes: "
            "impact above replacement level, times the share of the team's minutes "
            "played, times the wins a point of net rating was worth that season.",
            VALUE,
            provenance=_MODELED,
        ),
        MetricSpec(
            "minutes_share",
            "MIN%",
            "Share of team minutes",
            "Minutes played over the team's game minutes, every team played for added "
            "up: 100% is every minute of every game.",
            VALUE,
            _PCT,
            _DERIVED,
            higher_is_better=None,
            decimals=0,
        ),
        MetricSpec(
            "reliability",
            "REL",
            "Reliability",
            "Share of the season's impact that rests on the player's own numbers. The "
            "rest is what the model assumes of any player used that many minutes a game.",
            VALUE,
            _PCT,
            _DERIVED,
            higher_is_better=None,
            decimals=0,
        ),
        *(
            _part(
                component.key,
                _PART_LABELS[component.key],
                f"Impact from {component.label[0].lower()}{component.label[1:]}",
                component.description,
            )
            for component in COMPONENTS
        ),
        _part(
            BASELINE_PART,
            "BASE",
            "Impact assumed",
            "The part of impact that is assumed rather than shown: the level given to the "
            "share of the estimate the minutes do not vouch for, less the constant that "
            "puts the league's average minute at zero.",
        ),
        MetricSpec(
            "projected_impact",
            "P-IMP",
            "Projected impact",
            "Impact expected going into the season, from up to three seasons before it "
            f"and the player's age. This is the estimate the model is tested on. {_PER_100}",
            PROJECTION,
            _SIGNED,
            _MODELED,
        ),
        MetricSpec(
            "projected_offense",
            "P-OFF",
            "Projected offensive impact",
            f"The offensive part of projected impact. {_PER_100}",
            PROJECTION,
            _SIGNED,
            _MODELED,
        ),
        MetricSpec(
            "projected_defense",
            "P-DEF",
            "Projected defensive impact",
            f"The defensive part of projected impact. {_PER_100}",
            PROJECTION,
            _SIGNED,
            _MODELED,
        ),
        MetricSpec(
            "projection_reliability",
            "P-REL",
            "Reliability of the projection",
            "Share of the projection that rests on the player's own earlier numbers. "
            "Missing for a player with no earlier season, who is given the level of a "
            "new player.",
            PROJECTION,
            _PCT,
            _DERIVED,
            higher_is_better=None,
            decimals=0,
        ),
        MetricSpec(
            "projected_share",
            "P-MIN%",
            "Projected share of team minutes",
            "Share of team minutes expected going into the season, from the last three "
            "seasons' shares and age. It allows for the chance of not playing at all, "
            "and knows nothing of injuries or depth charts.",
            PROJECTION,
            _PCT,
            _MODELED,
            higher_is_better=None,
            decimals=0,
        ),
        MetricSpec(
            "projected_wins",
            "P-WAR",
            "Projected wins above replacement",
            "Projected impact above replacement level, times the projected share of "
            "team minutes, times the wins a point of net rating is worth, over 82 games.",
            PROJECTION,
            provenance=_MODELED,
        ),
    )
)
"""Every value metric, in the order the table holds them."""

SEASON_KEYS: tuple[str, ...] = tuple(spec.key for spec in VALUE_METRICS.in_category(VALUE))
PART_KEYS: tuple[str, ...] = tuple(spec.key for spec in VALUE_METRICS.in_category(PARTS))
PROJECTION_KEYS: tuple[str, ...] = tuple(spec.key for spec in VALUE_METRICS.in_category(PROJECTION))
