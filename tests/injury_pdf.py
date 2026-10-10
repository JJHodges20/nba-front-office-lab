"""A made-up injury report in the league's layout, for tests.

The league's report may not be redistributed ("no portion... may be duplicated,
redistributed or manipulated", docs/DATA_SOURCE_REGISTER.md), so no real one is committed.
This draws one the way the league sets it out, as the parser saw it in a real report on
2026-10-09: a title, a header row whose headings are separate words, one line per player -
the game, the team and the matchup written once for the group below them - a reason that
wraps over two lines set either side of its row, a reason carried over a page break, a team
"NOT YET SUBMITTED", and a "Page n of m" footer.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

COLUMN_X = (20.0, 92.0, 150.0, 232.0, 380.0, 520.0, 600.0)
HEADINGS = (
    ("Game", "Date"),
    ("Game", "Time"),
    ("Matchup",),
    ("Team",),
    ("Player", "Name"),
    ("Current", "Status"),
    ("Reason",),
)
ROW = 12.0
LINE = 9.0


@dataclass(frozen=True)
class Line:
    """One line of the report. A blank cell is not written, as in the league's layout."""

    date: str = ""
    time: str = ""
    matchup: str = ""
    team: str = ""
    player: str = ""
    status: str = ""
    reason: tuple[str, ...] = ()


def report_pdf(
    pages: Sequence[Sequence[Line]],
    *,
    title: str = "Report: 10/21/26 05:30 PM",
    carried_over: Sequence[str] = (),
) -> bytes:
    """The report's PDF. ``carried_over`` is reason text at the top of the second page
    that finishes the last line of the first."""
    writer = PdfWriter()
    for number, lines in enumerate(pages, start=1):
        items = [(20.0, 585.0, "Injury"), (52.0, 585.0, title)]
        y = 560.0
        if number == 1:
            for x, words in zip(COLUMN_X, HEADINGS, strict=True):
                for offset, word in enumerate(words):
                    items.append((x + 34.0 * offset, y, word))
            y -= 20.0
        elif carried_over:
            for text in carried_over:
                items.append((COLUMN_X[6], y, text))
                y -= LINE
            y -= 16.0
        for line in lines:
            cells = (line.date, line.time, line.matchup, line.team, line.player, line.status)
            items += [(x, y, cell) for x, cell in zip(COLUMN_X, cells, strict=False) if cell]
            top = y + LINE / 2 * (len(line.reason) - 1)
            items += [(COLUMN_X[6], top - LINE * k, text) for k, text in enumerate(line.reason)]
            y -= ROW + LINE * max(len(line.reason) - 1, 0)
        items += [(370.0, 20.0, "Page"), (392.0, 20.0, f"{number} of {len(pages)}")]
        _draw(writer, items)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _draw(writer: PdfWriter, items: list[tuple[float, float, str]]) -> None:
    page = writer.add_blank_page(width=792, height=612)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        "\n".join(
            f"BT /F1 8 Tf {x:.1f} {y:.1f} Td ({_escaped(text)}) Tj ET" for x, y, text in items
        ).encode("latin-1")
    )
    page[NameObject("/Contents")] = writer._add_object(stream)


def _escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


SAMPLE = [
    [
        Line(
            "10/21/2026",
            "07:30 (ET)",
            "NYK@BOS",
            "Boston Celtics",
            "Brown, Jaylen",
            "Questionable",
            ("Injury/Illness - Left Knee; Soreness",),
        ),  # fmt: skip
        Line(
            player="Tatum, Jayson",
            status="Out",
            reason=("Injury/Illness - Right Achilles;", "Tendon Repair"),
        ),  # fmt: skip
        Line(
            team="New York Knicks",
            player="Hart, Josh",
            status="Available",
            reason=("Injury/Illness - Left Ankle; Sprain",),
        ),  # fmt: skip
        Line(
            "10/22/2026", "08:00 (ET)", "CHI@MIL", "Chicago Bulls", reason=("NOT YET SUBMITTED",)
        ),  # fmt: skip
        Line(
            team="Milwaukee Bucks", player="Doe, Jordan", status="Out", reason=("G League - Two-",)
        ),  # fmt: skip
    ],
    [
        Line(player="Roe, Riley", status="Doubtful", reason=("Rest",)),
    ],
]
"""Two pages: six lines, the fifth's reason finished at the top of page two."""
SAMPLE_CARRIED = ("Way",)
