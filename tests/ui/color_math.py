"""Colour arithmetic for checking the workbench palette.

A palette is safe when its colours stay apart for readers with the common forms of
colour blindness, not just for those with full colour vision. That is measurable:

- colours are compared in OKLab, where equal distances look equally different, with
  the difference scaled by 100;
- protanopia and deuteranopia are simulated with the Machado, Oliveira and Fernandes
  (2009) matrices at full severity, applied to linear RGB.
"""

from __future__ import annotations

from itertools import combinations, pairwise

PROTAN = (
    (0.152286, 1.052583, -0.204868),
    (0.114503, 0.786281, 0.099216),
    (-0.003882, -0.048116, 1.051998),
)
DEUTAN = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)

Rgb = tuple[float, float, float]


def _linear(hex_color: str) -> Rgb:
    """sRGB hex to linear RGB."""
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)


def _oklab(rgb: Rgb) -> Rgb:
    red, green, blue = rgb
    long = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    medium = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    long, medium, short = (max(value, 0.0) ** (1 / 3) for value in (long, medium, short))
    return (
        0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short,
    )


def _simulate(rgb: Rgb, matrix: tuple[Rgb, Rgb, Rgb]) -> Rgb:
    return tuple(
        min(max(sum(weight * channel for weight, channel in zip(row, rgb, strict=True)), 0.0), 1.0)
        for row in matrix
    )


def difference(first: str, second: str, matrix: tuple[Rgb, Rgb, Rgb] | None = None) -> float:
    """How different two colours look, optionally to a colour-blind reader."""
    a, b = _linear(first), _linear(second)
    if matrix is not None:
        a, b = _simulate(a, matrix), _simulate(b, matrix)
    lab_a, lab_b = _oklab(a), _oklab(b)
    return 100 * sum((x - y) ** 2 for x, y in zip(lab_a, lab_b, strict=True)) ** 0.5


def worst_separation(colors: tuple[str, ...], *, every_pair: bool) -> tuple[float, float]:
    """The smallest difference among a palette's pairs: ``(normal vision, colour-blind)``.

    ``every_pair`` compares each colour with every other, as a scatter needs; otherwise
    only neighbours in the given order are compared, as lines and bars need.
    """
    pairs = list(combinations(colors, 2) if every_pair else pairwise(colors))
    normal = min(difference(a, b) for a, b in pairs)
    blind = min(min(difference(a, b, PROTAN), difference(a, b, DEUTAN)) for a, b in pairs)
    return normal, blind


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio between two colours."""

    def luminance(hex_color: str) -> float:
        red, green, blue = _linear(hex_color)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
