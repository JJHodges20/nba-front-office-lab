from __future__ import annotations

from datetime import date

import pytest

from front_office.domain.seasons import Season, SeasonType


@pytest.mark.parametrize(
    ("label", "start_year"),
    [("2025-26", 2025), ("1999-00", 1999), ("1946-47", 1946), (" 2009-10 ", 2009)],
)
def test_parse_reads_the_start_year(label: str, start_year: int) -> None:
    assert Season.parse(label).start_year == start_year


@pytest.mark.parametrize(
    "label", ["2025-27", "2025", "25-26", "2025/26", "2025-2026", "", "abcd-ef"]
)
def test_parse_rejects_malformed_labels(label: str) -> None:
    with pytest.raises(ValueError):
        Season.parse(label)


def test_parse_rejects_non_strings() -> None:
    with pytest.raises(ValueError):
        Season.parse(2025)  # type: ignore[arg-type]


@pytest.mark.parametrize("start_year", [1946, 1999, 2009, 2025, 2099])
def test_label_round_trips(start_year: int) -> None:
    season = Season(start_year)
    assert Season.parse(season.label) == season


def test_label_pads_the_turn_of_a_century() -> None:
    assert Season(1999).label == "1999-00"
    assert Season(2008).label == "2008-09"


def test_rejects_years_before_the_league_existed() -> None:
    with pytest.raises(ValueError):
        Season(1945)


@pytest.mark.parametrize("value", ["2025", 2025.0, True, None])
def test_start_year_must_be_an_int(value: object) -> None:
    with pytest.raises(TypeError):
        Season(value)  # type: ignore[arg-type]


def test_coerce_accepts_season_label_and_year() -> None:
    season = Season(2025)
    assert Season.coerce(season) is season
    assert Season.coerce("2025-26") == season
    assert Season.coerce(2025) == season


def test_seasons_order_chronologically() -> None:
    assert Season(2024) < Season(2025)
    assert sorted([Season(2026), Season(2024), Season(2025)]) == Season.span(2024, 2026)


def test_span_is_inclusive_and_rejects_reversed_ranges() -> None:
    assert [s.label for s in Season.span("2023-24", "2025-26")] == ["2023-24", "2024-25", "2025-26"]
    assert Season.span("2025-26", "2025-26") == [Season(2025)]
    with pytest.raises(ValueError):
        Season.span("2025-26", "2024-25")


def test_neighbours() -> None:
    season = Season(2025)
    assert season.next().label == "2026-27"
    assert season.previous().label == "2024-25"
    assert season.offset(-3).label == "2022-23"
    assert season.end_year == 2026
    assert str(season) == "2025-26"


@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2026, 6, 30), "2025-26"),  # last day of the league year
        (date(2026, 7, 1), "2026-27"),  # new cap takes effect
        (date(2026, 10, 1), "2026-27"),  # offseason, before opening night
        (date(2027, 2, 14), "2026-27"),
        (date(2027, 6, 30), "2026-27"),
    ],
)
def test_league_year_rolls_over_on_july_first(day: date, label: str) -> None:
    assert Season.league_year_on(day).label == label


def test_seasons_are_hashable_and_immutable() -> None:
    assert len({Season(2025), Season.parse("2025-26")}) == 1
    with pytest.raises(AttributeError):
        Season(2025).start_year = 2026  # type: ignore[misc]


def test_season_type_values_and_titles() -> None:
    assert [t.value for t in SeasonType] == ["regular", "playoffs", "playin"]
    assert SeasonType("playin") is SeasonType.PLAY_IN
    assert SeasonType.PLAY_IN.title == "Play-In"
    assert SeasonType.REGULAR.title == "Regular Season"
