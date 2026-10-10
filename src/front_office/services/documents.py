"""The lab's documentation and research, searched (decision 0018, A4).

What ``research_docs`` reads: every Markdown file under the project's ``docs/`` folder,
cut at its headings and searched afresh each time, so that an answer about how something
is computed or was tested can quote the lab's own account of it and cite the file and the
heading. Nothing is stored, and nothing here reads the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from front_office.config.documents import documents_path, load_sections
from front_office.domain.documents import Section
from front_office.services.lab import Lab
from front_office.storage.documents import DocumentHit, query_words, search_sections

HITS = 4
"""Sections a search returns unless asked for another number."""


@dataclass(frozen=True, slots=True)
class DocumentSearch:
    query: str
    words: tuple[str, ...]
    """The words searched for: the query's, less the common ones."""
    hits: tuple[DocumentHit, ...]
    """The best-matching sections, best first."""
    documents: int
    """Files searched."""
    sections: int

    @property
    def is_empty(self) -> bool:
        return not self.hits


class DocumentService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def available(self) -> bool:
        """Whether the project's documents are on this machine."""
        return documents_path(self._lab.settings.project_root).is_dir()

    def sections(self) -> tuple[Section, ...]:
        return load_sections(self._lab.settings.project_root)

    def search(self, query: str, limit: int = HITS) -> DocumentSearch:
        sections = self.sections()
        return DocumentSearch(
            query=query,
            words=query_words(query),
            hits=search_sections(sections, query, limit=limit),
            documents=len({section.path for section in sections}),
            sections=len(sections),
        )
