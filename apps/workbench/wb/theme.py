"""Design tokens: one palette, stepped for a light and for a dark surface.

Every colour a chart uses comes from here, by role. The categorical order is fixed and
is what keeps neighbouring series apart for colour-blind readers, so slots are assigned
in sequence and never reordered or extended: a chart that needs more series than it can
carry is the wrong chart. ``tests/ui/test_theme.py`` checks the separation numerically.

The page's brand is a forest green (``brand``, ``link``; UI polish P1,
``docs/ui-polish/DESIGN_SYSTEM.md``): it marks actions and selection, never data, so the
charts keep their own accent and their categorical order.
"""

from __future__ import annotations

from dataclasses import dataclass

FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

# Any two marks can sit side by side in a scatter, so it may use only the leading slots,
# which stay distinguishable in every pairing. Lines and bars touch only their neighbours.
MAX_SCATTER_SERIES = 3
MAX_LINE_SERIES = 4


@dataclass(frozen=True, slots=True)
class Palette:
    mode: str
    surface: str
    """Background of a chart and of the cards it sits on."""
    plane: str
    """Background of the page."""
    ink: str
    ink_secondary: str
    ink_muted: str
    """Axis ticks and other quiet labels."""
    grid: str
    axis: str
    series: tuple[str, ...]
    """Categorical hues in their fixed order."""
    deemphasis: str
    """Marks that are context, not the subject."""
    positive: str
    negative: str
    """The two poles of a diverging scale: above and below a baseline."""
    good: str
    warning: str
    serious: str
    critical: str
    """Status colours. Reserved for state, and always shown with an icon and a label."""
    brand: str
    """The page's primary colour: primary buttons under a white label, and the selected tab,
    toggle, slider and focus drawn straight on the page - so it must hold both, which is why
    it is a mid forest green rather than a deep one. Never a chart colour."""
    link: str
    """Links in text: the brand, light enough to read as text on the page."""

    @property
    def accent(self) -> str:
        """The first categorical hue: a single series, or the one that is the subject."""
        return self.series[0]

    def wash(self, color: str, opacity: float = 0.10) -> str:
        """``color`` as a translucent fill: an area under a line, never a solid block."""
        red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
        return f"rgba({red},{green},{blue},{opacity})"


# UI polish P4: the green, amber and pink a step darker, so every series reaches 3:1 on the
# light surface (they were 2.74, 2.11 and 2.62), and the muted ink too, so 12px tick labels
# reach the 4.5:1 of small text (it was 3.5). Hue kept; every separation still holds.
LIGHT = Palette(
    mode="light",
    surface="#fcfcfb",
    plane="#f9f9f7",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    ink_muted="#74726d",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series=(
        "#2a78d6",
        "#eb6834",
        "#19a472",
        "#c28400",
        "#e46494",
        "#008300",
        "#4a3aa7",
        "#e34948",
    ),
    deemphasis="#c3c2b7",
    positive="#2a78d6",
    negative="#e34948",
    good="#0ca30c",
    warning="#fab219",
    serious="#ec835a",
    critical="#d03b3b",
    brand="#1f6b45",
    link="#1f6b45",
)

# Near-black with a trace of the forest in every neutral: the page, its cards, its text
# and its lines. The series, the poles and the states are the same as before P1.
DARK = Palette(
    mode="dark",
    surface="#151b17",
    plane="#0a0d0b",
    ink="#f1f5f2",
    ink_secondary="#a7b4a9",
    ink_muted="#7f9084",
    grid="#2a362e",
    axis="#3a4a40",
    series=(
        "#3987e5",
        "#d95926",
        "#199e70",
        "#c98500",
        "#d55181",
        "#008300",
        "#9085e9",
        "#e66767",
    ),
    deemphasis="#4e5e54",
    positive="#3987e5",
    negative="#e66767",
    good="#0ca30c",
    warning="#fab219",
    serious="#ec835a",
    critical="#d03b3b",
    brand="#2f8556",
    link="#79b391",
)


def palette(mode: str | None) -> Palette:
    """The palette for a theme type; anything but ``"dark"`` is light."""
    return DARK if mode == "dark" else LIGHT
