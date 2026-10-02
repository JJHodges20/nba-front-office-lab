from __future__ import annotations

import pytest
from pydantic import ValidationError

from front_office.domain.eras import Era, EraSet

ON_RECORD = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]


def test_an_era_with_no_bounds_is_every_season() -> None:
    era = Era(key="all", name="All seasons")
    assert era.seasons(ON_RECORD) == tuple(ON_RECORD)
    assert era.describe(ON_RECORD) == "2019-20 to 2024-25 (6 seasons)"


def test_a_first_season_opens_the_span_and_a_last_season_closes_it() -> None:
    assert Era(key="recent", name="Recent", first_season="2022-23").seasons(ON_RECORD) == (
        "2022-23",
        "2023-24",
        "2024-25",
    )
    assert Era(key="early", name="Early", last_season="2020-21").seasons(ON_RECORD) == (
        "2019-20",
        "2020-21",
    )
    middle = Era(key="middle", name="Middle", first_season="2020-21", last_season="2021-22")
    assert middle.seasons(ON_RECORD) == ("2020-21", "2021-22")


def test_the_latest_seasons_are_counted_back_from_the_newest_on_record() -> None:
    era = Era(key="last_3", name="Last 3 seasons", latest_seasons=3)
    assert era.seasons(ON_RECORD) == ("2022-23", "2023-24", "2024-25")
    # A newer season on record moves the window with it.
    assert era.seasons([*ON_RECORD, "2025-26"]) == ("2023-24", "2024-25", "2025-26")


def test_an_era_never_reaches_outside_the_seasons_on_record() -> None:
    assert Era(key="last_10", name="Last 10", latest_seasons=10).seasons(ON_RECORD) == tuple(
        ON_RECORD
    )
    old = Era(key="nineties", name="Nineties", first_season="1990-91", last_season="1999-00")
    assert old.seasons(ON_RECORD) == ()
    assert old.describe(ON_RECORD) == "no seasons on record"
    assert Era(key="all", name="All").seasons([]) == ()


def test_seasons_come_back_oldest_first_whatever_order_they_arrive_in() -> None:
    shuffled = ["2021-22", "2019-20", "2024-25", "2020-21", "2019-20"]
    assert Era(key="all", name="All").seasons(shuffled) == (
        "2019-20",
        "2020-21",
        "2021-22",
        "2024-25",
    )
    # 1999-00 sorts after 1998-99 although its label does not start with a larger number.
    assert Era(key="all", name="All").seasons(["1999-00", "2000-01", "1998-99"]) == (
        "1998-99",
        "1999-00",
        "2000-01",
    )


def test_one_season_is_described_by_its_label() -> None:
    era = Era.between("2021-22", "2021-22")
    assert era.name == "2021-22" and era.describe(ON_RECORD) == "2021-22"


def test_a_span_chosen_on_the_spot() -> None:
    era = Era.between("2020-21", "2022-23")
    assert (era.key, era.name) == ("custom", "2020-21 to 2022-23")
    assert era.seasons(ON_RECORD) == ("2020-21", "2021-22", "2022-23")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"key": "Modern Era", "name": "Modern"}, "lowercase letters"),
        ({"key": "modern", "name": "  "}, "needs a name"),
        ({"key": "modern", "name": "Modern", "first_season": "2015"}, "not a season label"),
        ({"key": "modern", "name": "Modern", "first_season": "2015-17"}, "not consecutive"),
        (
            {"key": "back", "name": "Back", "first_season": "2020-21", "last_season": "2018-19"},
            "reversed",
        ),
        (
            {"key": "both", "name": "Both", "first_season": "2020-21", "latest_seasons": 5},
            "one or the other",
        ),
        ({"key": "none", "name": "None", "latest_seasons": 0}, "greater than 0"),
        ({"key": "extra", "name": "Extra", "since": "2015-16"}, "Extra inputs"),
    ],
)
def test_an_era_that_makes_no_sense_is_refused(fields: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Era(**fields)


def test_an_era_cannot_be_changed_once_made() -> None:
    era = Era(key="all", name="All")
    with pytest.raises(ValidationError):
        era.name = "Everything"  # type: ignore[misc]


class TestEraSet:
    def test_eras_keep_their_order_and_the_first_is_the_default(self) -> None:
        eras = EraSet(
            eras=(
                Era(key="all", name="All seasons"),
                Era(key="last_5", name="Last 5 seasons", latest_seasons=5),
            )
        )
        assert [era.key for era in eras] == ["all", "last_5"]
        assert len(eras) == 2 and eras.default.key == "all"
        assert eras["last_5"].latest_seasons == 5

    def test_an_unknown_key_names_the_ones_there_are(self) -> None:
        eras = EraSet(eras=(Era(key="all", name="All"), Era(key="modern", name="Modern")))
        with pytest.raises(KeyError, match="no era named 'ancient' .configured: all, modern."):
            eras["ancient"]

    def test_keys_are_unique_and_there_is_at_least_one(self) -> None:
        with pytest.raises(ValidationError, match="repeated: all"):
            EraSet(eras=(Era(key="all", name="All"), Era(key="all", name="Again")))
        with pytest.raises(ValidationError, match="at least one era"):
            EraSet(eras=())
