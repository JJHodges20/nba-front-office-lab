"""The pieces pages are built from, each drawn on its own."""

from __future__ import annotations

import re
from pathlib import Path

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
APPS = Path(__file__).resolve().parents[2] / "apps" / "workbench"
TAG = re.compile(r'\(\s*"([^"]+)",\s*":material/([a-z_]+):",\s*"([a-z]+)"')
"""A tag written out in the code: its word, its icon and its colour."""


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
        components.REPORTED,
    )
    assert set(components.PROVENANCE) == set(kinds)
    words = [components.PROVENANCE[kind][0] for kind in kinds]
    assert words == ["Measured", "Derived", "Estimate", "Modeled", "Your assumption", "Reported"]
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


def test_each_row_of_tiles_is_named_for_the_grid_that_wraps_it() -> None:
    """UI polish P3: wb/style.css lays out a container keyed "tiles-" as a grid that wraps in
    a narrow window, and one keyed "tiles-wide-" - a row of four tiles or fewer, which has the
    room - with wider tiles. A page's rows are counted from the start of each run, so they
    keep their names."""

    def script() -> None:
        from wb import components
        from wb.components import Figure

        components.new_page()
        components.figures([Figure(f"Figure {n}", str(n)) for n in range(5)])
        components.figures([Figure(f"Long {n}", str(n)) for n in range(4)], per_row=3)
        components.figures([Figure(f"Four {n}", str(n)) for n in range(4)])

    def names(opened: AppTest) -> list[str]:
        # A keyed container's id ends with its key: "$$ID-<hash>-<key>".
        return [block.proto.id.split("-", 2)[2] for block in opened.main.children.values()]

    expected = ["tiles-0", "tiles-wide-1", "tiles-wide-2", "tiles-wide-3"]
    opened = drawn(script)
    assert names(opened) == expected
    assert len(figures(opened)) == 13
    opened.run()
    assert names(opened) == expected, "the same names in the next run"


def test_a_tag_word_looks_the_same_wherever_it_appears() -> None:
    """UI polish P3 (audit F12): "Note" was blue on two pages, orange on two and gray in the
    answers, and "Out of date" was written out in four views. A word has one icon and one
    colour everywhere, and a tag that several pages use is written once, in components."""
    looks: dict[str, set[tuple[str, str]]] = {}
    for path in APPS.rglob("*.py"):
        for word, icon, color in TAG.findall(path.read_text(encoding="utf-8")):
            looks.setdefault(word, set()).add((icon, color))
    assert {word: found for word, found in looks.items() if len(found) > 1} == {}
    for word, _, _ in (components.NOTE, components.CHECK, components.OUT_OF_DATE):
        writers = [
            path.name
            for path in APPS.rglob("*.py")
            if any(found == word for found, _, _ in TAG.findall(path.read_text(encoding="utf-8")))
        ]
        assert writers == ["components.py"], word
    assert components.NO_ANSWER[0] == "No answer"


def test_what_cannot_be_undone_waits_for_its_box() -> None:
    """UI polish P3, the owner's decision: every delete asks first, the same way."""

    def script() -> None:
        import streamlit as st

        from wb import components

        if components.confirmed_button(
            "Delete it", "I want to delete it", key="gone", confirm_key="gone_ok"
        ):
            st.markdown("Deleted.")

    opened = drawn(script)
    button = opened.button(key="gone")
    assert button.label == "Delete it" and button.disabled
    assert button.proto.type != "primary", "never drawn as the page's main action"
    assert "Deleted." not in [element.value for element in opened.markdown]
    opened.checkbox(key="gone_ok").check().run()
    assert not opened.button(key="gone").disabled
    opened.button(key="gone").click().run()
    assert "Deleted." in [element.value for element in opened.markdown]


def test_every_delete_asks_first() -> None:
    """No page draws a plain button that deletes or clears: they go through
    ``components.confirmed_button``, which waits for its box to be ticked."""
    pressed = re.compile(r'st\.(?:form_submit_)?button\(\s*f?"(?:Delete|Clear)')
    found = [
        path.relative_to(APPS).as_posix()
        for path in APPS.rglob("*.py")
        if pressed.search(path.read_text(encoding="utf-8"))
    ]
    assert found == []


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


def test_every_kind_of_message_has_its_one_icon() -> None:
    """UI polish P2: errors, warnings, successes and notes are drawn one way on every page."""

    def script() -> None:
        from wb import components

        components.alert("error", "Refused.")
        components.alert("warning", "Check this.")
        components.alert("success", "Saved.")
        components.alert("info", "Already saved.")

    opened = drawn(script)
    drawn_as = {
        "error": [(e.value, e.icon) for e in opened.error],
        "warning": [(e.value, e.icon) for e in opened.warning],
        "success": [(e.value, e.icon) for e in opened.success],
        "info": [(e.value, e.icon) for e in opened.info],
    }
    assert drawn_as == {
        "error": [("Refused.", ":material/error:")],
        "warning": [("Check this.", ":material/warning:")],
        "success": [("Saved.", ":material/check_circle:")],
        "info": [("Already saved.", ":material/info:")],
    }
