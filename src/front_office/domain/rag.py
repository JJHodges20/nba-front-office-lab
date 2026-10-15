"""Retrieval over the lab's documents (decision 0019): the passages a vector index holds, the
passages nearest a question, and the answer written from them.

The documents are the sections the assistant's keyword search reads, with the same files left
out (``config/documents.py``), cut into the same passages
(:func:`front_office.domain.documents.passages`). Each passage is embedded under its
document's title and its heading, so that it is found for what it is about as well as for its
words. An index records the embedding model and a fingerprint of the passages it holds: when
the documents or the model change, the fingerprint no longer matches and the index is built
again.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from front_office.domain.documents import PASSAGE, TRAIL, Section, passages


@dataclass(frozen=True, slots=True)
class IndexedPassage:
    """One passage of one section, as the index keeps it."""

    passage_id: str
    """A hash of where the passage is and what it says: a passage that changes is a new one."""
    path: str
    document: str
    heading: str
    location: str
    """The file and the heading, as a link within the project."""
    text: str

    @property
    def title(self) -> str:
        """The document's title and the passage's heading: "Architecture › The API"."""
        return (
            self.document if self.heading == self.document else self.document + TRAIL + self.heading
        )

    @property
    def embedded(self) -> str:
        """What the embedding model reads: the passage under its title."""
        return f"{self.title}\n\n{self.text}"


def document_passages(
    sections: Sequence[Section], *, size: int = PASSAGE
) -> tuple[IndexedPassage, ...]:
    """Every section's passages, in order."""
    found: list[IndexedPassage] = []
    used: set[str] = set()
    for section in sections:
        for ordinal, text in enumerate(passages(section.text, size=size), start=1):
            seed = "\x1f".join((section.location, str(ordinal), text))
            passage_id = _digest(seed)
            # Two passages alike in place and words cannot both be kept under one id.
            repeat = 1
            while passage_id in used:
                repeat += 1
                passage_id = _digest(f"{seed}\x1f{repeat}")
            used.add(passage_id)
            found.append(
                IndexedPassage(
                    passage_id=passage_id,
                    path=section.path,
                    document=section.document,
                    heading=section.heading,
                    location=section.location,
                    text=text,
                )
            )
    return tuple(found)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def index_fingerprint(found: Sequence[IndexedPassage], *, model: str, prefix: str) -> str:
    """What an index is built from, in one short hash: the embedding model, the text put
    before each passage, and every passage."""
    digest = hashlib.sha256()
    for part in (model, prefix, *(passage.passage_id for passage in found)):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class PassageHit:
    """A passage found near a question."""

    passage: IndexedPassage
    distance: float
    """Cosine distance from the question: 0 points the same way, 1 is unrelated."""


@dataclass(frozen=True, slots=True)
class IndexState:
    """What a built index holds."""

    passages: int
    model: str
    """The embedding model its passages were embedded with."""
    fingerprint: str
    built_at: datetime


@dataclass(frozen=True, slots=True)
class IndexStatus:
    """A built index, if there is one, beside what the documents and the settings are now."""

    built: IndexState | None
    model: str
    """The embedding model the settings name."""
    fingerprint: str
    """The fingerprint an index built now would have."""
    passages: int
    """The passages an index built now would hold."""

    @property
    def is_built(self) -> bool:
        return self.built is not None

    @property
    def is_current(self) -> bool:
        """Built from these documents, with this model."""
        return self.built is not None and self.built.fingerprint == self.fingerprint

    @property
    def can_answer(self) -> bool:
        """Built with the model a question is embedded with now: an index built from older
        documents still answers, from what they said."""
        return self.built is not None and self.built.model == self.model


@dataclass(frozen=True, slots=True)
class IndexReport:
    """What building the index did."""

    rebuilt: bool
    """False when the index already matched the documents and the model."""
    passages: int
    model: str
    fingerprint: str
    built_at: datetime
    seconds: float


@dataclass(frozen=True, slots=True)
class CitedSource:
    """One passage an answer was given, numbered as the answer cites it."""

    number: int
    path: str
    """The document, from the project root."""
    heading: str
    """The document's title and the heading the passage sits under."""
    location: str
    """The file and the heading as a link within the project."""
    distance: float
    """How far the passage was from the question: smaller is nearer."""
    text: str = ""
    """The passage as the model read it."""
    cited: bool = False
    """Whether the answer cites it."""


@dataclass(frozen=True, slots=True)
class DocumentAnswer:
    """An answer written from the lab's documents, with the passages it was given."""

    question: str
    answer: str
    sources: tuple[CitedSource, ...]
    model: str
    """The chat model that wrote the answer."""
    seconds: float
    notes: tuple[str, ...] = ()
    """What the reader should know about the answer: a sentence cut for a figure no passage
    holds, no passage cited, an index built from older documents."""
