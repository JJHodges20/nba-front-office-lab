"""The lab's own documents as the assistant searches them: the text under each heading.

Decision 0018 (A4). ``research_docs`` answers how something is computed or was tested
from the lab's documentation and research, and an answer cites the file and the heading
it read. A document is cut at its headings: a section is the text under one heading,
down to the next heading of any level. A ``#`` inside fenced code is code, not a heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
TRAIL = " › "
"""Between the headings a section sits under: "Decision › How it was tested"."""
PASSAGE = 900
"""Characters a passage grows to, paragraph by paragraph: a section is searched in
passages, so that a long one is not found for holding every word somewhere."""
PARAGRAPH = re.compile(r"\n[ \t]*\n")


@dataclass(frozen=True, slots=True)
class Section:
    """The text under one heading of one document."""

    path: str
    """The document's path from the project root, with forward slashes."""
    document: str
    """The document's title: its first top-level heading, else its file name."""
    heading: str
    """The headings the section sits under below the title, outermost first, joined by
    :data:`TRAIL`; the title itself for the text before the first heading below it."""
    anchor: str
    """The section's own heading as a link fragment, as GitHub writes it; empty for text
    before any heading."""
    text: str

    @property
    def location(self) -> str:
        """The file and the heading, as a link within the project."""
        return f"{self.path}#{self.anchor}" if self.anchor else self.path


@dataclass(frozen=True, slots=True)
class _Heading:
    level: int
    name: str
    anchor: str


def anchor(heading: str) -> str:
    """A heading as GitHub makes its link fragment: lower case, everything but letters,
    digits, spaces, hyphens and underscores dropped, spaces as hyphens."""
    kept = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return kept.replace(" ", "-")


def split_sections(path: str, text: str) -> tuple[Section, ...]:
    """``text``, the Markdown document at ``path``, cut at its headings. A heading with
    nothing under it before the next one gives no section of its own; it stays in the
    trail of those below it."""
    trail: list[_Heading] = []
    body: list[str] = []
    found: list[tuple[tuple[_Heading, ...], str]] = []
    used: dict[str, int] = {}
    title: str | None = None
    fenced = False

    def close() -> None:
        content = "\n".join(body).strip()
        if content:
            found.append((tuple(trail), content))

    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            body.append(line)
            continue
        match = None if fenced else HEADING.match(line)
        if match is None:
            body.append(line)
            continue
        close()
        body = []
        level, name = len(match.group(1)), match.group(2).strip()
        if level == 1 and title is None:
            title = name
        fragment = anchor(name)
        # GitHub numbers a fragment the document has used already: "notes", "notes-1".
        seen = used.get(fragment, 0)
        used[fragment] = seen + 1
        heading = _Heading(level, name, fragment if seen == 0 else f"{fragment}-{seen}")
        trail = [*(item for item in trail if item.level < level), heading]
    close()

    document = title or path.rsplit("/", 1)[-1]
    sections = []
    for headings, content in found:
        below = [item.name for item in headings if not (item.level == 1 and item.name == title)]
        sections.append(
            Section(
                path=path,
                document=document,
                heading=TRAIL.join(below) or document,
                anchor=headings[-1].anchor if headings else "",
                text=content,
            )
        )
    return tuple(sections)


def passages(text: str, *, size: int = PASSAGE) -> tuple[str, ...]:
    """``text`` in passages of whole paragraphs, each grown until it reaches ``size``
    characters; a paragraph longer than that - a long table, a long list - is cut between
    its lines instead."""
    pieces: list[str] = []
    for paragraph in PARAGRAPH.split(text.strip()):
        paragraph = paragraph.strip()
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        lines: list[str] = []
        for line in paragraph.splitlines():
            if lines and len("\n".join(lines)) + len(line) > size:
                pieces.append("\n".join(lines))
                lines = []
            lines.append(line)
        pieces.append("\n".join(lines))
    found: list[str] = []
    for piece in (piece for piece in pieces if piece):
        if found and len(found[-1]) < size and len(found[-1]) + len(piece) <= size:
            found[-1] = f"{found[-1]}\n\n{piece}"
        else:
            found.append(piece)
    return tuple(found)
