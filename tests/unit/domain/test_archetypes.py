"""Archetype definitions: what a rule may say, and what a set of rules promises."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from front_office.domain.archetypes import EVERYONE, Archetype, ArchetypeSet


def one(key: str = "role", **settings: object) -> Archetype:
    defaults = {"name": "Role", "description": "A role.", "measures": ("usage_pct",)}
    return Archetype(key=key, **{**defaults, **settings})


def rules(*archetypes: Archetype, **settings: object) -> ArchetypeSet:
    defaults = {"version": 2, "min_minutes": 500, "fills_at": 67}
    return ArchetypeSet(archetypes=archetypes, **{**defaults, **settings})


class TestAnArchetype:
    def test_it_is_open_to_everyone_and_uses_the_sets_cut_off_unless_it_says(self) -> None:
        plain = one()
        assert (plain.among, plain.fills_at, plain.fills_below, plain.note) == (
            EVERYONE, None, None, "",
        )  # fmt: skip

    def test_names_and_descriptions_are_trimmed_and_needed(self) -> None:
        assert one(name="  Role ", description=" A role.\n").name == "Role"
        for blank in ({"name": " "}, {"description": ""}):
            with pytest.raises(ValidationError, match="needs a name and a description"):
                one(**blank)

    @pytest.mark.parametrize("key", ["Role", "1st", "floor-spacer", "", "floor spacer"])
    def test_a_key_is_a_lowercase_slug(self, key: str) -> None:
        with pytest.raises(ValidationError, match="lowercase letters, digits, underscores"):
            one(key)

    def test_it_needs_measures_and_each_once(self) -> None:
        with pytest.raises(ValidationError, match="at least one measure"):
            one(measures=())
        with pytest.raises(ValidationError, match="repeats a measure"):
            one(measures=("usage_pct", "ts_pct", "usage_pct"))

    @pytest.mark.parametrize("field", ["fills_at", "fills_below"])
    @pytest.mark.parametrize("value", [0, 100.5, -5])
    def test_a_cut_off_is_a_percentile(self, field: str, value: float) -> None:
        with pytest.raises(ValidationError):
            one(**{field: value})

    def test_nothing_else_may_be_said_and_nothing_changed(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs"):
            one(weight=2)
        with pytest.raises(ValidationError, match="frozen"):
            one().name = "Other"


class TestASet:
    def test_it_is_read_in_order_by_key_and_by_count(self) -> None:
        both = rules(one("zeta"), one("alpha"))
        assert both.keys == ("zeta", "alpha") and len(both) == 2
        assert [archetype.key for archetype in both] == ["zeta", "alpha"]
        assert both["alpha"] is both.archetypes[1]
        with pytest.raises(
            KeyError, match=r"no archetype named 'beta'; known: \('zeta', 'alpha'\)"
        ):
            both["beta"]

    def test_assignments_are_stamped_with_its_version(self) -> None:
        assert rules(one()).label == "v2"
        assert rules(one(), version=11).label == "v11"
        with pytest.raises(ValidationError):
            rules(one(), version=0)

    def test_the_cut_off_is_the_archetypes_own_or_else_the_sets(self) -> None:
        both = rules(one("own", fills_at=85), one("shared"), fills_at=60)
        assert (both.cut(both["own"]), both.cut(both["shared"])) == (85, 60)

    def test_keys_may_not_repeat_and_there_must_be_one(self) -> None:
        with pytest.raises(ValidationError, match=r"archetype keys repeat: \['role'\]"):
            rules(one(), one("other"), one())
        with pytest.raises(ValidationError, match="at least one archetype is needed"):
            rules()

    def test_a_tier_must_end_above_where_it_begins(self) -> None:
        rules(one(fills_below=85))
        with pytest.raises(ValidationError, match=r"role: fills_below \(67\) must be above"):
            rules(one(fills_below=67))
        # The archetype's own cut-off is the one that counts.
        with pytest.raises(
            ValidationError, match=r"fills_below \(80\) must be above fills_at \(90\)"
        ):
            rules(one(fills_at=90, fills_below=80))

    @pytest.mark.parametrize("settings", [{"min_minutes": -1}, {"fills_at": 0}, {"fills_at": 101}])
    def test_minutes_and_cut_off_are_bounded(self, settings: dict[str, float]) -> None:
        with pytest.raises(ValidationError):
            rules(one(), **settings)
