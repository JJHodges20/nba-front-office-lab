"""A full-text search over the lab's own documents (decision 0018, A4).

SQLite's FTS5, in memory: the sections are indexed afresh for each search, so an edited
document is found as it now reads and nothing is kept on disk. A section is indexed in
passages (``domain.documents.passages``), so that a long one is not found for holding
every word somewhere, and each section is returned once, with its best passage. Words
match on their stems (``porter``), so "probabilities" finds "probability"; a heading
weighs more than a document's title, and the title more than the text. The query is the
words the caller wrote, any of them, less the common ones, ranked by BM25: nothing in it
is read as FTS5's own syntax.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from front_office.domain.documents import Section, passages

WORD = re.compile(r"\w+")
COMMON = frozenset(
    """a about an and any are as at be been but by can could did do does doesn don for
    from had has have how i if in into is isn it its me my not of on or our should so
    than that the their them then there these they this those to was wasn we were what
    when where which while who why will with would you your
    decide decides explain find get gets give gives lab make makes mean means say says
    show shows tell tells use uses used using work works""".split()
)
"""Words that say nothing about which section is meant: the common ones, and the verbs a
question asks with ("how does it decide", "why doesn't it use")."""
WEIGHTS = (0.0, 1.5, 2.0, 1.0)
"""BM25 weights of the columns: the section (not searched), the document's title, the
headings, the passage."""
POOL = 8
"""Passages read per section asked for, before each section is kept once."""
SHORTEST = 80
"""Characters a section needs to be searched: shorter is a date line or a status, which
a matching title would otherwise rank first."""


@dataclass(frozen=True, slots=True)
class DocumentHit:
    section: Section
    excerpt: str
    """The passage of the section that matched best."""
    score: float
    """BM25 as FTS5 gives it: the more negative, the better the match."""


def query_words(query: str) -> tuple[str, ...]:
    """The words of ``query`` searched for: each once, lower case, the common ones left
    out unless nothing else is left."""
    words = list(dict.fromkeys(word.lower() for word in WORD.findall(query)))
    telling = [word for word in words if word not in COMMON and (len(word) > 2 or word.isdigit())]
    return tuple(telling or words)


def search_sections(
    sections: Sequence[Section], query: str, *, limit: int
) -> tuple[DocumentHit, ...]:
    """The sections that best match the words of ``query``, best first, each once."""
    words = query_words(query)
    if not words or not sections or limit < 1:
        return ()
    expression = " OR ".join(f'"{word}"' for word in words)
    rows_in = (
        (position, section.document, section.heading, passage)
        for position, section in enumerate(sections)
        if len(section.text) >= SHORTEST
        for passage in passages(section.text)
    )
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE passages USING fts5("
            "section UNINDEXED, document, heading, body, tokenize = 'porter unicode61')"
        )
        connection.executemany(
            "INSERT INTO passages (section, document, heading, body) VALUES (?, ?, ?, ?)",
            rows_in,
        )
        rows = connection.execute(
            "SELECT section, body, bm25(passages, ?, ?, ?, ?) AS score "
            "FROM passages WHERE passages MATCH ? ORDER BY score, rowid LIMIT ?",
            (*WEIGHTS, expression, limit * POOL),
        ).fetchall()
    finally:
        connection.close()
    hits: dict[int, DocumentHit] = {}
    for position, body, score in rows:
        if int(position) not in hits:
            hits[int(position)] = DocumentHit(sections[int(position)], str(body), float(score))
    return tuple(hits.values())[:limit]
