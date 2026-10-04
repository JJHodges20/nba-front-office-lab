"""The fit measures: one list that the table, the catalog and the computation all follow."""

from __future__ import annotations

import pytest

from front_office.domain.fit import (
    COVERAGE_ROLES,
    MEASURE_KEYS,
    MEASURES,
    Area,
    Kind,
    measure,
    measures_in,
)
from front_office.domain.schema import Provenance
from front_office.domain.tables import MODELED_TABLES, REBUILT_TABLES, table
from front_office.domain.tables.fit import TEAM_FIT_PROFILES
from front_office.modeling.fit import FIT_METRICS


def test_measures_are_found_by_key_and_by_area() -> None:
    assert measure("usage_sum").area is Area.USAGE
    assert [item.key for item in measures_in(Area.USAGE)] == ["usage_sum", "usage_top"]
    with pytest.raises(KeyError, match="no fit measure named 'synergy'"):
        measure("synergy")
    assert COVERAGE_ROLES == (
        "floor_spacer",
        "perimeter_defender",
        "primary_creator",
        "rim_protector",
        "secondary_creator",
        "switchable_wing",
    )


def test_labels_are_short_and_names_are_proper() -> None:
    for item in MEASURES:
        assert 0 < len(item.label) <= 10, item.key
        assert item.name[0].isupper() and item.description.endswith("."), item.key


def test_the_table_stores_every_measure_as_a_modeled_float() -> None:
    assert table("team_fit_profiles") is TEAM_FIT_PROFILES
    names = list(TEAM_FIT_PROFILES.column_names)
    assert names[:5] == ["season", "team_id", "archetype_version", "model_version", "players"]
    assert names[5:] == list(MEASURE_KEYS)
    by_name = {field.name: field for field in TEAM_FIT_PROFILES.fields}
    for item in MEASURES:
        field = by_name[item.key]
        assert field.provenance is Provenance.MODELED and field.dtype == "float"
        assert field.description == item.description
        if item.kind in (Kind.COUNT, Kind.SHARE):
            assert field.minimum == 0, item.key
    assert by_name["impact_sum"].unit == "points per 100 possessions"
    assert by_name["height"].unit == "inches"
    assert TEAM_FIT_PROFILES in MODELED_TABLES and TEAM_FIT_PROFILES in REBUILT_TABLES


def test_the_catalog_labels_every_measure_as_modeled() -> None:
    assert FIT_METRICS.keys == MEASURE_KEYS
    for item in MEASURES:
        spec = FIT_METRICS[item.key]
        assert spec.provenance is Provenance.MODELED
        assert (spec.label, spec.name, spec.category) == (item.label, item.name, str(item.area))
        assert spec.higher_is_better == item.higher_is_better
    assert FIT_METRICS["spacers"].format == "count"
    assert FIT_METRICS["usage_sum"].format == "percent"
    assert FIT_METRICS["impact_sum"].format == "signed"
    assert set(FIT_METRICS.categories) == {str(area) for area in Area}


def test_each_count_names_the_roles_it_counts() -> None:
    by_key = {item.key: item for item in MEASURES}
    creators = ("primary_creator", "secondary_creator")
    defenders = ("perimeter_defender", "switchable_wing", "rim_protector")
    assert by_key["primary_creators"].roles == ("primary_creator",)
    assert by_key["creators"].roles == creators
    assert by_key["spacers"].roles == ("floor_spacer",)
    assert by_key["perimeter_defenders"].roles == ("perimeter_defender",)
    assert by_key["switchable_wings"].roles == ("switchable_wing",)
    assert by_key["rim_protectors"].roles == ("rim_protector",)
    assert by_key["bench_creators"].roles == creators and by_key["bench_creators"].bench
    assert by_key["bench_bigs"].group == "in_bigs" and by_key["bench_bigs"].bench
    assert by_key["bench_defenders"].roles == defenders and by_key["bench_defenders"].bench
    for item in MEASURES:
        if item.bench:
            assert item.key.startswith("bench_"), item.key
        if item.key.startswith("bench_"):
            assert item.bench, item.key
