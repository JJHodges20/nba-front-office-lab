"""The lab's own documentation and research as the assistant's ``research_docs`` tool.

Decision 0018 (A4). How a figure is computed, how a model was tested and why a choice was
made are written down in ``docs/``; the tool searches it (``services/documents.py``) and
returns the best-matching sections, each quoted as written and cited by its file and
heading. A section is data, like any text the model reads: the rules say so.
"""

from __future__ import annotations

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import Found, Handler, missing
from front_office.domain.assistant import Evidence, EvidenceKind, ResultStatus
from front_office.services import DocumentSearch, Lab

FIRST_QUOTE = 640
"""Characters of the best section the model reads; the page shows the whole passage."""
QUOTE = 380
"""Characters of each further section."""


def research_docs(lab: Lab, args: t.ResearchDocs) -> Found:
    title = f'The lab\'s documents on "{args.query}"'
    documents = lab.documents
    if not documents.available:
        return Found(
            ResultStatus.UNAVAILABLE,
            title,
            "The lab's documents (the docs folder) are not on this machine.",
        )
    found = documents.search(args.query)
    searched = Evidence(
        EvidenceKind.DOCS, f"The lab's documents ({found.documents} files)", location="docs/"
    )
    if found.is_empty:
        return missing(
            title,
            f"No section of the lab's {found.documents} documents matches "
            f"{', '.join(found.words) or 'these words'}.",
            (searched,),
        )
    blocks = []
    for position, hit in enumerate(found.hits):
        section = hit.section
        quoted = _cut(hit.excerpt, FIRST_QUOTE if position == 0 else QUOTE)
        blocks.append(
            f"From {section.location} ({section.document} › {section.heading}):\n{quoted}"
        )
    head = (
        f"The parts of the lab's own documents ({found.documents} files) that best match "
        f"{', '.join(found.words)}, best first, quoted as written:"
    )
    table = _table(found)
    evidence = tuple(
        Evidence(
            EvidenceKind.DOCS,
            f"{hit.section.document} › {hit.section.heading}",
            location=hit.section.location,
        )
        for hit in found.hits
    )
    return Found(ResultStatus.OK, title, "\n\n".join([head, *blocks]), table, evidence)


def _cut(text: str, limit: int) -> str:
    """``text`` up to ``limit`` characters, its lines kept - a table stays a table - and
    ended at a word with " …" when it goes on."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    kept = "\n".join(line for line in lines if line)
    if len(kept) <= limit:
        return kept
    cut = max(kept.rfind(" ", 0, limit), kept.rfind("\n", 0, limit))
    return kept[: cut if cut > 0 else limit].rstrip() + " …"


def _table(found: DocumentSearch) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "document": hit.section.document,
                "heading": hit.section.heading,
                "location": hit.section.location,
                "passage": hit.excerpt,
            }
            for hit in found.hits
        ]
    )


DOCUMENT_HANDLERS: dict[str, Handler] = {"research_docs": research_docs}
