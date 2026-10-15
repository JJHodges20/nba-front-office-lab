"""The vector index of the lab's documents, read (decision 0019): where it stands, and the
passages nearest a question.

``pipelines/rag.py`` builds the index; the assistant's documents answer searches it through
here. The index is opened afresh for every call, as every store is, so a rebuild is seen at
once.
"""

from __future__ import annotations

from collections.abc import Sequence

from front_office.config.api import load_api_settings
from front_office.config.documents import load_sections
from front_office.config.settings import Settings
from front_office.domain.rag import (
    IndexStatus,
    PassageHit,
    document_passages,
    index_fingerprint,
)
from front_office.storage.vectors import IndexNotBuilt, PassageIndex


class PassageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> IndexStatus:
        """The index as built, beside what the documents and the settings are now."""
        rag = load_api_settings(self._settings.config_dir).rag
        expected = document_passages(
            load_sections(self._settings.project_root), left_out=rag.left_out
        )
        built = None
        if PassageIndex.exists(self._settings.rag_dir):
            with PassageIndex(self._settings.rag_dir) as index:
                built = index.state()
        return IndexStatus(
            built=built,
            model=rag.embedding_model,
            fingerprint=index_fingerprint(
                expected, model=rag.embedding_model, prefix=rag.document_prefix
            ),
            passages=len(expected),
        )

    def search(self, vector: Sequence[float], k: int) -> tuple[PassageHit, ...]:
        """The ``k`` passages nearest an embedded question; :class:`IndexNotBuilt` before
        the index is."""
        if not PassageIndex.exists(self._settings.rag_dir):
            raise IndexNotBuilt("the documents have not been indexed")
        with PassageIndex(self._settings.rag_dir) as index:
            return index.search(vector, k)


__all__ = ["IndexNotBuilt", "PassageService"]
