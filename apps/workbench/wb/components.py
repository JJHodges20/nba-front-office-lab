"""The pieces every page is built from: headers, figures, charts with their table view."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from front_office.domain.metrics import MetricCatalog
from front_office.domain.schema import Provenance
from wb import charts
from wb.theme import Palette, palette

MEASURED = "measured"
DERIVED = "derived"
ESTIMATE = "estimate"
MODELED = "modeled"
ASSUMPTION = "assumption"
REPORTED = "reported"

# What each kind of number is, how it is tagged, and what the tag means. Colour never
# carries the meaning alone: every tag has an icon and a word.
PROVENANCE = {
    MEASURED: (
        "Measured",
        ":material/straighten:",
        "blue",
        "Published by the league or counted from its box scores, and shown unchanged.",
    ),
    DERIVED: (
        "Derived",
        ":material/calculate:",
        "gray",
        "Computed by the lab from measured totals with a stated formula. See the metric "
        "glossary in the Analytics Lab.",
    ),
    ESTIMATE: (
        "Estimate",
        ":material/query_stats:",
        "orange",
        "Estimated by the lab. Ratings and pace over a span of games rest on possessions "
        "estimated from box scores, typically within a quarter of a point of the league's "
        "own figure over a full season and noisier over a few games.",
    ),
    MODELED: (
        "Modeled",
        ":material/model_training:",
        "green",
        "Estimated by a model fitted to the lab's own data and tested on seasons it had "
        "not seen: an estimate with error, never a count. What the model is and how it "
        "did is under Player Value, The model.",
    ),
    ASSUMPTION: (
        "Your assumption",
        ":material/edit_note:",
        "violet",
        "Entered or chosen by you: a roster you built, or a salary you typed in.",
    ),
    REPORTED: (
        "Reported",
        ":material/newspaper:",
        "yellow",
        "Said by a source outside the lab's data: the league's transactions and injury "
        "report, or a page on the web. Dated and linked, and never checked against the "
        "lab's figures.",
    ),
}

OK = ("Up to date", ":material/check_circle:", "green")
STATES = {
    "ok": OK,
    "stale": ("Stale", ":material/schedule:", "orange"),
    "failing": ("Failing", ":material/error:", "red"),
    "absent": ("Not supplied", ":material/do_not_disturb_on:", "gray"),
}

# Tags that more than one page uses, each with one look wherever it appears (UI polish P3):
# a page takes them from here instead of writing its own.
NOTE = ("Note", ":material/info:", "blue")
"""Something to know about what is shown."""
CHECK = ("Check", ":material/warning:", "orange")
"""Something to look at before relying on what is shown: a rule a roster breaks, a file's flag."""
OUT_OF_DATE = ("Out of date", ":material/schedule:", "orange")
"""A fitted file that no longer matches the data it is read with."""
NO_ANSWER = ("No answer", ":material/error:", "red")
"""A question that came back without an answer."""


ROW = 34
"""Height of a table row in pixels."""
EMPTY_CELL = "—"
"""What a table shows where a value is missing."""
TOO_FEW_GAMES = (
    "Form over {games} games needs {games} games played in this season and phase. "
    "Choose fewer trailing games, or see the game log."
)
"""What a form chart says instead of drawing a span it does not have the games for."""


def table_height(rows: int) -> int:
    """The height that shows ``rows`` rows and the header, with nothing left over."""
    return ROW * (rows + 1) + 3


def colors() -> Palette:
    """The palette for the theme the reader is using."""
    return palette(st.context.theme.type)


def header(title: str, subtitle: str = "", *, kinds: Sequence[str] = ()) -> None:
    """A page's title, what it covers, and what kinds of number appear on it."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    if kinds:
        provenance(kinds)


def provenance(kinds: Sequence[str]) -> None:
    """A row of tags saying where the numbers below come from."""
    with st.container(horizontal=True, gap="small"):
        for kind in kinds:
            label, icon, color, meaning = PROVENANCE[kind]
            st.badge(label, icon=icon, color=color, help=meaning)


def tagged(tag: tuple[str, str, str], text: str) -> None:
    """A line of text led by a tag: a word and an icon in a colour, then what it is about.

    ``tag`` is ``(word, icon, colour)``. The tag sits in the line itself, so long text
    wraps under it instead of pushing it onto a line of its own.
    """
    word, icon, color = tag
    st.markdown(f":{color}-badge[{icon} {word}] {text}")


def state_badge(state: str, label: str | None = None, *, help: str | None = None) -> None:
    """A status with its icon and its word, so the colour is never the only signal; ``help``
    is what lies behind it, on hover."""
    text, icon, color = STATES[state]
    st.badge(label or text, icon=icon, color=color, help=help)


AlertKind = Literal["error", "warning", "success", "info"]
ALERTS: dict[str, tuple[Callable[..., Any], str]] = {
    "error": (st.error, ":material/error:"),
    "warning": (st.warning, ":material/warning:"),
    "success": (st.success, ":material/check_circle:"),
    "info": (st.info, ":material/info:"),
}
"""One icon for each kind of message, the same on every page (UI polish P2)."""


def alert(kind: AlertKind, message: str) -> None:
    """A message about what just happened - something refused, something to check, something
    done, something to know - in one form on every page. ``message`` is markdown: text from
    outside the lab is escaped by the caller."""
    draw, icon = ALERTS[kind]
    draw(message, icon=icon)


def confirmed_button(
    label: str,
    confirm: str,
    *,
    key: str,
    confirm_key: str,
    icon: str = ":material/delete:",
) -> bool:
    """A button for what cannot be undone, the same on every page (UI polish P3): it stays
    off until its box is ticked, and it is never the page's main action. True when pressed."""
    ticked = st.checkbox(confirm, key=confirm_key)
    return st.button(label, key=key, icon=icon, disabled=not ticked)


def source_word(source: str, state: str) -> str:
    """How a source's state is worded: a file is supplied, a feed is up to date."""
    if source == "contract_file" and state == "ok":
        return "Supplied"
    return STATES[state][0]


ORIGINS = {
    Provenance.MEASURED: "Measured by the league.",
    Provenance.DERIVED: "Derived by the lab.",
    Provenance.MODELED: "Estimated by the value model.",
}


def origin(kind: Provenance) -> str:
    """How a metric's provenance is worded in a tooltip."""
    return ORIGINS.get(kind, ORIGINS[Provenance.DERIVED])


@dataclass(frozen=True, slots=True)
class Figure:
    """One headline number: what it is, its value, and optional context beneath it."""

    label: str
    value: str
    context: str | None = None
    """A rank, a percentile or a comparison, shown under the value in quiet ink."""
    help: str | None = None
    trend: Sequence[float] | None = None
    """Recent values, oldest first, drawn as a small line under the figure."""


TILE_ROWS = "_tile_rows"
"""How many rows of tiles the page has drawn in this run, which names each row's container."""


def new_page() -> None:
    """Begin a page's run, so that its rows of tiles take the same names in every run."""
    st.session_state[TILE_ROWS] = 0


def figures(items: Sequence[Figure], *, per_row: int | None = None) -> None:
    """Headline numbers side by side, in rows of ``per_row`` where one row would crowd them.

    A tile cuts off text that does not fit, so figures with long values or long context
    get fewer, wider tiles: ``per_row=3``. Each row is a grid (``wb/style.css``, UI polish
    P3) that wraps its tiles in a narrow window instead of cutting them off: at least 11rem
    each in a row of five or more, and 14rem in a row of four or fewer, which has the room.
    """
    size = per_row or len(items)
    wide = "wide-" if size <= 4 else ""
    for start in range(0, len(items), size):
        row = items[start : start + size]
        count = st.session_state.get(TILE_ROWS, 0)
        st.session_state[TILE_ROWS] = count + 1
        with st.container(key=f"tiles-{wide}{count}"):
            for column, item in zip(st.columns(size), row, strict=False):
                column.metric(
                    item.label,
                    item.value,
                    delta=item.context,
                    delta_color="off",
                    delta_arrow="off",
                    help=item.help,
                    border=True,
                    chart_data=list(item.trend) if item.trend is not None else None,
                    chart_type="line",
                )


def chart(
    figure: go.Figure,
    table: pd.DataFrame,
    *,
    key: str,
    filename: str,
    catalog: MetricCatalog | None = None,
    formats: Mapping[str, Callable[[object], str]] | None = None,
) -> None:
    """A chart with its table view and its exports.

    Nothing on a chart is reachable only by hovering: the same values are in the table
    underneath, which can be saved as CSV. The camera button on the chart saves it as an
    image; the HTML export keeps it interactive. Metric columns are shown in their own
    format when a ``catalog`` is given; ``formats`` does the same for other columns. The
    CSV always holds the plain numbers.
    """
    st.plotly_chart(figure, theme=None, config=charts.image_config(filename), key=key)
    with st.expander("Table view and export", icon=":material/table_view:"):
        plain = catalog is None and not formats
        shown = table if plain else _styled(table, catalog, formats)
        headings: dict = {column: heading(str(column)) for column in table.columns}
        if catalog is not None:
            headings |= metric_columns(
                catalog, [column for column in table.columns if column in catalog]
            )
        st.dataframe(
            shown, hide_index=True, placeholder="—", key=f"{key}_table", column_config=headings
        )
        with st.container(horizontal=True, gap="small"):
            export(table, filename, key=f"{key}_csv")
            st.download_button(
                # Short, like "Data (CSV)": the longer label was cut in a narrow column (P5).
                "Chart (HTML)",
                figure.to_html(include_plotlyjs="cdn", full_html=True),
                file_name=f"{filename}.html",
                mime="text/html",
                key=f"{key}_html",
                icon=":material/download:",
                on_click="ignore",
                help="The chart as a page to open in a browser, where it can still be hovered "
                "and zoomed.",
            )
        st.caption("For a static image, use the camera button at the top right of the chart.")


HEADINGS = {
    "name": "Name",
    "team_name": "Team",
    "player_name": "Player",
    "team": "Team",
    "season": "Season",
    "season_type": "Phase",
    "conference": "Conference",
    "game_date": "Date",
    "games_played": "Games",
}
"""Words for the columns a chart's table view shows most often, where no metric names them."""


def heading(column: str) -> str:
    """A column's heading in a chart's table view: its word, or its name in plain case. The CSV
    keeps the column's own name (UI polish P5: the table views showed "team_name")."""
    if column in HEADINGS:
        return HEADINGS[column]
    words = column.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def export(table: pd.DataFrame, filename: str, *, key: str, label: str = "Data (CSV)") -> None:
    """A button that saves a table as CSV."""
    st.download_button(
        label,
        table.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{filename}.csv",
        mime="text/csv",
        key=key,
        icon=":material/download:",
        on_click="ignore",
    )


def empty(title: str, body: str, *, icon: str = ":material/inbox:") -> None:
    """What a section shows when it has nothing to show, and why."""
    with st.container(border=True):
        st.markdown(f"{icon} **{title}**")
        st.caption(body)


def metric_columns(
    catalog: MetricCatalog,
    keys: Sequence[str],
    *,
    estimated: Sequence[str] = (),
) -> dict:
    """Column settings for metric columns: the stat-sheet label, and what it means on hover."""
    settings = {}
    for key in keys:
        spec = catalog[key]
        is_estimate = key in estimated
        note = "Estimated from box scores." if is_estimate else origin(spec.provenance)
        settings[key] = st.column_config.Column(
            f"≈ {spec.label}" if is_estimate else spec.label,
            help=f"{spec.name}. {spec.description} {note}",
        )
    return settings


def _styled(  # type: ignore[no-untyped-def]
    table: pd.DataFrame,
    catalog: MetricCatalog | None,
    extra: Mapping[str, Callable[[object], str]] | None = None,
):
    formats: dict = {}
    if catalog is not None:
        formats = {key: catalog[key].format_value for key in table.columns if key in catalog}
    formats.update(extra or {})
    return table.style.format(formats, na_rep=EMPTY_CELL)
