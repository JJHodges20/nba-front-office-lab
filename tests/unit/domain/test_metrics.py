from __future__ import annotations

import pytest

from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance


def spec(key: str = "ts_pct", **kwargs: object) -> MetricSpec:
    arguments = {
        "label": "TS%",
        "name": "True shooting percentage",
        "description": "Points per scoring attempt.",
        "category": "Scoring",
    }
    arguments.update(kwargs)
    return MetricSpec(key, **arguments)  # type: ignore[arg-type]


class TestFormatting:
    @pytest.mark.parametrize(
        ("kwargs", "value", "shown"),
        [
            ({"format": MetricFormat.PERCENT}, 0.5881, "58.8%"),
            ({"format": MetricFormat.PERCENT, "decimals": 0}, 0.5881, "59%"),
            ({"format": MetricFormat.DECIMAL}, 21.75, "21.8"),
            ({"format": MetricFormat.DECIMAL, "decimals": 2}, 2.179, "2.18"),
            ({"format": MetricFormat.DECIMAL}, 1234.5, "1,234.5"),
            ({"format": MetricFormat.COUNT}, 2051.06, "2,051"),
            ({"format": MetricFormat.SIGNED}, 5.72, "+5.7"),
            ({"format": MetricFormat.SIGNED}, -2.14, "-2.1"),
            ({"format": MetricFormat.SIGNED}, 0.0, "+0.0"),
            ({"format": MetricFormat.MONEY}, 54126450, "$54,126,450"),
        ],
    )
    def test_values_are_shown_in_the_metrics_own_format(
        self, kwargs: dict, value: float, shown: str
    ) -> None:
        assert spec(**kwargs).format_value(value) == shown

    @pytest.mark.parametrize("missing", [None, float("nan")])
    def test_a_missing_value_is_a_dash_not_a_zero(self, missing) -> None:
        for kind in MetricFormat:
            assert spec(format=kind).format_value(missing) == "—"


class TestSpec:
    def test_defaults(self) -> None:
        metric = spec()
        assert metric.format is MetricFormat.DECIMAL
        assert metric.provenance is Provenance.DERIVED
        assert metric.higher_is_better is True
        assert metric.decimals == 1

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"key": "TS%"},
            {"key": "TsPct"},
            {"label": " "},
            {"name": ""},
            {"description": ""},
            {"category": ""},
            {"decimals": -1},
        ],
    )
    def test_invalid_definitions_are_rejected(self, kwargs: dict) -> None:
        key = kwargs.pop("key", "ts_pct")
        with pytest.raises(ValueError):
            spec(key, **kwargs)

    def test_specs_are_immutable(self) -> None:
        with pytest.raises(AttributeError):
            spec().label = "X"  # type: ignore[misc]


class TestCatalog:
    CATALOG = MetricCatalog(
        (
            spec("pts_per_game", category="Scoring"),
            spec("ast_per_game", category="Creation"),
            spec("ts_pct", category="Scoring"),
        )
    )

    def test_lookup_membership_and_order(self) -> None:
        assert self.CATALOG["ts_pct"].key == "ts_pct"
        assert "ts_pct" in self.CATALOG and "nope" not in self.CATALOG
        assert self.CATALOG.keys == ("pts_per_game", "ast_per_game", "ts_pct")
        assert [metric.key for metric in self.CATALOG] == list(self.CATALOG.keys)
        assert len(self.CATALOG) == 3

    def test_categories_in_order_of_first_appearance(self) -> None:
        assert self.CATALOG.categories == ("Scoring", "Creation")
        assert [m.key for m in self.CATALOG.in_category("Scoring")] == ["pts_per_game", "ts_pct"]
        assert self.CATALOG.in_category("Nothing") == ()

    def test_an_unknown_key_is_named(self) -> None:
        with pytest.raises(KeyError, match="no metric named 'nope'"):
            self.CATALOG["nope"]

    def test_duplicate_keys_are_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"metric keys repeat: \['ts_pct'\]"):
            MetricCatalog((spec(), spec()))
