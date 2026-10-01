from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from front_office.domain.schema import (
    ContractViolationError,
    DType,
    Field,
    Provenance,
    TableContract,
    conform_frame,
    validate_frame,
)

CONTRACT = TableContract(
    name="sample",
    domain="test",
    description="A table exercising every logical type.",
    grain="One row per player per game.",
    fields=(
        Field(
            "player_id",
            DType.INTEGER,
            "Player id.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
        ),
        Field(
            "game_id", DType.STRING, "Game id.", nullable=False, provenance=Provenance.IDENTIFIER
        ),
        Field("game_date", DType.DATE, "Date played.", nullable=False),
        Field("team_id", DType.INTEGER, "Team id."),
        Field("minutes", DType.FLOAT, "Minutes played.", minimum=0, maximum=70),
        Field("won", DType.BOOLEAN, "Whether the team won."),
        Field("is_home", DType.BOOLEAN, "Home game.", nullable=False),
        Field("phase", DType.STRING, "Season phase.", allowed=("regular", "playoffs")),
        Field("fetched_at", DType.DATETIME, "Fetch time.", provenance=Provenance.OPERATIONAL),
    ),
    primary_key=("player_id", "game_id"),
    indexes=(("game_date",),),
)


def good_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": [1, 2],
            "game_id": ["0022500001", "0022500001"],
            "game_date": ["2025-10-21", "2025-10-21"],
            "team_id": [1610612760, None],
            "minutes": [34.5, None],
            "won": [True, None],
            "is_home": [True, False],
            "phase": ["regular", None],
            "fetched_at": ["2026-10-01T12:00:00Z", None],
        }
    )


def rules(frame: pd.DataFrame) -> list[str]:
    return [violation.rule for violation in validate_frame(frame, CONTRACT)]


def test_a_conforming_frame_has_no_violations() -> None:
    assert validate_frame(good_frame(), CONTRACT) == []


def test_conform_gives_canonical_dtypes_and_column_order() -> None:
    shuffled = good_frame()[list(reversed(CONTRACT.column_names))]
    conformed = conform_frame(shuffled, CONTRACT)
    assert tuple(conformed.columns) == CONTRACT.column_names
    assert {name: str(dtype) for name, dtype in conformed.dtypes.items()} == {
        "player_id": "int64",
        "game_id": "str",
        "game_date": "datetime64[ns]",
        "team_id": "Int64",
        "minutes": "float64",
        "won": "boolean",
        "is_home": "bool",
        "phase": "str",
        "fetched_at": "datetime64[ns]",
    }


def test_conform_keeps_values_and_missingness() -> None:
    conformed = conform_frame(good_frame(), CONTRACT)
    assert conformed["team_id"].tolist()[0] == 1610612760
    assert conformed["team_id"].isna().tolist() == [False, True]
    assert conformed["game_date"][0] == pd.Timestamp("2025-10-21")
    assert conformed["fetched_at"][0] == pd.Timestamp("2026-10-01 12:00:00")
    assert conformed["phase"].isna().tolist() == [False, True]


def test_conform_does_not_modify_its_input() -> None:
    frame = good_frame()
    before = frame.copy(deep=True)
    conform_frame(frame, CONTRACT)
    pd.testing.assert_frame_equal(frame, before)


def test_conform_resets_the_index() -> None:
    frame = good_frame()
    frame.index = [10, 20]
    assert conform_frame(frame, CONTRACT).index.tolist() == [0, 1]


def test_datetimes_are_converted_to_naive_utc() -> None:
    frame = good_frame()
    eastern = dt.timezone(dt.timedelta(hours=-4))
    frame["fetched_at"] = [dt.datetime(2026, 10, 1, 8, 0, tzinfo=eastern), None]
    conformed = conform_frame(frame, CONTRACT)
    assert conformed["fetched_at"][0] == pd.Timestamp("2026-10-01 12:00:00")
    assert conformed["fetched_at"].dt.tz is None


def test_dates_accept_date_objects_and_timestamps() -> None:
    frame = good_frame()
    frame["game_date"] = [dt.date(2025, 10, 21), pd.Timestamp("2025-10-22")]
    conformed = conform_frame(frame, CONTRACT)
    assert conformed["game_date"].tolist() == [
        pd.Timestamp("2025-10-21"),
        pd.Timestamp("2025-10-22"),
    ]


def test_integer_valued_floats_are_accepted_as_integers() -> None:
    frame = good_frame()
    frame["team_id"] = [1610612760.0, np.nan]
    assert conform_frame(frame, CONTRACT)["team_id"].tolist()[0] == 1610612760


def test_an_empty_frame_conforms() -> None:
    empty = CONTRACT.empty_frame()
    assert len(empty) == 0
    conformed = conform_frame(empty, CONTRACT)
    assert tuple(conformed.columns) == CONTRACT.column_names
    assert str(conformed["player_id"].dtype) == "int64"


def test_missing_and_unexpected_columns_are_reported() -> None:
    frame = good_frame().drop(columns=["minutes"]).assign(extra=1)
    found = validate_frame(frame, CONTRACT)
    assert {(v.rule, v.column) for v in found} == {
        ("missing_column", "minutes"),
        ("unexpected_column", "extra"),
    }


def test_null_in_a_required_column_is_reported() -> None:
    frame = good_frame()
    frame["game_id"] = ["0022500001", None]
    assert rules(frame) == ["null_value"]


def test_duplicate_primary_keys_are_reported() -> None:
    frame = pd.concat([good_frame(), good_frame().iloc[[0]]], ignore_index=True)
    found = validate_frame(frame, CONTRACT)
    assert [(v.rule, v.rows) for v in found] == [("duplicate_key", 1)]


@pytest.mark.parametrize(
    ("column", "values"),
    [
        ("player_id", ["1", "2"]),  # numbers stored as text
        ("player_id", [1.5, 2.0]),  # not whole numbers
        ("player_id", [True, False]),  # booleans are not integers
        ("minutes", ["34.5", None]),
        ("minutes", [np.inf, 1.0]),  # non-finite
        ("game_id", [22500001, 22500002]),  # an id that lost its leading zeros
        ("is_home", [1, 0]),  # integers are not booleans
        ("won", ["W", "L"]),
        ("game_date", [20251021, 20251022]),  # would otherwise parse as nanoseconds
        ("game_date", ["2025-10-21 19:30:00", "2025-10-21"]),  # a date with a time
        ("game_date", ["not a date", "2025-10-21"]),
        ("game_date", ["10/21/2025", "2025-10-21"]),  # text dates must be ISO 8601
        ("game_date", ["MAR 03, 1998", "2025-10-21"]),
        ("fetched_at", [1727784000, None]),
    ],
)
def test_wrong_types_are_reported(column: str, values: list[object]) -> None:
    frame = good_frame()
    frame[column] = pd.Series(values, dtype=object)
    assert "wrong_type" in rules(frame)


def test_range_limits_are_enforced() -> None:
    frame = good_frame()
    frame["minutes"] = [-1.0, 80.0]
    assert rules(frame) == ["below_minimum", "above_maximum"]


def test_values_outside_the_allowed_set_are_reported() -> None:
    frame = good_frame()
    frame["phase"] = ["regular", "preseason"]
    found = validate_frame(frame, CONTRACT)
    assert [v.rule for v in found] == ["not_allowed"]
    assert "preseason" in found[0].detail


def test_empty_text_is_rejected_in_favour_of_null() -> None:
    frame = good_frame()
    frame["phase"] = ["regular", "  "]
    assert "blank_value" in rules(frame)


def test_conform_raises_with_every_violation_listed() -> None:
    frame = good_frame()
    frame["minutes"] = [-1.0, 80.0]
    frame["game_id"] = ["0022500001", None]
    with pytest.raises(ContractViolationError) as caught:
        conform_frame(frame, CONTRACT)
    assert caught.value.table == "sample"
    assert {v.rule for v in caught.value.violations} == {
        "null_value",
        "below_minimum",
        "above_maximum",
    }
    assert "sample.minutes" in str(caught.value)


def test_all_missing_optional_columns_conform() -> None:
    frame = good_frame()
    for column in ("team_id", "minutes", "won", "phase", "fetched_at"):
        frame[column] = None
    conformed = conform_frame(frame, CONTRACT)
    assert conformed[["team_id", "minutes", "won", "phase", "fetched_at"]].isna().all().all()
    assert str(conformed["fetched_at"].dtype) == "datetime64[ns]"


class TestContractDefinition:
    def test_primary_key_must_be_declared(self) -> None:
        with pytest.raises(ValueError, match="undeclared"):
            TableContract(
                "t",
                "d",
                "desc",
                "grain",
                (Field("a", DType.INTEGER, "A.", nullable=False),),
                ("b",),
            )

    def test_primary_key_must_not_be_nullable(self) -> None:
        with pytest.raises(ValueError, match="nullable"):
            TableContract("t", "d", "desc", "grain", (Field("a", DType.INTEGER, "A."),), ("a",))

    def test_primary_key_is_required(self) -> None:
        with pytest.raises(ValueError, match="needs a primary key"):
            TableContract(
                "t", "d", "desc", "grain", (Field("a", DType.INTEGER, "A.", nullable=False),), ()
            )

    def test_field_names_must_be_unique(self) -> None:
        duplicate = Field("a", DType.INTEGER, "A.", nullable=False)
        with pytest.raises(ValueError, match="repeats"):
            TableContract("t", "d", "desc", "grain", (duplicate, duplicate), ("a",))

    def test_indexes_must_use_declared_columns(self) -> None:
        with pytest.raises(ValueError, match="index"):
            TableContract(
                "t",
                "d",
                "desc",
                "grain",
                (Field("a", DType.INTEGER, "A.", nullable=False),),
                ("a",),
                (("zzz",),),
            )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"name": "PlayerId", "dtype": DType.INTEGER, "description": "x"},
            {"name": "player id", "dtype": DType.INTEGER, "description": "x"},
            {"name": "a", "dtype": DType.INTEGER, "description": "  "},
            {"name": "a", "dtype": DType.INTEGER, "description": "x", "allowed": ("y",)},
            {"name": "a", "dtype": DType.STRING, "description": "x", "minimum": 0},
            {"name": "a", "dtype": DType.INTEGER, "description": "x", "references": "players"},
        ],
    )
    def test_invalid_fields_are_rejected(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            Field(**kwargs)  # type: ignore[arg-type]

    def test_field_lookup(self) -> None:
        assert CONTRACT.field("minutes").maximum == 70
        with pytest.raises(KeyError):
            CONTRACT.field("nope")
