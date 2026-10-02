from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from front_office.domain.cap_rules import PayrollLine
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from wb import formats

CATALOG = MetricCatalog(
    (
        MetricSpec("ts_pct", "TS%", "True shooting", "Points per attempt.", "Scoring",
                   MetricFormat.PERCENT),
        MetricSpec("net", "Net", "Net rating", "Margin per 100.", "Impact", MetricFormat.SIGNED),
        MetricSpec("ppg", "PPG", "Points per game", "Points per game.", "Scoring"),
        MetricSpec("games", "GP", "Games", "Games played.", "Availability", MetricFormat.COUNT),
        MetricSpec("salary", "$", "Salary", "Salary.", "Money", MetricFormat.MONEY),
        MetricSpec("ft_rate", "FTr", "Free throw rate", "FTA per FGA.", "Scoring", decimals=3),
    )
)  # fmt: skip
MISSING_VALUES = [None, float("nan"), pd.NA]


@pytest.mark.parametrize("missing", MISSING_VALUES)
def test_a_missing_value_is_a_dash_everywhere(missing) -> None:
    for function in (
        formats.money,
        formats.money_compact,
        formats.share,
        formats.number,
        formats.ordinal,
        formats.percentile,
        formats.height,
        formats.moment,
        formats.day,
        formats.words,
    ):
        assert function(missing) == "—", function.__name__
    assert formats.rank_of(missing, 30) == "—"
    assert formats.is_missing(missing)


def test_zero_is_a_value_not_a_gap() -> None:
    assert not formats.is_missing(0) and not formats.is_missing(0.0)
    assert formats.money(0) == "$0"
    assert formats.share(0) == "0.0%"


def test_money() -> None:
    assert formats.money(40_000_000) == "$40,000,000"
    assert formats.money(599_999.6) == "$600,000"


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (150_921_000, "$150.9M"),
        (1_000_000, "$1.0M"),
        (640_000, "$640K"),
        (999, "$999"),
        (0, "$0"),
        (-2_985_000, "-$3.0M"),
        (-5_000, "-$5K"),
    ],
)
def test_money_in_the_largest_unit_that_fits(amount: float, text: str) -> None:
    assert formats.money_compact(amount) == text


def test_shares_and_numbers() -> None:
    assert formats.share(0.2425) == "24.2%"
    assert formats.share(0.2425, 0) == "24%"
    assert formats.share(1.508757) == "150.9%"
    assert formats.number(174492) == "174,492"
    assert formats.number(28.04, 1) == "28.0"


@pytest.mark.parametrize(
    ("rank", "text"),
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th"),
     (21, "21st"), (22, "22nd"), (23, "23rd"), (30, "30th"), (101, "101st"), (111, "111th")],
)  # fmt: skip
def test_ordinals(rank: int, text: str) -> None:
    assert formats.ordinal(rank) == text


def test_ranks_and_percentiles_in_words() -> None:
    assert formats.rank_of(4, 30) == "4th of 30"
    assert formats.rank_of(pd.array([2], dtype="Int64")[0], 29) == "2nd of 29"
    assert formats.rank_of(4, None) == "4th"
    assert formats.percentile(91.6) == "92nd percentile"
    assert formats.percentile(50.0) == "50th percentile"
    # The best of 421 players sits at 99.88: that is the 99th percentile, not the 100th.
    assert formats.percentile(99.88) == "99th percentile"
    assert formats.percentile(0.12) == "1st percentile"


def test_height_and_dates() -> None:
    assert formats.height(80) == "6'8\""
    assert formats.height(72) == "6'0\""
    assert formats.day(pd.Timestamp("2026-04-12")) == "Apr 12, 2026"
    assert formats.moment(datetime(2026, 10, 1, 19, 6)) == "Oct 01, 2026 19:06 UTC"
    assert formats.moment(pd.Timestamp("2026-10-01 19:06")) == "Oct 01, 2026 19:06 UTC"


def test_stored_codes_as_words() -> None:
    assert formats.words("early_termination") == "Early termination"
    assert formats.words("player") == "Player"
    assert formats.CONTRACT_TYPES == {"standard": "Standard", "two_way": "Two-way"}
    assert formats.CONTRACT_STATUSES["dead_money"] == "Dead money"


def test_every_payroll_line_has_a_short_name() -> None:
    assert set(formats.LINE_LABELS) == set(PayrollLine)
    assert formats.LINE_LABELS[PayrollLine.MINIMUM_TEAM_SALARY] == "Floor"
    assert len(set(formats.LINE_LABELS.values())) == len(PayrollLine)
    for word in ("Floor", "Cap", "Tax", "Aprons"):
        assert word in formats.LINES_EXPLAINED


@pytest.mark.parametrize(
    ("key", "tickformat"),
    [("ts_pct", ".1%"), ("net", "+.1f"), ("ppg", ",.1f"), ("games", ",.0f"), ("salary", "$,.0f"),
     ("ft_rate", ",.3f")],
)  # fmt: skip
def test_an_axis_is_formatted_like_the_metric_it_shows(key: str, tickformat: str) -> None:
    assert formats.tickformat(CATALOG[key]) == tickformat


def test_a_metric_column_as_the_text_a_reader_sees() -> None:
    frame = pd.DataFrame({"ts_pct": [0.5881, None], "net": [5.72, -2.14]}, index=[7, 8])
    shown = formats.shown(CATALOG, frame, "ts_pct")
    assert shown.tolist() == ["58.8%", "—"] and shown.index.tolist() == [7, 8]
    assert formats.shown(CATALOG, frame, "net").tolist() == ["+5.7", "-2.1"]


def test_a_styled_table_shows_formats_but_keeps_numbers_underneath() -> None:
    frame = pd.DataFrame(
        {"name": ["A", "B"], "ts_pct": [0.5881, None], "salary": [40_000_000, 600_000]}
    )
    styled = formats.styled(frame, CATALOG, {"name": str.upper})
    html = styled.to_html()
    assert "58.8%" in html and "$40,000,000" in html and "—" in html
    # Sorting acts on the data, which is untouched.
    assert styled.data["ts_pct"].iloc[0] == 0.5881
    assert styled.data.equals(frame)


def test_a_styled_table_writes_a_dash_in_columns_it_has_no_format_for_too() -> None:
    frame = pd.DataFrame(
        {"name": ["A", None], "minutes": [31.5, float("nan")], "ts_pct": [0.5881, None]}
    )
    html = formats.styled(frame, CATALOG).to_html()
    assert html.count(">—<") == 3
    assert ">nan<" not in html and ">None<" not in html
