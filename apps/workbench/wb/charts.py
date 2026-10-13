"""Chart builders: a frame and a palette in, a Plotly figure out.

Nothing here knows about Streamlit or about basketball. Each builder draws what it is
given and computes nothing, so a chart can never disagree with the table beside it.

House rules, applied by every builder:

- One y-scale per chart. Two measures of different scale get two charts.
- Thin marks: 2px lines, bars no thicker than 24px with a rounded data end, markers of
  at least 8px with a ring in the surface colour so overlapping marks stay legible.
- Gridlines and axes are solid hairlines one step off the surface. Nothing is dashed.
- Text is ink, never the series colour; a coloured mark beside it carries identity.
- One series needs no legend. Two or more always get one.
- Colour follows the job: one hue for a single series, the accent against gray for
  emphasis, two poles for above and below a baseline, fixed categorical slots for
  distinct series.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go

from wb.theme import FONT, MAX_LINE_SERIES, MAX_SCATTER_SERIES, Palette

BAR_THICKNESS = 18
"""Pixels a bar may take; the rest of its band is air."""
MAX_BAR_THICKNESS = 24
ROW_HEIGHT = 30
MARKER_SIZE = 10
LINE_WIDTH = 2
RING_WIDTH = 2
CORNER_RADIUS = 4
HAIRLINE = 1
LABEL_ROOM = 0.14
"""Share of a bar chart's value range left free past the longest bar, for its label."""
REFERENCE_MARGIN = 92
"""Pixels kept at the right of a line chart for the name of its reference line."""
LABEL_GAP = "  "
"""Space between a category label and the start of its bar."""
THRESHOLD_ROW = 14
"""Pixels between the rows that threshold names take turns on."""
THRESHOLD_ROWS = 3
"""Rows of threshold names: with two, a phone's narrow chart set "Tax" on "2nd apron"."""
STAGGER_FROM = 9
"""Columns from which a column chart's labels take turns on two levels."""
LABEL_LEVEL = 32
"""Pixels between those two levels: a two-line label and a little air."""
LONG_TITLE = 32
"""Characters an axis title takes on one line. A longer one is set on two balanced lines:
centred under a phone's narrow plot, a long title ran past the chart's edge."""
TIME_TICKS = 4
"""The most date labels a time axis writes."""
COLUMN_PLOT_WIDTH = 900
"""The plot width a column chart is laid out for, in pixels: layout, not measurement."""
BAND_THICKNESS = 0.14
"""Half the height of the inner band of an interval row, as a share of the row."""

MODEBAR = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}
"""Plotly toolbar options: the camera button saves a static image at twice the screen size."""


def image_config(filename: str) -> dict:
    """Toolbar options with the name the saved image should take."""
    options = dict(MODEBAR)
    options["toImageButtonOptions"] = {**MODEBAR["toImageButtonOptions"], "filename": filename}
    return options


def _base(palette: Palette, *, height: int, legend: bool = False) -> go.Figure:
    """An empty figure carrying the house style."""
    figure = go.Figure()
    axis = {
        "showgrid": True,
        "gridcolor": palette.grid,
        "gridwidth": HAIRLINE,
        "griddash": "solid",
        "zeroline": False,
        "showline": False,
        "ticks": "",
        "tickfont": {"color": palette.ink_muted, "size": 12},
        "title": {"font": {"color": palette.ink_secondary, "size": 12}, "standoff": 10},
        "automargin": True,
        "ticklabelstandoff": 4,
    }
    figure.update_layout(
        height=height,
        margin={"l": 8, "r": 16, "t": 28 if legend else 12, "b": 8},
        paper_bgcolor=palette.surface,
        plot_bgcolor=palette.surface,
        font={"family": FONT, "size": 13, "color": palette.ink},
        xaxis=axis,
        yaxis=axis,
        showlegend=legend,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"color": palette.ink_secondary, "size": 12},
            "bgcolor": "rgba(0,0,0,0)",
        },
        hoverlabel={
            "bgcolor": palette.surface,
            "bordercolor": palette.axis,
            "font": {"family": FONT, "size": 12, "color": palette.ink},
            "align": "left",
        },
        hovermode="closest",
        barcornerradius=CORNER_RADIUS,
        dragmode=False,
    )
    return figure


def _reference_line(
    figure: go.Figure,
    palette: Palette,
    *,
    x: float | None = None,
    y: float | None = None,
    color: str | None = None,
) -> None:
    """A solid hairline marking a reference value, drawn beneath the data."""
    line = {"color": color or palette.axis, "width": HAIRLINE}
    if x is not None:
        figure.add_vline(x=x, line=line, layer="below")
    if y is not None:
        figure.add_hline(y=y, line=line, layer="below")


def _thresholds(figure: go.Figure, palette: Palette, thresholds: Mapping[str, float]) -> None:
    """Hairlines at named values on the x-axis, each with its name above the plot.

    Names take turns on three rows in order of value, so lines that sit close together -
    a tax line and the aprons, closer still on a phone - keep their names apart. The
    lines are a step stronger than the gridlines they stand among (UI polish P4).
    """
    ordered = sorted(thresholds.items(), key=lambda item: item[1])
    for position, (title, amount) in enumerate(ordered):
        _reference_line(figure, palette, x=amount, color=palette.deemphasis)
        _note(
            figure, palette, title, x=amount, y=1, yref="paper", yanchor="bottom",
            xanchor="center", yshift=4 + THRESHOLD_ROW * (position % THRESHOLD_ROWS),
        )  # fmt: skip


def _axis_title(text: str) -> str:
    """An axis title as it is set: on one line, or on two balanced lines past ``LONG_TITLE``
    characters (UI polish P4)."""
    if len(text) <= LONG_TITLE or " " not in text:
        return text
    spaces = [place for place, letter in enumerate(text) if letter == " "]
    split = min(spaces, key=lambda place: abs(place - len(text) / 2))
    return f"{text[:split]}<br>{text[split + 1 :]}"


def _side(value: float, axis_range: Sequence[float]) -> str:
    """Which way a note at ``value`` runs so that it stays on the chart: away from the end of
    the axis it sits near (an axis given high-to-low runs the other way)."""
    start, end = axis_range
    share = (value - start) / ((end - start) or 1.0)
    return "right" if share > 0.8 else "left" if share < 0.2 else "center"


def _note(figure: go.Figure, palette: Palette, text: str, *, x: float, y: float, **place) -> None:
    """A quiet label in axis ink, placed in paper or data coordinates."""
    figure.add_annotation(
        text=text,
        x=x,
        y=y,
        showarrow=False,
        font={"color": palette.ink_muted, "size": 11},
        **place,
    )


LABEL_SIDES = ("top center", "bottom center", "middle right", "middle left")
_PLOT_WIDTH, _PLOT_HEIGHT = 560.0, 420.0
_CHARACTER_WIDTH, _LABEL_HEIGHT, _LABEL_OFFSET = 6.5, 12.0, 9.0


def label_sides(
    x: pd.Series, y: pd.Series, labels: pd.Series, *, reverse_y: bool = False
) -> list[str]:
    """Which side of its mark each label should sit on, so labels collide as little as possible.

    Marks are placed on a plot of typical size and each label takes the first side
    where it covers neither a mark nor a label already placed; where no side is free
    it takes the least crowded one. This is layout, not measurement: the plot's real
    size varies, so a few labels may still touch.
    """
    if len(x) == 0:
        return []
    x_span = (x.max() - x.min()) or 1.0
    y_span = (y.max() - y.min()) or 1.0
    across = ((x - x.min()) / x_span * _PLOT_WIDTH).tolist()
    down = (y - y.min()) / y_span if reverse_y else (y.max() - y) / y_span
    down = (down * _PLOT_HEIGHT).tolist()
    half = MARKER_SIZE / 2
    marks = [
        (cx - half, cy - half, cx + half, cy + half) for cx, cy in zip(across, down, strict=True)
    ]

    def box(cx: float, cy: float, width: float, side: str) -> tuple[float, float, float, float]:
        if side == "top center":
            left, top = cx - width / 2, cy - _LABEL_OFFSET - _LABEL_HEIGHT
        elif side == "bottom center":
            left, top = cx - width / 2, cy + _LABEL_OFFSET
        elif side == "middle right":
            left, top = cx + _LABEL_OFFSET, cy - _LABEL_HEIGHT / 2
        else:
            left, top = cx - _LABEL_OFFSET - width, cy - _LABEL_HEIGHT / 2
        return left, top, left + width, top + _LABEL_HEIGHT

    def overlaps(a: tuple, b: tuple) -> bool:
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    placed: list[tuple[float, float, float, float]] = []
    sides = []
    for position, (cx, cy) in enumerate(zip(across, down, strict=True)):
        width = len(str(labels.iloc[position])) * _CHARACTER_WIDTH
        others = marks[:position] + marks[position + 1 :]
        crowding = {}
        for side in LABEL_SIDES:
            candidate = box(cx, cy, width, side)
            crowding[side] = sum(overlaps(candidate, other) for other in (*others, *placed))
            if crowding[side] == 0:
                break
        best = min(crowding, key=crowding.get)
        placed.append(box(cx, cy, width, best))
        sides.append(best)
    return sides


def scatter(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    name: str,
    palette: Palette,
    x_title: str,
    y_title: str,
    x_tickformat: str = "",
    y_tickformat: str = "",
    hover: Sequence[str] = (),
    label: str | None = None,
    group: str | None = None,
    highlight: Sequence[object] = (),
    x_reference: float | None = None,
    y_reference: float | None = None,
    reference_label: str = "",
    reverse_y: bool = False,
    trend: tuple[float, float] | None = None,
    height: int = 480,
) -> go.Figure:
    """Two metrics against each other, one mark per row of ``frame``.

    ``name`` is the column naming each mark; ``hover`` lists columns of ready-made text
    shown under it. ``label`` writes a column's text beside every mark. ``group`` colours
    marks by a column with at most three values. ``highlight`` lists index values that
    are the subject: with no ``group`` they take the accent and everything else recedes
    to gray; with one they are drawn larger. ``trend`` is the ``(intercept, slope)`` of
    a straight line the marks are read against, drawn as a hairline across the plot and
    named by ``reference_label``.
    """
    figure = _base(palette, height=height, legend=group is not None)
    _reference_line(figure, palette, x=x_reference, y=y_reference)
    if trend is not None and len(frame):
        intercept, slope = trend
        ends = [float(frame[x].min()), float(frame[x].max())]
        figure.add_trace(
            go.Scatter(
                x=ends,
                y=[intercept + slope * end for end in ends],
                mode="lines",
                line={"color": palette.axis, "width": HAIRLINE},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    subject = frame.index.isin(list(highlight))
    sides = pd.Series("top center", index=frame.index)
    if label:
        placed = label_sides(frame[x], frame[y], frame[label], reverse_y=reverse_y)
        sides = pd.Series(placed, index=frame.index)

    def trace(rows: pd.DataFrame, color: str, title: str, *, emphasised: bool, legend: bool):
        template = "<b>%{customdata[0]}</b>"
        template += "".join(f"<br>%{{customdata[{n}]}}" for n in range(1, len(hover) + 1))
        return go.Scatter(
            x=rows[x],
            y=rows[y],
            mode="markers+text" if label else "markers",
            text=rows[label] if label else None,
            textposition=sides.loc[rows.index].tolist() if label else None,
            textfont={"color": palette.ink if emphasised else palette.ink_secondary, "size": 11},
            marker={
                "size": MARKER_SIZE + 4 if emphasised else MARKER_SIZE,
                "color": color,
                "line": {"color": palette.surface, "width": RING_WIDTH},
            },
            customdata=rows[[name, *hover]].to_numpy(),
            hovertemplate=template + "<extra></extra>",
            name=title,
            showlegend=legend,
            cliponaxis=False,
        )

    if group is None:
        if subject.any():
            rest = trace(frame[~subject], palette.deemphasis, "", emphasised=False, legend=False)
            figure.add_trace(rest)
            chosen = trace(frame[subject], palette.accent, "", emphasised=True, legend=False)
            figure.add_trace(chosen)
        else:
            figure.add_trace(trace(frame, palette.accent, "", emphasised=False, legend=False))
    else:
        groups = [value for value in frame[group].dropna().unique()]
        if len(groups) > MAX_SCATTER_SERIES:
            raise ValueError(
                f"a scatter can tell {MAX_SCATTER_SERIES} groups apart, not {len(groups)}"
            )
        for color, value in zip(palette.series, groups, strict=False):
            members = frame[group] == value
            figure.add_trace(
                trace(frame[members & ~subject], color, str(value), emphasised=False, legend=True)
            )
            if (members & subject).any():
                figure.add_trace(
                    trace(frame[members & subject], color, "", emphasised=True, legend=False)
                )

    figure.update_xaxes(title_text=_axis_title(x_title), tickformat=x_tickformat)
    figure.update_yaxes(title_text=y_title, tickformat=y_tickformat)
    if reverse_y:
        figure.update_yaxes(autorange="reversed")
    referenced = x_reference is not None or y_reference is not None or trend is not None
    if reference_label and referenced:
        figure.update_layout(margin={"t": 30})
        _note(
            figure, palette, reference_label, x=1, y=1, xref="paper", yref="paper",
            xanchor="right", yanchor="bottom",
        )  # fmt: skip
    return figure


def diverging_bars(
    frame: pd.DataFrame,
    *,
    value: str,
    label: str,
    text: str,
    palette: Palette,
    value_title: str,
    tickformat: str = "",
    hover: Sequence[str] = (),
    highlight: Sequence[object] = (),
) -> go.Figure:
    """Horizontal bars either side of zero, in the order given, top to bottom.

    The two poles show which side of the baseline a bar is on. ``text`` is the column of
    ready-made value labels drawn at each bar's tip. ``highlight`` lists index values
    whose labels are set in bold ink.
    """
    figure = _base(palette, height=ROW_HEIGHT * len(frame) + 60)
    colors = [palette.positive if number >= 0 else palette.negative for number in frame[value]]
    chosen = frame.index.isin(list(highlight))
    names = [
        f"<b>{title}</b>" if bold else title
        for title, bold in zip(frame[label], chosen, strict=True)
    ]
    template = "<b>%{customdata[0]}</b><br>%{customdata[1]}"
    template += "".join(f"<br>%{{customdata[{n}]}}" for n in range(2, len(hover) + 2))
    figure.add_trace(
        go.Bar(
            x=frame[value],
            y=names,
            orientation="h",
            width=BAR_THICKNESS / ROW_HEIGHT,
            marker={"color": colors, "line": {"width": 0}},
            text=frame[text],
            textposition="outside",
            textfont={"color": palette.ink_secondary, "size": 11},
            customdata=frame[[label, text, *hover]].to_numpy(),
            hovertemplate=template + "<extra></extra>",
            cliponaxis=False,
        )
    )
    _reference_line(figure, palette, x=0)
    figure.update_xaxes(title_text=_axis_title(value_title), tickformat=tickformat)
    if len(frame):
        # Room beyond the longest bar on each side for its value label.
        low, high = min(frame[value].min(), 0), max(frame[value].max(), 0)
        reach = (high - low) * LABEL_ROOM
        figure.update_xaxes(range=[low - reach if low < 0 else 0, high + reach if high > 0 else 0])
    figure.update_yaxes(
        autorange="reversed",
        showgrid=False,
        tickfont={"color": palette.ink, "size": 12},
        ticksuffix=LABEL_GAP,
    )
    return figure


def diverging_columns(
    frame: pd.DataFrame,
    *,
    x: str,
    value: str,
    text: str,
    palette: Palette,
    value_title: str,
    tickformat: str = "",
    hover: Sequence[str] = (),
    marked: str | None = None,
    marked_label: str = "",
    height: int = 320,
) -> go.Figure:
    """Columns above and below zero along an ordered axis, such as seasons.

    ``marked`` is a boolean column; marked columns get a dot above them, explained by
    ``marked_label`` in the corner.
    """
    figure = _base(palette, height=height)
    colors = [palette.positive if number >= 0 else palette.negative for number in frame[value]]
    template = "<b>%{x}</b><br>%{customdata[0]}"
    template += "".join(f"<br>%{{customdata[{n}]}}" for n in range(1, len(hover) + 1))
    figure.add_trace(
        go.Bar(
            x=frame[x],
            y=frame[value],
            marker={"color": colors, "line": {"width": 0}},
            customdata=frame[[text, *hover]].to_numpy(),
            hovertemplate=template + "<extra></extra>",
        )
    )
    if marked is not None and frame[marked].any():
        rows = frame[frame[marked].astype(bool)]
        figure.add_trace(
            go.Scatter(
                x=rows[x],
                y=rows[value],
                mode="markers",
                marker={
                    "size": MARKER_SIZE,
                    "symbol": "star",
                    "color": palette.ink,
                    "line": {"color": palette.surface, "width": RING_WIDTH},
                },
                hoverinfo="skip",
                cliponaxis=False,
            )
        )
        figure.update_layout(margin={"t": 30})
        _note(
            figure, palette, f"★ {marked_label}", x=1, y=1, xref="paper", yref="paper",
            xanchor="right", yanchor="bottom",
        )  # fmt: skip
    _reference_line(figure, palette, y=0)
    figure.update_layout(bargap=0.45)
    figure.update_xaxes(type="category", showgrid=False, tickangle=-45)
    figure.update_yaxes(title_text=value_title, tickformat=tickformat)
    return figure


def percentile_bars(
    frame: pd.DataFrame,
    *,
    percentile: str,
    label: str,
    text: str,
    palette: Palette,
    hover: Sequence[str] = (),
    group: str | None = None,
    axis_title: str = "Percentile (higher is better)",
) -> go.Figure:
    """Where one player or team stands on a set of metrics, as bars from 0 to 100.

    Every bar is the same hue: the bar's length is the message. ``text`` is the column
    of ready-made values written at each bar's tip. ``group`` is a column whose changes
    are marked by a hairline between rows, to set categories apart.
    """
    figure = _base(palette, height=ROW_HEIGHT * len(frame) + 64)
    template = "<b>%{customdata[0]}</b><br>%{customdata[1]}"
    template += "".join(f"<br>%{{customdata[{n}]}}" for n in range(2, len(hover) + 2))
    figure.add_trace(
        go.Bar(
            x=frame[percentile],
            y=frame[label],
            orientation="h",
            width=BAR_THICKNESS / ROW_HEIGHT,
            marker={"color": palette.accent, "line": {"width": 0}},
            text=frame[text],
            textposition="outside",
            textfont={"color": palette.ink_secondary, "size": 11},
            customdata=frame[[label, text, *hover]].to_numpy(),
            hovertemplate=template + "<extra></extra>",
            cliponaxis=False,
        )
    )
    _reference_line(figure, palette, x=50)
    if group is not None:
        groups = frame[group].tolist()
        for row in range(1, len(groups)):
            if groups[row] != groups[row - 1]:
                figure.add_hline(
                    y=row - 0.5, line={"color": palette.grid, "width": HAIRLINE}, layer="below"
                )
    figure.update_xaxes(
        # Past 100 there is only room for the value written at the tip of a full bar.
        range=[0, 100 * (1 + LABEL_ROOM)],
        tickvals=[0, 25, 50, 75, 100],
        title_text=_axis_title(axis_title),
    )
    figure.update_yaxes(
        autorange="reversed",
        showgrid=False,
        tickfont={"color": palette.ink, "size": 12},
        ticksuffix=LABEL_GAP,
    )
    return figure


def _ordered_axis(figure: go.Figure, palette: Palette, *, categories: int | None) -> None:
    """The x-axis of a line chart: no grid, a hairline under the pointer, level labels.

    ``categories`` is the number of points when the axis is a list of labels (seasons),
    and ``None`` when it is a span of time.
    """
    figure.update_layout(hovermode="x unified")
    figure.update_xaxes(
        showgrid=False,
        showspikes=True,
        spikemode="across",
        spikethickness=HAIRLINE,
        spikecolor=palette.axis,
        spikedash="solid",
    )
    if categories is None:
        # A few dates read better than many. Plotly sets them level where they fit and at a
        # slant where they would not: held level, three dates on Team Explorer's form chart
        # printed on top of each other at 1024px (UI polish P4).
        figure.update_xaxes(nticks=TIME_TICKS)
    else:
        figure.update_xaxes(type="category", nticks=8, range=[-0.6, categories - 0.4])


def line(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    text: str,
    palette: Palette,
    y_title: str = "",
    tickformat: str = "",
    reference: float | None = None,
    reference_label: str = "",
    baseline_zero: bool = False,
    area: bool = False,
    marked: Sequence[object] = (),
    categorical_x: bool = False,
    height: int = 300,
) -> go.Figure:
    """One series over an ordered axis.

    ``text`` is the column of ready-made values for the tooltip. The last point carries
    an end dot; ``marked`` lists x values that get a dot too. ``reference`` draws a
    hairline at a value on the y-axis, named by ``reference_label``.
    """
    figure = _base(palette, height=height)
    if reference is not None:
        _reference_line(figure, palette, y=reference)
        if reference_label:
            # In the margin, level with its hairline, where the line can never cross it.
            figure.update_layout(margin={"r": REFERENCE_MARGIN})
            _note(
                figure, palette, reference_label, x=1, y=reference, xref="paper",
                xanchor="left", yanchor="middle", xshift=6, align="left",
            )  # fmt: skip
    if baseline_zero:
        _reference_line(figure, palette, y=0)
    figure.add_trace(
        go.Scatter(
            x=frame[x],
            y=frame[y],
            mode="lines",
            line={"color": palette.accent, "width": LINE_WIDTH, "shape": "linear"},
            fill="tozeroy" if area else None,
            fillcolor=palette.wash(palette.accent) if area else None,
            customdata=frame[[text]].to_numpy(),
            hovertemplate="%{customdata[0]}<extra></extra>",
        )
    )
    dots = frame[frame[x].isin(list(marked))]
    if len(frame):
        dots = pd.concat([dots, frame.tail(1)]).drop_duplicates(subset=x)
    figure.add_trace(
        go.Scatter(
            x=dots[x],
            y=dots[y],
            mode="markers",
            marker={
                "size": MARKER_SIZE - 2,
                "color": palette.accent,
                "line": {"color": palette.surface, "width": RING_WIDTH},
            },
            hoverinfo="skip",
            cliponaxis=False,
        )
    )
    _ordered_axis(figure, palette, categories=len(frame) if categorical_x else None)
    figure.update_yaxes(title_text=y_title, tickformat=tickformat)
    return figure


def lines(
    frame: pd.DataFrame,
    *,
    x: str,
    series: Mapping[str, str],
    text: Mapping[str, str],
    palette: Palette,
    y_title: str = "",
    tickformat: str = "",
    baseline_zero: bool = False,
    categorical_x: bool = False,
    height: int = 320,
    x_title: str = "",
    x_dtick: float | None = None,
) -> go.Figure:
    """Several series over one ordered axis, on one scale, with a legend.

    ``series`` maps a column of ``frame`` to the name it is shown under, in slot order;
    ``text`` maps the same columns to columns of ready-made tooltip values.
    """
    if len(series) > MAX_LINE_SERIES:
        raise ValueError(f"a line chart carries {MAX_LINE_SERIES} series, not {len(series)}")
    figure = _base(palette, height=height, legend=True)
    if baseline_zero:
        _reference_line(figure, palette, y=0)
    for color, (column, title) in zip(palette.series, series.items(), strict=False):
        figure.add_trace(
            go.Scatter(
                x=frame[x],
                y=frame[column],
                mode="lines",
                name=title,
                line={"color": color, "width": LINE_WIDTH},
                customdata=frame[[text[column]]].to_numpy(),
                hovertemplate="%{customdata[0]}<extra>" + title + "</extra>",
            )
        )
    _ordered_axis(figure, palette, categories=len(frame) if categorical_x else None)
    figure.update_yaxes(title_text=y_title, tickformat=tickformat)
    if x_title:
        figure.update_xaxes(title_text=_axis_title(x_title))
    if x_dtick is not None:
        figure.update_xaxes(dtick=x_dtick)
    return figure


def stacked_bars(
    frame: pd.DataFrame,
    *,
    label: str,
    parts: Mapping[str, str],
    text: Mapping[str, str],
    palette: Palette,
    value_title: str,
    tickformat: str = "",
    thresholds: Mapping[str, float] | None = None,
    highlight: Sequence[object] = (),
) -> go.Figure:
    """Horizontal bars built from parts, in the order given, with labelled thresholds.

    ``parts`` maps a column to the name of that part; ``text`` maps the same columns to
    columns of ready-made tooltip values. A gap in the surface colour separates the
    parts of a bar. ``thresholds`` maps a name to a value on the axis and draws a
    hairline there with the name above it.
    """
    if len(parts) > len(palette.series):
        raise ValueError(f"a bar stacks {len(palette.series)} parts, not {len(parts)}")
    figure = _base(palette, height=ROW_HEIGHT * len(frame) + 96, legend=len(parts) > 1)
    chosen = frame.index.isin(list(highlight))
    names = [
        f"<b>{title}</b>" if bold else title
        for title, bold in zip(frame[label], chosen, strict=True)
    ]
    for color, (column, title) in zip(palette.series, parts.items(), strict=False):
        figure.add_trace(
            go.Bar(
                x=frame[column],
                y=names,
                orientation="h",
                name=title,
                width=BAR_THICKNESS / ROW_HEIGHT,
                marker={"color": color, "line": {"color": palette.surface, "width": RING_WIDTH}},
                customdata=frame[[label, text[column]]].to_numpy(),
                hovertemplate="<b>%{customdata[0]}</b><br>" + title + ": %{customdata[1]}"
                "<extra></extra>",
            )
        )
    _thresholds(figure, palette, thresholds or {})
    figure.update_layout(
        barmode="stack",
        margin={"t": 64, "r": 28},
        legend={"traceorder": "normal"},
    )
    figure.update_xaxes(
        title_text=_axis_title(value_title), tickformat=tickformat, rangemode="tozero"
    )
    figure.update_yaxes(
        autorange="reversed",
        showgrid=False,
        tickfont={"color": palette.ink, "size": 12},
        ticksuffix=LABEL_GAP,
    )
    return figure


def histogram(
    values: pd.Series,
    *,
    palette: Palette,
    x_title: str,
    tickformat: str = "",
    marker: float | None = None,
    marker_label: str = "",
    bins: int = 30,
    height: int = 300,
) -> go.Figure:
    """How one metric is spread across a group, with one value optionally marked."""
    figure = _base(palette, height=height)
    figure.add_trace(
        go.Histogram(
            x=values.dropna(),
            nbinsx=bins,
            marker={"color": palette.accent, "line": {"color": palette.surface, "width": 1}},
            hovertemplate="%{x}<br>%{y} in this range<extra></extra>",
        )
    )
    if marker is not None and marker == marker:
        figure.add_vline(x=marker, line={"color": palette.ink, "width": LINE_WIDTH})
        spread = values.dropna()
        span = (spread.min(), spread.max()) if len(spread) else (marker, marker)
        _note(
            figure, palette, marker_label, x=marker, y=1, yref="paper", yanchor="bottom",
            xanchor=_side(marker, span),
        )  # fmt: skip
    figure.update_layout(bargap=0.04, margin={"t": 28})
    # The value labels sit a little lower than the house's, clear of the count axis's "0" in
    # the corner they share (UI polish P4).
    figure.update_xaxes(
        title_text=_axis_title(x_title), tickformat=tickformat, showgrid=False,
        ticklabelstandoff=10,
    )  # fmt: skip
    figure.update_yaxes(title_text="Count")
    return figure


def comparison_dots(
    frame: pd.DataFrame,
    *,
    metric: str,
    who: str,
    percentile: str,
    text: str,
    palette: Palette,
    axis_title: str = "Percentile (higher is better)",
    axis_range: Sequence[float] = (-2, 102),
    tickvals: Sequence[float] | None = (0, 25, 50, 75, 100),
    tickformat: str = "",
    reference: float | None = 50,
) -> go.Figure:
    """Several players or teams on the same metrics: one row per metric, one dot each.

    ``frame`` is tidy: one row per metric per subject, in display order. A hairline
    joins the dots of a row so the gap between subjects reads at a glance. By default
    the axis is a percentile; ``axis_title``, ``axis_range``, ``tickvals``,
    ``tickformat`` and ``reference`` make it any other scale - a chance before and after
    a change, say.
    """
    subjects = list(dict.fromkeys(frame[who]))
    if len(subjects) > MAX_SCATTER_SERIES:
        raise ValueError(f"compare at most {MAX_SCATTER_SERIES}, not {len(subjects)}")
    metrics = list(dict.fromkeys(frame[metric]))
    figure = _base(palette, height=ROW_HEIGHT * len(metrics) + 96, legend=True)
    if reference is not None:
        _reference_line(figure, palette, x=reference)
    spans = frame.groupby(metric, sort=False)[percentile].agg(["min", "max"])
    for name, span in spans.iterrows():
        figure.add_shape(
            type="line", x0=span["min"], x1=span["max"], y0=name, y1=name,
            line={"color": palette.axis, "width": LINE_WIDTH}, layer="below",
        )  # fmt: skip
    for color, subject in zip(palette.series, subjects, strict=False):
        rows = frame[frame[who] == subject]
        figure.add_trace(
            go.Scatter(
                x=rows[percentile],
                y=rows[metric],
                mode="markers",
                name=str(subject),
                marker={
                    "size": MARKER_SIZE + 2,
                    "color": color,
                    "line": {"color": palette.surface, "width": RING_WIDTH},
                },
                customdata=rows[[who, metric, text]].to_numpy(),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}: %{customdata[2]}"
                "<extra></extra>",
                cliponaxis=False,
            )
        )
    figure.update_xaxes(
        range=list(axis_range),
        tickvals=None if tickvals is None else list(tickvals),
        tickformat=tickformat,
        title_text=_axis_title(axis_title),
    )
    figure.update_yaxes(
        type="category",
        categoryorder="array",
        categoryarray=metrics,
        autorange="reversed",
        showgrid=False,
        tickfont={"color": palette.ink, "size": 12},
    )
    return figure


def interval_columns(
    frame: pd.DataFrame,
    *,
    label: str,
    value: str,
    low: str,
    high: str,
    text: str,
    palette: Palette,
    value_title: str = "",
    tickformat: str = ".0%",
    height: int = 340,
) -> go.Figure:
    """A share for each band of something, with the interval the true share may lie in.

    One column per row of ``frame``, in order. ``label`` is the band in words; it may
    carry a second line, such as the number of cases behind the share. ``low`` and
    ``high`` are the ends of the interval, drawn as a thin line through the top of the
    column: a tall line on a short column is a share that rests on very little.
    ``text`` is the ready-made tooltip.
    """
    figure = _base(palette, height=height)
    figure.add_trace(
        go.Bar(
            x=frame[label],
            y=frame[value],
            marker={"color": palette.accent, "line": {"width": 0}},
            customdata=frame[[text]].to_numpy(),
            hovertemplate="%{customdata[0]}<extra></extra>",
        )
    )
    across: list[object] = []
    up: list[object] = []
    for name, bottom, top in zip(frame[label], frame[low], frame[high], strict=True):
        across += [name, name, None]
        up += [bottom, top, None]
    figure.add_trace(
        go.Scatter(
            x=across,
            y=up,
            mode="lines",
            line={"color": palette.ink_secondary, "width": LINE_WIDTH},
            hoverinfo="skip",
        )
    )
    # Columns no thicker than the house allows, on a plot of typical width.
    crowded = MAX_BAR_THICKNESS * max(len(frame), 1) / COLUMN_PLOT_WIDTH
    figure.update_layout(bargap=min(max(1 - crowded, 0.3), 0.9))
    # Level labels: a label carries a second line (how many cases), and tilted, two-line
    # labels garble into each other (tried at UI polish P4).
    figure.update_xaxes(type="category", showgrid=False, tickangle=0)
    if len(frame) >= STAGGER_FROM:
        # Many columns: the labels take turns on two levels, each with two columns' room,
        # so they stay apart in a narrower window - at 1024px fourteen ran together (P5).
        figure.update_xaxes(showticklabels=False)
        for position, name in enumerate(frame[label]):
            figure.add_annotation(
                text=str(name), x=name, y=0, xref="x", yref="paper", yanchor="top",
                showarrow=False, font={"color": palette.ink_muted, "size": 12},
                yshift=-6 - LABEL_LEVEL * (position % 2),
            )  # fmt: skip
        figure.update_layout(margin={"b": 8 + 2 * LABEL_LEVEL})
    figure.update_yaxes(title_text=value_title, tickformat=tickformat, rangemode="tozero")
    return figure


def interval_rows(
    frame: pd.DataFrame,
    *,
    label: str,
    value: str,
    low: str,
    high: str,
    text: str,
    palette: Palette,
    inner_low: str | None = None,
    inner_high: str | None = None,
    value_title: str = "",
    tickformat: str = "",
    reference: float | None = None,
    reference_label: str = "",
    axis_range: Sequence[float] | None = None,
    tickvals: Sequence[float] | None = None,
) -> go.Figure:
    """One row per item: a dot at its value on a thin line spanning an interval.

    The line runs from ``low`` to ``high``. With ``inner_low`` and ``inner_high`` a
    thicker band is drawn inside it - the middle half of a group inside its middle 80%,
    say. ``reference`` draws a hairline at a value, named by ``reference_label`` above
    the plot; the value axis then fits the intervals and the reference together.
    ``axis_range`` fixes the value axis instead; give it high-to-low to put the better
    end on the right when lower is better, as with a rank.
    """
    labels = list(frame[label])
    figure = _base(palette, height=ROW_HEIGHT * len(frame) + 76)
    if axis_range is None and len(frame) and frame[low].notna().any():
        # Dots mark positions, so the axis need not start at zero. It fits the intervals and
        # the line the dots are read against, with room either side so that no interval
        # ends on the chart's edge (UI polish P4).
        left, right = frame[low].min(), frame[high].max()
        if reference is not None:
            left, right = min(left, reference), max(right, reference)
        room = (right - left) * LABEL_ROOM / 2 or 1.0
        axis_range = (left - room, right + room)
    if reference is not None:
        _reference_line(figure, palette, x=reference)
        if reference_label:
            # Room above the plot for the name of the line, which runs away from the edge
            # it sits near so that it stays on the chart.
            figure.update_layout(margin={"t": 30})
            side = _side(reference, axis_range) if axis_range is not None else "center"
            _note(
                figure, palette, reference_label, x=reference, y=1, yref="paper",
                yanchor="bottom", xanchor=side, yshift=4,
            )  # fmt: skip
    across: list[object] = []
    down: list[object] = []
    for name, left, right in zip(labels, frame[low], frame[high], strict=True):
        across += [left, right, None]
        down += [name, name, None]
    figure.add_trace(
        go.Scatter(
            x=across,
            y=down,
            mode="lines",
            line={"color": palette.deemphasis, "width": LINE_WIDTH},
            hoverinfo="skip",
        )
    )
    if inner_low is not None and inner_high is not None:
        bands = zip(frame[inner_low], frame[inner_high], strict=True)
        for position, (left, right) in enumerate(bands):
            if pd.isna(left) or pd.isna(right):
                continue
            figure.add_shape(
                type="rect", x0=left, x1=right,
                y0=position - BAND_THICKNESS, y1=position + BAND_THICKNESS,
                fillcolor=palette.deemphasis, line={"width": 0}, layer="below",
            )  # fmt: skip
    figure.add_trace(
        go.Scatter(
            x=frame[value],
            y=labels,
            mode="markers",
            marker={
                "size": MARKER_SIZE,
                "color": palette.accent,
                "line": {"color": palette.surface, "width": RING_WIDTH},
            },
            customdata=frame[[text]].to_numpy(),
            hovertemplate="%{customdata[0]}<extra></extra>",
            cliponaxis=False,
        )
    )
    figure.update_xaxes(title_text=_axis_title(value_title), tickformat=tickformat)
    if axis_range is not None:
        figure.update_xaxes(range=list(axis_range))
    if tickvals is not None:
        figure.update_xaxes(tickvals=list(tickvals))
    figure.update_yaxes(
        type="category",
        categoryorder="array",
        categoryarray=labels,
        autorange="reversed",
        showgrid=False,
        tickfont={"color": palette.ink, "size": 12},
        ticksuffix=LABEL_GAP,
    )
    return figure


def meter(
    *,
    value: float,
    value_text: str,
    thresholds: Mapping[str, float],
    palette: Palette,
    tickformat: str = "",
    estimated: bool = False,
) -> go.Figure:
    """One amount against a ladder of thresholds: a payroll against the cap lines.

    The bar is the amount; each threshold is a hairline with its name above. The bar
    takes the accent, or the de-emphasis gray when ``estimated`` says the amount is
    incomplete.
    """
    figure = _base(palette, height=132 + THRESHOLD_ROW)
    figure.add_trace(
        go.Bar(
            x=[value],
            y=[""],
            orientation="h",
            width=0.5,
            marker={
                "color": palette.deemphasis if estimated else palette.accent,
                "line": {"width": 0},
            },
            customdata=[[value_text]],
            hovertemplate="%{customdata[0]}<extra></extra>",
        )
    )
    _thresholds(figure, palette, thresholds)
    upper = max([value, *thresholds.values()]) * 1.04 if thresholds else None
    figure.update_layout(margin={"t": 44 + THRESHOLD_ROW, "b": 8, "r": 28})
    figure.update_xaxes(tickformat=tickformat, range=[0, upper] if upper else None)
    figure.update_yaxes(showgrid=False, showticklabels=False)
    return figure


def band_line(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    low: str,
    high: str,
    text: str,
    palette: Palette,
    x_title: str = "",
    y_title: str = "",
    x_tickformat: str = "",
    tickformat: str = "",
    reference: float | None = None,
    reference_label: str = "",
    marked: Sequence[object] = (),
    height: int = 320,
) -> go.Figure:
    """One estimate over an ordered numeric axis, with the interval it may lie in.

    The line is the estimate; the wash behind it runs from ``low`` to ``high``, so a wide
    band is an estimate that rests on little. ``text`` is the column of ready-made
    tooltip values. The last point carries an end dot; ``marked`` lists x values that get
    one too. ``reference`` draws a hairline at a value on the y-axis, named by
    ``reference_label`` in the margin.
    """
    figure = _base(palette, height=height)
    if reference is not None:
        _reference_line(figure, palette, y=reference)
        if reference_label:
            figure.update_layout(margin={"r": REFERENCE_MARGIN})
            _note(
                figure, palette, reference_label, x=1, y=reference, xref="paper",
                xanchor="left", yanchor="middle", xshift=6, align="left",
            )  # fmt: skip
    for column, fill in ((low, None), (high, "tonexty")):
        figure.add_trace(
            go.Scatter(
                x=frame[x],
                y=frame[column],
                mode="none",
                fill=fill,
                fillcolor=palette.wash(palette.accent) if fill else None,
                hoverinfo="skip",
                showlegend=False,
            )
        )
    figure.add_trace(
        go.Scatter(
            x=frame[x],
            y=frame[y],
            mode="lines",
            line={"color": palette.accent, "width": LINE_WIDTH, "shape": "linear"},
            customdata=frame[[text]].to_numpy(),
            hovertemplate="%{customdata[0]}<extra></extra>",
        )
    )
    dots = frame[frame[x].isin(list(marked))]
    if len(frame):
        dots = pd.concat([dots, frame.tail(1)]).drop_duplicates(subset=x)
    figure.add_trace(
        go.Scatter(
            x=dots[x],
            y=dots[y],
            mode="markers",
            marker={
                "size": MARKER_SIZE - 2,
                "color": palette.accent,
                "line": {"color": palette.surface, "width": RING_WIDTH},
            },
            hoverinfo="skip",
            cliponaxis=False,
        )
    )
    figure.update_layout(hovermode="x unified")
    figure.update_xaxes(
        title_text=_axis_title(x_title),
        tickformat=x_tickformat,
        showgrid=False,
        showspikes=True,
        spikemode="across",
        spikethickness=HAIRLINE,
        spikecolor=palette.axis,
        spikedash="solid",
    )
    figure.update_yaxes(title_text=y_title, tickformat=tickformat)
    return figure
