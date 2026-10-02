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
ROW_HEIGHT = 30
MARKER_SIZE = 10
LINE_WIDTH = 2
RING_WIDTH = 2
CORNER_RADIUS = 4
HAIRLINE = 1
LABEL_ROOM = 0.14
REFERENCE_MARGIN = 92
LABEL_GAP = "  "
THRESHOLD_ROW = 14
TIME_TICKS = 4
"""Pixels between the two rows that threshold names alternate on."""
"""Space between a category label and the start of its bar."""
"""Pixels kept at the right of a line chart for the name of its reference line."""
"""Share of a bar chart's value range left free past the longest bar, for its label."""

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
    figure: go.Figure, palette: Palette, *, x: float | None = None, y: float | None = None
) -> None:
    """A solid hairline marking a reference value, drawn beneath the data."""
    line = {"color": palette.axis, "width": HAIRLINE}
    if x is not None:
        figure.add_vline(x=x, line=line, layer="below")
    if y is not None:
        figure.add_hline(y=y, line=line, layer="below")


def _thresholds(figure: go.Figure, palette: Palette, thresholds: Mapping[str, float]) -> None:
    """Hairlines at named values on the x-axis, each with its name above the plot.

    Names alternate between two rows in order of value, so lines that sit close
    together - a tax line and an apron - keep their names apart.
    """
    ordered = sorted(thresholds.items(), key=lambda item: item[1])
    for position, (title, amount) in enumerate(ordered):
        _reference_line(figure, palette, x=amount)
        _note(
            figure, palette, title, x=amount, y=1, yref="paper", yanchor="bottom",
            xanchor="center", yshift=4 + THRESHOLD_ROW * (position % 2),
        )  # fmt: skip


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
    height: int = 480,
) -> go.Figure:
    """Two metrics against each other, one mark per row of ``frame``.

    ``name`` is the column naming each mark; ``hover`` lists columns of ready-made text
    shown under it. ``label`` writes a column's text beside every mark. ``group`` colours
    marks by a column with at most three values. ``highlight`` lists index values that
    are the subject: with no ``group`` they take the accent and everything else recedes
    to gray; with one they are drawn larger.
    """
    figure = _base(palette, height=height, legend=group is not None)
    _reference_line(figure, palette, x=x_reference, y=y_reference)
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

    figure.update_xaxes(title_text=x_title, tickformat=x_tickformat)
    figure.update_yaxes(title_text=y_title, tickformat=y_tickformat)
    if reverse_y:
        figure.update_yaxes(autorange="reversed")
    if reference_label and (x_reference is not None or y_reference is not None):
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
    figure.update_xaxes(title_text=value_title, tickformat=tickformat)
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
        title_text="Percentile (higher is better)",
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
        # A few dates written level read better than many written at a slant.
        figure.update_xaxes(tickangle=0, nticks=TIME_TICKS)
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
    figure.update_xaxes(title_text=value_title, tickformat=tickformat, rangemode="tozero")
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
        _note(
            figure, palette, marker_label, x=marker, y=1, yref="paper", yanchor="bottom",
            xanchor="center",
        )  # fmt: skip
    figure.update_layout(bargap=0.04, margin={"t": 28})
    figure.update_xaxes(title_text=x_title, tickformat=tickformat, showgrid=False)
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
) -> go.Figure:
    """Several players or teams on the same metrics: one row per metric, one dot each.

    ``frame`` is tidy: one row per metric per subject, in display order. A hairline
    joins the dots of a row so the gap between subjects reads at a glance.
    """
    subjects = list(dict.fromkeys(frame[who]))
    if len(subjects) > MAX_SCATTER_SERIES:
        raise ValueError(f"compare at most {MAX_SCATTER_SERIES}, not {len(subjects)}")
    metrics = list(dict.fromkeys(frame[metric]))
    figure = _base(palette, height=ROW_HEIGHT * len(metrics) + 96, legend=True)
    _reference_line(figure, palette, x=50)
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
        range=[-2, 102],
        tickvals=[0, 25, 50, 75, 100],
        title_text="Percentile (higher is better)",
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
    figure = _base(palette, height=132)
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
    figure.update_layout(margin={"t": 44, "b": 8, "r": 28})
    figure.update_xaxes(tickformat=tickformat, range=[0, upper] if upper else None)
    figure.update_yaxes(showgrid=False, showticklabels=False)
    return figure
