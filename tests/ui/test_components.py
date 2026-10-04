"""The pieces pages are built from, each drawn on its own."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance
from tests.ui.conftest import TIMEOUT, figures
from wb import components

CATALOG = MetricCatalog(
    (
        MetricSpec("off_rating", "ORtg", "Offensive rating", "Points per 100 possessions.",
                   "Efficiency", provenance=Provenance.MEASURED),
        MetricSpec("efg_pct", "eFG%", "Effective field goal percentage", "Shooting.",
                   "Shooting", MetricFormat.PERCENT),
    )
)  # fmt: skip


def drawn(script) -> AppTest:  # type: ignore[no-untyped-def]
    opened = AppTest.from_function(script, default_timeout=TIMEOUT)
    opened.run()
    assert not opened.exception, [error.value for error in opened.exception]
    return opened


def test_table_height_shows_the_rows_and_the_header() -> None:
    assert components.table_height(0) == components.ROW + 3
    assert components.table_height(10) == 11 * components.ROW + 3


def test_a_file_is_supplied_and_a_feed_is_up_to_date() -> None:
    assert components.source_word("contract_file", "ok") == "Supplied"
    assert components.source_word("nba_stats", "ok") == "Up to date"
    assert components.source_word("contract_file", "absent") == "Not supplied"
    assert components.source_word("nba_stats", "failing") == "Failing"


def test_every_state_and_kind_has_a_word_an_icon_and_a_colour() -> None:
    for word, icon, color in components.STATES.values():
        assert word and icon.startswith(":material/") and color
    kinds = (
        components.MEASURED,
        components.DERIVED,
        components.ESTIMATE,
        components.MODELED,
        components.ASSUMPTION,
    )
    assert set(components.PROVENANCE) == set(kinds)
    words = [components.PROVENANCE[kind][0] for kind in kinds]
    assert words == ["Measured", "Derived", "Estimate", "Modeled", "Your assumption"]
    assert len({components.PROVENANCE[kind][2] for kind in kinds}) == len(kinds)


def test_a_column_heading_says_what_the_metric_is_and_where_it_comes_from() -> None:
    settings = components.metric_columns(CATALOG, ["off_rating", "efg_pct"])
    assert settings["off_rating"]["label"] == "ORtg"
    assert settings["off_rating"]["help"] == (
        "Offensive rating. Points per 100 possessions. Measured by the league."
    )
    assert settings["efg_pct"]["help"].endswith("Derived by the lab.")


def test_a_modeled_metric_says_it_is_an_estimate() -> None:
    from front_office.domain.schema import Provenance
    from front_office.modeling.value.catalog import VALUE_METRICS

    settings = components.metric_columns(VALUE_METRICS, ["impact", "minutes_share"])
    assert settings["impact"]["label"] == "IMP"
    assert settings["impact"]["help"].endswith("Estimated by the value model.")
    assert settings["minutes_share"]["help"].endswith("Derived by the lab.")
    assert components.origin(Provenance.MEASURED) == "Measured by the league."
    word, icon, _, meaning = components.PROVENANCE[components.MODELED]
    assert word == "Modeled" and icon.startswith(":material/")
    assert "an estimate with error, never a count" in meaning


def test_an_estimated_column_is_marked_and_says_so() -> None:
    settings = components.metric_columns(CATALOG, ["off_rating"], estimated=["off_rating"])
    assert settings["off_rating"]["label"] == "≈ ORtg"
    assert settings["off_rating"]["help"].endswith("Estimated from box scores.")
    assert "Measured by the league" not in settings["off_rating"]["help"]


def test_figures_sit_in_one_row_unless_told_to_wrap() -> None:
    def one_row() -> None:
        from wb import components
        from wb.components import Figure

        components.figures([Figure(f"Figure {n}", str(n), f"context {n}") for n in range(5)])

    def wrapped() -> None:
        from wb import components
        from wb.components import Figure

        components.figures(
            [Figure(f"Figure {n}", str(n), f"context {n}") for n in range(5)], per_row=3
        )

    expected = {f"Figure {n}": (str(n), f"context {n}") for n in range(5)}
    row = drawn(one_row)
    assert figures(row) == expected and len(row.columns) == 5
    rows = drawn(wrapped)
    # Two rows of three tiles: the second row keeps the tile width with one place empty.
    assert figures(rows) == expected and len(rows.columns) == 6
    assert list(figures(rows)) == list(expected)


def test_a_chart_comes_with_its_table_and_says_how_to_save_an_image() -> None:
    def script() -> None:
        import pandas as pd

        from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
        from wb import charts, components
        from wb.theme import LIGHT

        catalog = MetricCatalog(
            (MetricSpec("efg_pct", "eFG%", "Effective FG%", "Shooting.", "Shooting",
                        MetricFormat.PERCENT),)
        )  # fmt: skip
        frame = pd.DataFrame({"season": ["2024-25", "2025-26"], "efg_pct": [0.543, None]})
        figure = charts.line(
            frame.assign(text=["a", "b"]), x="season", y="efg_pct", text="text", palette=LIGHT,
            categorical_x=True,
        )  # fmt: skip
        components.chart(figure, frame, key="trend", filename="trend", catalog=catalog)

    opened = drawn(script)
    # The test harness files an expander that has an icon under "status".
    assert [block.label for block in opened.status] == ["Table view and export"]
    assert len(opened.dataframe) == 1
    table = opened.dataframe[0].value
    assert table["season"].tolist() == ["2024-25", "2025-26"]
    assert table["efg_pct"].iloc[0] == 0.543  # numbers underneath, so the table sorts
    captions = [caption.value for caption in opened.caption]
    assert "For a static image, use the camera button at the top right of the chart." in captions


def test_an_empty_section_says_what_is_missing_and_why() -> None:
    def script() -> None:
        from wb import components

        components.empty("No games", "Nothing was played in this span.")
        components.tagged(
            ("Needs attention", ":material/warning:", "orange"), "**Contracts.** None."
        )

    opened = drawn(script)
    said = [element.value for element in opened.markdown]
    assert ":material/inbox: **No games**" in said
    assert ":orange-badge[:material/warning: Needs attention] **Contracts.** None." in said
    assert [caption.value for caption in opened.caption] == ["Nothing was played in this span."]


def test_too_few_games_names_the_span_it_could_not_draw() -> None:
    assert components.TOO_FEW_GAMES.format(games=20).startswith(
        "Form over 20 games needs 20 games played"
    )
