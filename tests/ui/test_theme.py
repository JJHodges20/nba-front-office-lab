"""The palette, checked by arithmetic rather than by eye.

Thresholds follow the chart-design method the workbench uses: neighbouring series must
differ by at least 15 for full colour vision and 8 under simulated colour blindness
(OKLab distance x 100); marks need 3:1 contrast against the surface unless the values
are also readable as text, which every chart's table view guarantees.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.ui.color_math import DEUTAN, PROTAN, contrast, difference, worst_separation
from wb.theme import DARK, LIGHT, MAX_LINE_SERIES, MAX_SCATTER_SERIES, Palette, palette

NORMAL_FLOOR = 15.0
COLOUR_BLIND_TARGET = 8.0
MARK_CONTRAST = 3.0
TEXT_CONTRAST = 4.5

PALETTES = pytest.mark.parametrize("colors", [LIGHT, DARK], ids=["light", "dark"])


@PALETTES
def test_neighbouring_series_stay_apart_for_every_reader(colors: Palette) -> None:
    """Lines and bars only ever set a series beside its neighbour in the fixed order."""
    normal, colour_blind = worst_separation(colors.series, every_pair=False)
    assert normal >= NORMAL_FLOOR
    assert colour_blind >= COLOUR_BLIND_TARGET


@PALETTES
def test_the_series_a_scatter_may_use_stay_apart_in_every_pairing(colors: Palette) -> None:
    normal, colour_blind = worst_separation(colors.series[:MAX_SCATTER_SERIES], every_pair=True)
    assert normal >= NORMAL_FLOOR
    assert colour_blind >= COLOUR_BLIND_TARGET


@PALETTES
def test_a_fourth_scatter_series_would_not_be_safe(colors: Palette) -> None:
    """Why the cap is three: with a fourth colour some pair collapses for someone."""
    normal, colour_blind = worst_separation(
        colors.series[: MAX_SCATTER_SERIES + 1], every_pair=True
    )
    assert normal < NORMAL_FLOOR or colour_blind < COLOUR_BLIND_TARGET


def test_series_caps() -> None:
    assert (MAX_SCATTER_SERIES, MAX_LINE_SERIES) == (3, 4)
    assert len(LIGHT.series) == len(DARK.series) == 8
    assert len(set(LIGHT.series)) == 8 and len(set(DARK.series)) == 8


@PALETTES
def test_the_two_poles_of_a_diverging_scale_read_as_opposite(colors: Palette) -> None:
    assert difference(colors.positive, colors.negative) >= NORMAL_FLOOR
    for matrix in (PROTAN, DEUTAN):
        assert difference(colors.positive, colors.negative, matrix) >= COLOUR_BLIND_TARGET
    assert contrast(colors.positive, colors.surface) >= MARK_CONTRAST
    assert contrast(colors.negative, colors.surface) >= MARK_CONTRAST


@PALETTES
def test_the_subject_stands_out_from_its_context(colors: Palette) -> None:
    """Emphasis charts set the accent against gray: the two must not be confusable."""
    assert difference(colors.accent, colors.deemphasis) >= NORMAL_FLOOR
    for matrix in (PROTAN, DEUTAN):
        assert difference(colors.accent, colors.deemphasis, matrix) >= COLOUR_BLIND_TARGET
    assert contrast(colors.accent, colors.surface) >= MARK_CONTRAST
    # Context is meant to recede, but not to vanish.
    assert contrast(colors.deemphasis, colors.surface) >= 1.5


@PALETTES
def test_text_is_readable_on_the_surface(colors: Palette) -> None:
    assert contrast(colors.ink, colors.surface) >= 7
    assert contrast(colors.ink_secondary, colors.surface) >= TEXT_CONTRAST
    # Tick labels are 12px, small text, so 4.5:1 - not the 3:1 of large text, which this
    # test once allowed and the light theme's muted ink (3.5:1) met (UI polish P4).
    assert contrast(colors.ink_muted, colors.surface) >= TEXT_CONTRAST
    assert contrast(colors.ink_muted, colors.plane) >= TEXT_CONTRAST


@PALETTES
def test_every_series_stands_out_from_the_surface(colors: Palette) -> None:
    """A mark needs 3:1 against its chart (UI polish P4: three light series were under it)."""
    for color in colors.series:
        assert contrast(color, colors.surface) >= MARK_CONTRAST, color


@PALETTES
def test_gridlines_recede(colors: Palette) -> None:
    assert contrast(colors.grid, colors.surface) < 1.5
    assert contrast(colors.axis, colors.surface) < 2.0
    assert contrast(colors.grid, colors.surface) < contrast(colors.axis, colors.surface)


def test_dark_is_its_own_selection_not_a_flip() -> None:
    assert DARK.series != LIGHT.series
    assert contrast(DARK.surface, LIGHT.surface) > 15
    for color in DARK.series:
        assert contrast(color, DARK.surface) >= MARK_CONTRAST, color


@PALETTES
def test_status_colours_are_not_series_colours(colors: Palette) -> None:
    status = {colors.good, colors.warning, colors.serious, colors.critical}
    assert len(status) == 4
    assert not status & set(colors.series)


@PALETTES
def test_the_brand_holds_a_white_label_and_shows_on_the_page(colors: Palette) -> None:
    """Streamlit has one primary colour: the fill under a primary button's white label, and
    the selected tab, toggle, slider and focus drawn straight on the page (UI polish P1).
    The roadmap's deeper forest green, #244f38, would have failed the second line (2.1:1)."""
    assert contrast("#ffffff", colors.brand) >= TEXT_CONTRAST
    assert contrast(colors.brand, colors.plane) >= MARK_CONTRAST
    assert contrast(colors.brand, colors.surface) >= MARK_CONTRAST
    assert contrast(colors.link, colors.plane) >= TEXT_CONTRAST
    assert contrast(colors.link, colors.surface) >= TEXT_CONTRAST


@PALETTES
def test_the_brand_is_not_a_chart_colour(colors: Palette) -> None:
    """Actions and selection are green; data keeps its own colours, so a chart never takes
    a series for a button, nor a loss for a success."""
    assert colors.brand not in colors.series and colors.link not in colors.series
    assert difference(colors.brand, colors.accent) >= NORMAL_FLOOR
    assert colors.brand not in {colors.good, colors.warning, colors.serious, colors.critical}


def test_the_palette_follows_the_theme_type() -> None:
    assert palette("dark") is DARK
    assert palette("light") is LIGHT
    assert palette(None) is LIGHT


def test_wash_is_a_translucent_version_of_the_colour() -> None:
    assert LIGHT.wash("#2a78d6") == "rgba(42,120,214,0.15)"
    assert DARK.wash("#2a78d6") == "rgba(42,120,214,0.25)"
    assert LIGHT.wash("#ffffff", 0.25) == "rgba(255,255,255,0.25)"
    assert LIGHT.accent == LIGHT.series[0]


@PALETTES
def test_an_uncertainty_band_can_be_seen_and_stays_a_wash(colors: Palette) -> None:
    """UI polish P6: at a tenth, the dark theme's band - a chance curve's 95% interval, 30
    points wide - could not be seen. The wash must stand off the chart's surface, leave the
    line it sits behind readable, and stay translucent."""
    red, green, blue = (int(colors.accent[index : index + 2], 16) for index in (1, 3, 5))
    under = [int(colors.surface[index : index + 2], 16) for index in (1, 3, 5)]
    washed = "#" + "".join(
        f"{round(base + colors.wash_opacity * (top - base)):02x}"
        for base, top in zip(under, (red, green, blue), strict=True)
    )
    assert difference(washed, colors.surface) >= 6
    assert contrast(colors.accent, washed) >= MARK_CONTRAST
    assert colors.wash_opacity <= 0.3


@pytest.fixture(scope="module")
def config(repo_root: Path) -> dict:
    """The theme section of the workbench's Streamlit configuration."""
    with (repo_root / ".streamlit" / "config.toml").open("rb") as handle:
        return tomllib.load(handle)["theme"]


class TestPageThemeMatchesTheCharts:
    """.streamlit/config.toml and wb/theme.py state the same colours in two places."""

    @pytest.mark.parametrize(("mode", "colors"), [("light", LIGHT), ("dark", DARK)])
    def test_surfaces_and_ink(self, config: dict, mode: str, colors: Palette) -> None:
        page = config[mode]
        assert page["backgroundColor"] == colors.plane
        assert page["secondaryBackgroundColor"] == colors.surface
        assert page["textColor"] == colors.ink
        assert page["borderColor"] == colors.grid
        assert page["dataframeBorderColor"] == colors.grid
        assert page["dataframeHeaderBackgroundColor"] == colors.surface
        assert page["grayColor"] == colors.ink_muted
        assert page["sidebar"]["backgroundColor"] == colors.surface
        assert page["sidebar"]["secondaryBackgroundColor"] == colors.plane

    @pytest.mark.parametrize(("mode", "colors"), [("light", LIGHT), ("dark", DARK)])
    def test_the_brand_marks_actions_and_links(
        self, config: dict, mode: str, colors: Palette
    ) -> None:
        """UI polish P1: the primary colour is the brand, no longer the chart accent, which
        keeps the charts exactly as they were."""
        page = config[mode]
        assert page["primaryColor"] == colors.brand
        assert page["linkColor"] == colors.link
        assert page["primaryColor"] != colors.accent

    @pytest.mark.parametrize(("mode", "colors"), [("light", LIGHT), ("dark", DARK)])
    def test_code_is_quiet_text_not_green(self, config: dict, mode: str, colors: Palette) -> None:
        """UI polish P7: left unset, code takes the green of a good state, and a file path in
        an answer's evidence read as a link beside the real ones. Code is the secondary ink,
        which reads at 4.5:1 on the cards (``test_text_is_readable_on_the_surface``)."""
        page = config[mode]
        assert page["codeTextColor"] == colors.ink_secondary
        assert page["codeTextColor"] not in (colors.good, colors.brand, colors.link)

    @pytest.mark.parametrize(("mode", "colors"), [("light", LIGHT), ("dark", DARK)])
    def test_categorical_order_and_status_colours(
        self, config: dict, mode: str, colors: Palette
    ) -> None:
        page = config[mode]
        assert tuple(page["chartCategoricalColors"]) == colors.series
        assert page["greenColor"] == colors.good
        assert page["yellowColor"] == colors.warning
        assert page["orangeColor"] == colors.serious
        assert page["redColor"] == colors.critical

    def test_the_workbench_listens_on_this_machine_only(self, repo_root: Path) -> None:
        with (repo_root / ".streamlit" / "config.toml").open("rb") as handle:
            config = tomllib.load(handle)
        assert config["server"]["address"] == "localhost"
        assert config["browser"]["gatherUsageStats"] is False
