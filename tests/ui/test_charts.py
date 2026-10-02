"""The chart builders: each draws what it is given, by the house rules, and nothing else."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import plotly.graph_objects as go
import pytest

from wb import charts
from wb.theme import DARK, LIGHT, Palette

FRAME = pd.DataFrame(
    {
        "x": [1.0, 2.0, 3.0, 4.0],
        "y": [4.0, -3.0, 2.5, 1.0],
        "name": ["Alpha", "Bravo", "Charlie", "Delta"],
        "text": ["one", "two", "three", "four"],
        "group": ["Guard", "Forward", "Guard", "Center"],
        "percentile": [10.0, 55.0, 80.0, 99.0],
        "flag": [False, True, False, False],
    },
    index=pd.Index([10, 20, 30, 40], name="id"),
)
TIDY = pd.DataFrame(
    {
        "metric": ["PPG", "PPG", "TS%", "TS%"],
        "who": ["Alpha", "Bravo", "Alpha", "Bravo"],
        "percentile": [80.0, 40.0, 30.0, 60.0],
        "text": ["25.0", "12.0", "55%", "60%"],
    }
)


def scatter(palette: Palette, **kwargs) -> go.Figure:
    arguments = {"x": "x", "y": "y", "name": "name", "x_title": "X", "y_title": "Y"}
    return charts.scatter(FRAME, palette=palette, **(arguments | kwargs))


BUILDERS: dict[str, Callable[[Palette], go.Figure]] = {
    "scatter": lambda p: scatter(p, hover=["text"], label="name", highlight=[20]),
    "scatter_groups": lambda p: scatter(p, group="group", x_reference=2.0, y_reference=0.0),
    "diverging_bars": lambda p: charts.diverging_bars(
        FRAME, value="y", label="name", text="text", palette=p, value_title="Net"
    ),
    "diverging_columns": lambda p: charts.diverging_columns(
        FRAME,
        x="name",
        value="y",
        text="text",
        palette=p,
        value_title="Net",
        marked="flag",
        marked_label="Champion",
    ),  # fmt: skip
    "percentile_bars": lambda p: charts.percentile_bars(
        FRAME, percentile="percentile", label="name", text="text", palette=p, group="group"
    ),
    "line": lambda p: charts.line(
        FRAME,
        x="x",
        y="y",
        text="text",
        palette=p,
        reference=1.0,
        reference_label="Season",
        baseline_zero=True,
        area=True,
        marked=[2.0],
    ),  # fmt: skip
    "lines": lambda p: charts.lines(
        FRAME,
        x="x",
        series={"y": "Net", "percentile": "Rank"},
        text={"y": "text", "percentile": "text"},
        palette=p,
    ),  # fmt: skip
    "stacked_bars": lambda p: charts.stacked_bars(
        FRAME,
        label="name",
        parts={"x": "Active", "percentile": "Dead"},
        text={"x": "text", "percentile": "text"},
        palette=p,
        value_title="Salary",
        thresholds={"Cap": 50.0, "Tax": 80.0},
    ),  # fmt: skip
    "histogram": lambda p: charts.histogram(
        FRAME["y"], palette=p, x_title="Y", marker=1.0, marker_label="Alpha"
    ),
    "comparison_dots": lambda p: charts.comparison_dots(
        TIDY, metric="metric", who="who", percentile="percentile", text="text", palette=p
    ),
    "meter": lambda p: charts.meter(
        value=105.0, value_text="$105", thresholds={"Cap": 100.0, "Tax": 120.0}, palette=p
    ),
}
EVERY_CHART = pytest.mark.parametrize("build", BUILDERS.values(), ids=BUILDERS.keys())
BOTH_MODES = pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])


class TestHouseRules:
    """What is true of every chart, whatever it shows."""

    @EVERY_CHART
    @BOTH_MODES
    def test_one_scale_per_chart(self, build, palette: Palette) -> None:
        layout = build(palette).to_dict()["layout"]
        assert "yaxis2" not in layout and "xaxis2" not in layout

    @EVERY_CHART
    @BOTH_MODES
    def test_surface_and_ink_come_from_the_palette(self, build, palette: Palette) -> None:
        layout = build(palette).layout
        assert layout.paper_bgcolor == layout.plot_bgcolor == palette.surface
        assert layout.font.color == palette.ink
        assert layout.xaxis.gridcolor == layout.yaxis.gridcolor == palette.grid

    @EVERY_CHART
    def test_nothing_is_dashed(self, build) -> None:
        figure = build(LIGHT)
        assert figure.layout.xaxis.griddash == figure.layout.yaxis.griddash == "solid"
        for shape in figure.layout.shapes:
            assert shape.line.dash in (None, "solid")
        for trace in figure.data:
            if trace.type == "scatter" and trace.line is not None:
                assert trace.line.dash in (None, "solid")

    @EVERY_CHART
    @BOTH_MODES
    def test_text_is_ink_never_a_series_colour(self, build, palette: Palette) -> None:
        figure = build(palette)
        ink = {palette.ink, palette.ink_secondary, palette.ink_muted}
        for annotation in figure.layout.annotations:
            assert annotation.font.color in ink
        for axis in (figure.layout.xaxis, figure.layout.yaxis):
            assert axis.tickfont.color in ink
        for trace in figure.data:
            textfont = getattr(trace, "textfont", None)
            if textfont is not None and textfont.color is not None:
                assert textfont.color in ink

    @EVERY_CHART
    def test_one_series_has_no_legend_and_several_always_do(self, build) -> None:
        figure = build(LIGHT)
        named = [trace for trace in figure.data if trace.showlegend is not False and trace.name]
        if figure.layout.showlegend:
            assert len(named) >= 2
        else:
            assert len({trace.name for trace in figure.data if trace.name}) <= 1

    @EVERY_CHART
    def test_markers_are_big_enough_and_ringed_in_the_surface(self, build) -> None:
        for trace in build(DARK).data:
            if trace.type == "scatter" and "markers" in (trace.mode or ""):
                assert trace.marker.size >= 8
                assert trace.marker.line.color == DARK.surface
                assert trace.marker.line.width == charts.RING_WIDTH

    @EVERY_CHART
    def test_lines_are_thin(self, build) -> None:
        for trace in build(LIGHT).data:
            if trace.type == "scatter" and "lines" in (trace.mode or ""):
                assert trace.line.width == charts.LINE_WIDTH == 2

    @EVERY_CHART
    def test_the_figure_is_valid_plotly(self, build) -> None:
        assert build(LIGHT).to_dict()["data"]

    def test_bars_are_thin_with_a_rounded_data_end(self) -> None:
        assert charts.BAR_THICKNESS <= 24
        figure = BUILDERS["diverging_bars"](LIGHT)
        assert figure.layout.barcornerradius == charts.CORNER_RADIUS == 4
        assert figure.data[0].width == charts.BAR_THICKNESS / charts.ROW_HEIGHT

    def test_the_toolbar_saves_a_named_image_at_twice_the_size(self) -> None:
        config = charts.image_config("net_rating_2025-26")
        assert config["toImageButtonOptions"] == {
            "format": "png",
            "scale": 2,
            "filename": "net_rating_2025-26",
        }
        assert config["displaylogo"] is False
        assert "filename" not in charts.MODEBAR["toImageButtonOptions"]


class TestScatter:
    def test_a_single_series_is_one_hue(self) -> None:
        figure = scatter(LIGHT)
        assert len(figure.data) == 1
        assert figure.data[0].marker.color == LIGHT.accent
        assert not figure.layout.showlegend

    def test_a_highlight_takes_the_accent_and_the_rest_recede(self) -> None:
        figure = scatter(LIGHT, highlight=[20])
        rest, chosen = figure.data
        assert rest.marker.color == LIGHT.deemphasis and len(rest.x) == 3
        assert chosen.marker.color == LIGHT.accent and list(chosen.x) == [2.0]
        assert chosen.marker.size > rest.marker.size

    def test_a_highlight_that_is_not_in_the_data_changes_nothing(self) -> None:
        figure = scatter(LIGHT, highlight=[999])
        assert len(figure.data) == 1 and figure.data[0].marker.color == LIGHT.accent

    def test_groups_take_the_leading_slots_in_order_with_a_legend(self) -> None:
        figure = scatter(LIGHT, group="group")
        assert [trace.name for trace in figure.data] == ["Guard", "Forward", "Center"]
        assert [trace.marker.color for trace in figure.data] == list(LIGHT.series[:3])
        assert figure.layout.showlegend

    def test_more_groups_than_a_scatter_can_tell_apart_is_an_error(self) -> None:
        frame = FRAME.assign(group=["a", "b", "c", "d"])
        with pytest.raises(ValueError, match="3 groups apart, not 4"):
            charts.scatter(
                frame, x="x", y="y", name="name", palette=LIGHT, x_title="X", y_title="Y",
                group="group",
            )  # fmt: skip

    def test_a_highlighted_member_of_a_group_keeps_its_groups_colour(self) -> None:
        figure = scatter(LIGHT, group="group", highlight=[10])
        guards = [trace for trace in figure.data if trace.marker.color == LIGHT.series[0]]
        assert len(guards) == 2
        assert sorted(len(trace.x) for trace in guards) == [1, 1]
        assert sum(trace.showlegend for trace in guards) == 1

    def test_hover_shows_the_name_and_the_ready_made_text(self) -> None:
        figure = scatter(LIGHT, hover=["text"])
        trace = figure.data[0]
        assert trace.customdata[0].tolist() == ["Alpha", "one"]
        assert trace.hovertemplate == "<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>"

    def test_reference_lines_are_hairlines_beneath_the_data(self) -> None:
        figure = scatter(LIGHT, x_reference=2.5, y_reference=0.0, reference_label="League")
        assert len(figure.layout.shapes) == 2
        for shape in figure.layout.shapes:
            assert (shape.line.width, shape.line.color) == (1, LIGHT.axis)
            assert shape.layer == "below"
        assert [note.text for note in figure.layout.annotations] == ["League"]

    def test_a_reversed_axis_for_metrics_where_lower_is_better(self) -> None:
        assert scatter(LIGHT, reverse_y=True).layout.yaxis.autorange == "reversed"
        assert scatter(LIGHT).layout.yaxis.autorange is None

    def test_labels_are_written_beside_the_marks(self) -> None:
        trace = scatter(LIGHT, label="name").data[0]
        assert trace.mode == "markers+text"
        assert list(trace.text) == ["Alpha", "Bravo", "Charlie", "Delta"]
        assert set(trace.textposition) <= set(charts.LABEL_SIDES)


class TestLabelSides:
    def test_a_label_with_room_sits_above_its_mark(self) -> None:
        x, y = pd.Series([0.0, 10.0]), pd.Series([0.0, 10.0])
        assert charts.label_sides(x, y, pd.Series(["AAA", "BBB"])) == ["top center"] * 2

    def test_marks_on_top_of_each_other_get_different_sides(self) -> None:
        x = pd.Series([0.0, 5.0, 5.01, 10.0])
        y = pd.Series([0.0, 5.0, 5.01, 10.0])
        sides = charts.label_sides(x, y, pd.Series(["AAA", "BBB", "CCC", "DDD"]))
        assert sides[1] != sides[2]

    def test_a_crowd_spreads_over_all_four_sides(self) -> None:
        x = pd.Series([0.0, 5.0, 5.02, 5.04, 5.06, 10.0])
        y = pd.Series([0.0, 5.0, 5.0, 5.0, 5.0, 10.0])
        sides = charts.label_sides(x, y, pd.Series(["AAA"] * 6))
        assert len(set(sides[1:5])) >= 3
        assert set(sides) <= set(charts.LABEL_SIDES)

    def test_a_reversed_axis_flips_which_way_is_up(self) -> None:
        x, y = pd.Series([0.0, 5.0, 5.0, 10.0]), pd.Series([0.0, 5.0, 5.4, 10.0])
        labels = pd.Series(["AAA"] * 4)
        upright = charts.label_sides(x, y, labels)
        flipped = charts.label_sides(x, y, labels, reverse_y=True)
        assert upright != flipped

    def test_no_marks_and_one_mark(self) -> None:
        empty = pd.Series([], dtype="float64")
        assert charts.label_sides(empty, empty, pd.Series([], dtype="str")) == []
        one = pd.Series([3.0])
        assert charts.label_sides(one, one, pd.Series(["AAA"])) == ["top center"]


class TestDivergingBars:
    def test_the_two_poles_say_which_side_of_zero(self) -> None:
        bar = BUILDERS["diverging_bars"](LIGHT).data[0]
        assert list(bar.marker.color) == [
            LIGHT.positive,
            LIGHT.negative,
            LIGHT.positive,
            LIGHT.positive,
        ]
        assert bar.orientation == "h"

    def test_zero_is_on_the_positive_side(self) -> None:
        frame = FRAME.assign(y=[0.0, -1.0, 1.0, 2.0])
        bar = charts.diverging_bars(
            frame, value="y", label="name", text="text", palette=LIGHT, value_title="Net"
        ).data[0]
        assert bar.marker.color[0] == LIGHT.positive

    def test_values_are_written_at_the_bar_tips_with_room_to_fit(self) -> None:
        figure = BUILDERS["diverging_bars"](LIGHT)
        bar = figure.data[0]
        assert list(bar.text) == ["one", "two", "three", "four"]
        assert bar.textposition == "outside"
        low, high = figure.layout.xaxis.range
        assert low < -3.0 and high > 4.0

    def test_rows_run_top_to_bottom_in_the_order_given(self) -> None:
        figure = BUILDERS["diverging_bars"](LIGHT)
        assert list(figure.data[0].y) == ["Alpha", "Bravo", "Charlie", "Delta"]
        assert figure.layout.yaxis.autorange == "reversed"

    def test_the_highlighted_row_is_set_in_bold(self) -> None:
        figure = charts.diverging_bars(
            FRAME, value="y", label="name", text="text", palette=LIGHT, value_title="Net",
            highlight=[30],
        )  # fmt: skip
        assert list(figure.data[0].y) == ["Alpha", "Bravo", "<b>Charlie</b>", "Delta"]

    def test_the_chart_grows_with_its_rows(self) -> None:
        short = BUILDERS["diverging_bars"](LIGHT).layout.height
        long = charts.diverging_bars(
            pd.concat([FRAME] * 3), value="y", label="name", text="text", palette=LIGHT,
            value_title="Net",
        ).layout.height  # fmt: skip
        assert long - short == 8 * charts.ROW_HEIGHT

    def test_no_rows(self) -> None:
        figure = charts.diverging_bars(
            FRAME.iloc[0:0], value="y", label="name", text="text", palette=LIGHT,
            value_title="Net",
        )  # fmt: skip
        assert len(figure.data[0].x) == 0


class TestDivergingColumns:
    def test_marked_columns_get_a_star_and_the_star_is_explained(self) -> None:
        figure = BUILDERS["diverging_columns"](LIGHT)
        bars, stars = figure.data
        assert list(stars.x) == ["Bravo"] and stars.marker.symbol == "star"
        assert [note.text for note in figure.layout.annotations] == ["★ Champion"]
        assert list(bars.marker.color)[1] == LIGHT.negative

    def test_nothing_marked_means_no_star_and_no_note(self) -> None:
        figure = charts.diverging_columns(
            FRAME.assign(flag=False), x="name", value="y", text="text", palette=LIGHT,
            value_title="Net", marked="flag", marked_label="Champion",
        )  # fmt: skip
        assert len(figure.data) == 1 and not figure.layout.annotations

    def test_the_axis_is_categorical_so_seasons_keep_their_order(self) -> None:
        assert BUILDERS["diverging_columns"](LIGHT).layout.xaxis.type == "category"


class TestPercentileBars:
    def test_bars_run_from_zero_to_a_hundred_in_one_hue(self) -> None:
        figure = BUILDERS["percentile_bars"](LIGHT)
        bar = figure.data[0]
        low, high = figure.layout.xaxis.range
        assert low == 0 and 105 < high < 120  # room past 100 for the label of a full bar
        assert list(figure.layout.xaxis.tickvals) == [0, 25, 50, 75, 100]
        assert bar.marker.color == LIGHT.accent
        assert list(bar.x) == [10.0, 55.0, 80.0, 99.0]
        assert list(bar.text) == ["one", "two", "three", "four"]

    def test_the_middle_of_the_group_is_marked(self) -> None:
        figure = charts.percentile_bars(
            FRAME, percentile="percentile", label="name", text="text", palette=LIGHT
        )
        assert [shape.x0 for shape in figure.layout.shapes] == [50]

    def test_a_hairline_separates_one_category_from_the_next(self) -> None:
        figure = BUILDERS["percentile_bars"](LIGHT)
        separators = [shape for shape in figure.layout.shapes if shape.y0 == shape.y1]
        # Guard, Forward, Guard, Center: the category changes three times.
        assert [shape.y0 for shape in separators] == [0.5, 1.5, 2.5]


class TestLine:
    def test_one_line_with_an_end_dot(self) -> None:
        figure = charts.line(FRAME, x="x", y="y", text="text", palette=LIGHT)
        line, dots = figure.data
        assert line.mode == "lines" and line.line.color == LIGHT.accent
        assert list(dots.x) == [4.0] and dots.mode == "markers"
        assert not figure.layout.showlegend

    def test_marked_points_get_a_dot_too(self) -> None:
        figure = charts.line(FRAME, x="x", y="y", text="text", palette=LIGHT, marked=[2.0])
        assert sorted(figure.data[1].x) == [2.0, 4.0]

    def test_marking_the_last_point_does_not_draw_it_twice(self) -> None:
        figure = charts.line(FRAME, x="x", y="y", text="text", palette=LIGHT, marked=[4.0])
        assert list(figure.data[1].x) == [4.0]

    def test_the_reference_is_named_in_the_margin_where_the_line_cannot_cross_it(self) -> None:
        figure = BUILDERS["line"](LIGHT)
        note = figure.layout.annotations[0]
        assert (note.text, note.xref, note.x, note.xanchor) == ("Season", "paper", 1, "left")
        assert note.y == 1.0
        assert figure.layout.margin.r == charts.REFERENCE_MARGIN

    def test_an_area_is_a_wash_never_a_block(self) -> None:
        line = BUILDERS["line"](LIGHT).data[0]
        assert line.fill == "tozeroy"
        assert line.fillcolor == LIGHT.wash(LIGHT.accent) and line.fillcolor.endswith(",0.1)")
        plain = charts.line(FRAME, x="x", y="y", text="text", palette=LIGHT).data[0]
        assert plain.fill is None

    def test_hovering_reads_the_value_at_that_position(self) -> None:
        figure = BUILDERS["line"](LIGHT)
        assert figure.layout.hovermode == "x unified"
        assert figure.layout.xaxis.showspikes and figure.layout.xaxis.spikedash == "solid"
        assert figure.data[0].customdata[0].tolist() == ["one"]

    def test_a_categorical_axis_keeps_its_first_label_clear_of_the_scale(self) -> None:
        figure = charts.line(FRAME, x="name", y="y", text="text", palette=LIGHT, categorical_x=True)
        assert figure.layout.xaxis.type == "category"
        assert list(figure.layout.xaxis.range) == [-0.6, 3.6]
        assert figure.layout.xaxis.tickangle is None  # labels may tilt when seasons crowd

    def test_dates_are_written_level_and_few(self) -> None:
        days = FRAME.assign(day=pd.date_range("2026-01-01", periods=len(FRAME), freq="7D"))
        single = charts.line(days, x="day", y="y", text="text", palette=LIGHT)
        several = charts.lines(
            days, x="day", series={"y": "One", "x": "Two"}, text={"y": "text", "x": "text"},
            palette=LIGHT,
        )  # fmt: skip
        for figure in (single, several):
            assert figure.layout.xaxis.tickangle == 0
            assert figure.layout.xaxis.nticks == charts.TIME_TICKS
            assert figure.layout.xaxis.type is None  # left to the data: a span of time

    def test_no_points(self) -> None:
        figure = charts.line(FRAME.iloc[0:0], x="x", y="y", text="text", palette=LIGHT)
        assert len(figure.data[0].x) == 0 and len(figure.data[1].x) == 0


class TestLines:
    def test_series_take_slots_in_order_and_share_one_tooltip(self) -> None:
        figure = BUILDERS["lines"](LIGHT)
        assert [trace.name for trace in figure.data] == ["Net", "Rank"]
        assert [trace.line.color for trace in figure.data] == list(LIGHT.series[:2])
        assert figure.layout.showlegend and figure.layout.hovermode == "x unified"

    def test_more_series_than_a_line_chart_carries_is_an_error(self) -> None:
        columns = {name: name for name in ("x", "y", "percentile", "a", "b")}
        frame = FRAME.assign(a=1.0, b=2.0)
        with pytest.raises(ValueError, match="carries 4 series, not 5"):
            charts.lines(frame, x="x", series=columns, text=columns, palette=LIGHT)


class TestStackedBars:
    def test_parts_stack_with_a_gap_in_the_surface_colour(self) -> None:
        figure = BUILDERS["stacked_bars"](DARK)
        assert figure.layout.barmode == "stack"
        assert [trace.name for trace in figure.data] == ["Active", "Dead"]
        for trace, color in zip(figure.data, DARK.series, strict=False):
            assert trace.marker.color == color
            assert (trace.marker.line.color, trace.marker.line.width) == (DARK.surface, 2)

    def test_thresholds_are_hairlines_named_above_the_plot(self) -> None:
        figure = BUILDERS["stacked_bars"](LIGHT)
        assert sorted(shape.x0 for shape in figure.layout.shapes) == [50.0, 80.0]
        assert [note.text for note in figure.layout.annotations] == ["Cap", "Tax"]

    def test_neighbouring_threshold_names_sit_on_different_rows(self) -> None:
        figure = charts.meter(
            value=10.0, value_text="10", palette=LIGHT,
            thresholds={"Tax": 80.0, "Cap": 50.0, "1st apron": 85.0, "2nd apron": 90.0},
        )  # fmt: skip
        notes = figure.layout.annotations
        assert [note.text for note in notes] == ["Cap", "Tax", "1st apron", "2nd apron"]
        shifts = [note.yshift for note in notes]
        assert shifts[0] == shifts[2] != shifts[1] == shifts[3]

    def test_one_part_needs_no_legend(self) -> None:
        figure = charts.stacked_bars(
            FRAME, label="name", parts={"x": "Salary"}, text={"x": "text"}, palette=LIGHT,
            value_title="Salary",
        )  # fmt: skip
        assert not figure.layout.showlegend and not figure.layout.shapes


class TestHistogram:
    def test_bins_are_one_hue_separated_by_the_surface(self) -> None:
        bars = BUILDERS["histogram"](LIGHT).data[0]
        assert bars.type == "histogram"
        assert (bars.marker.color, bars.marker.line.color) == (LIGHT.accent, LIGHT.surface)

    def test_the_marked_value_is_a_line_with_its_name(self) -> None:
        figure = BUILDERS["histogram"](LIGHT)
        assert [shape.x0 for shape in figure.layout.shapes] == [1.0]
        assert [note.text for note in figure.layout.annotations] == ["Alpha"]

    def test_a_missing_marker_draws_nothing(self) -> None:
        for marker in (None, float("nan")):
            figure = charts.histogram(FRAME["y"], palette=LIGHT, x_title="Y", marker=marker)
            assert not figure.layout.shapes and not figure.layout.annotations

    def test_missing_values_are_left_out(self) -> None:
        values = pd.Series([1.0, None, 3.0])
        assert list(charts.histogram(values, palette=LIGHT, x_title="Y").data[0].x) == [1.0, 3.0]


class TestComparisonDots:
    def test_one_dot_per_subject_per_metric_joined_by_a_hairline(self) -> None:
        figure = BUILDERS["comparison_dots"](LIGHT)
        assert [trace.name for trace in figure.data] == ["Alpha", "Bravo"]
        assert [trace.marker.color for trace in figure.data] == list(LIGHT.series[:2])
        joins = [shape for shape in figure.layout.shapes if shape.y0 == shape.y1]
        assert [(join.x0, join.x1) for join in joins] == [(40.0, 80.0), (30.0, 60.0)]
        assert figure.layout.showlegend

    def test_metrics_keep_the_order_they_were_given_in(self) -> None:
        figure = BUILDERS["comparison_dots"](LIGHT)
        assert list(figure.layout.yaxis.categoryarray) == ["PPG", "TS%"]

    def test_more_than_three_subjects_is_an_error(self) -> None:
        crowd = pd.concat([TIDY.assign(who=TIDY["who"] + suffix) for suffix in ("1", "2")])
        with pytest.raises(ValueError, match="at most 3, not 4"):
            charts.comparison_dots(
                crowd, metric="metric", who="who", percentile="percentile", text="text",
                palette=LIGHT,
            )  # fmt: skip


class TestMeter:
    def test_one_bar_against_named_thresholds(self) -> None:
        figure = BUILDERS["meter"](LIGHT)
        assert list(figure.data[0].x) == [105.0]
        assert figure.data[0].marker.color == LIGHT.accent
        assert sorted(shape.x0 for shape in figure.layout.shapes) == [100.0, 120.0]
        assert figure.layout.xaxis.range[1] > 120.0

    def test_an_incomplete_amount_is_drawn_in_gray(self) -> None:
        figure = charts.meter(
            value=50.0, value_text="50", thresholds={"Cap": 100.0}, palette=LIGHT, estimated=True
        )
        assert figure.data[0].marker.color == LIGHT.deemphasis

    def test_an_amount_past_every_threshold_still_fits(self) -> None:
        figure = charts.meter(
            value=300.0, value_text="300", thresholds={"Cap": 100.0}, palette=LIGHT
        )
        assert figure.layout.xaxis.range[1] > 300.0
