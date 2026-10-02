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
    # Axis labels are large enough for the 3:1 that applies to large text.
    assert contrast(colors.ink_muted, colors.surface) >= MARK_CONTRAST


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


def test_the_palette_follows_the_theme_type() -> None:
    assert palette("dark") is DARK
    assert palette("light") is LIGHT
    assert palette(None) is LIGHT


def test_wash_is_a_translucent_version_of_the_colour() -> None:
    assert LIGHT.wash("#2a78d6") == "rgba(42,120,214,0.1)"
    assert LIGHT.wash("#ffffff", 0.25) == "rgba(255,255,255,0.25)"
    assert LIGHT.accent == LIGHT.series[0]


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
        assert page["primaryColor"] == colors.accent
        assert page["borderColor"] == colors.grid
        assert page["sidebar"]["backgroundColor"] == colors.surface

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
