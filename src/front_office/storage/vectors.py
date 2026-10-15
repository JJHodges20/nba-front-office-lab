"""``data/rag/``: the vector index of the lab's documents, in ChromaDB (decision 0019).

One collection, ``lab_documents``: each passage's embedding, its text, and where it is -
file, title, heading, link. The collection records the embedding model, the fingerprint of
the passages it was built from, and when. A rebuild fills a collection of its own and then
puts it in the old one's place, so a search finds the old index or the new one, never half
of one. Chroma computes nothing here: every embedding is given - no embedding function, so
nothing is downloaded - and its telemetry is off.

Open it in a ``with`` block: on Windows an open index keeps its files locked. Opening it is
cheap, so a service opens it afresh for every call and sees a rebuild at once.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from front_office.domain.rag import IndexedPassage, IndexState, PassageHit
from front_office.storage.database import StorageError

COLLECTION = "lab_documents"
BUILDING = "lab_documents_next"
SPACE = "cosine"
_FILE = "chroma.sqlite3"


class IndexNotBuilt(StorageError):
    """No index of the documents has been built."""


class PassageIndex:
    """The documents' vector index at ``path``."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.path), settings=ChromaSettings(anonymized_telemetry=False)
        )

    @staticmethod
    def exists(path: Path) -> bool:
        """Whether an index was ever made at ``path``, without making one."""
        return (Path(path) / _FILE).is_file()

    def __enter__(self) -> PassageIndex:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _named(self, name: str) -> Any | None:
        if name not in {collection.name for collection in self._client.list_collections()}:
            return None
        return self._client.get_collection(name, embedding_function=None)

    def _drop(self, name: str) -> None:
        if self._named(name) is not None:
            self._client.delete_collection(name)

    def state(self) -> IndexState | None:
        """What the index holds, or ``None`` when none is built."""
        collection = self._named(COLLECTION)
        if collection is None:
            return None
        meta = collection.metadata or {}
        return IndexState(
            passages=collection.count(),
            model=str(meta["embedding_model"]),
            fingerprint=str(meta["fingerprint"]),
            built_at=datetime.fromisoformat(str(meta["built_at"])),
        )

    def replace(
        self,
        passages: Sequence[IndexedPassage],
        vectors: Sequence[Sequence[float]],
        *,
        model: str,
        fingerprint: str,
        built_at: datetime,
    ) -> IndexState:
        """Put these passages, embedded, in the index's place."""
        if len(passages) != len(vectors):
            raise StorageError(f"{len(passages)} passages but {len(vectors)} embeddings")
        self._drop(BUILDING)
        building = self._client.create_collection(
            BUILDING,
            embedding_function=None,
            configuration={"hnsw": {"space": SPACE}},
            metadata={
                "embedding_model": model,
                "fingerprint": fingerprint,
                "built_at": built_at.isoformat(),
            },
        )
        step = self._client.get_max_batch_size()
        for start in range(0, len(passages), step):
            chunk = passages[start : start + step]
            building.add(
                ids=[passage.passage_id for passage in chunk],
                embeddings=[list(vector) for vector in vectors[start : start + step]],
                documents=[passage.text for passage in chunk],
                metadatas=[
                    {
                        "path": passage.path,
                        "document": passage.document,
                        "heading": passage.heading,
                        "location": passage.location,
                    }
                    for passage in chunk
                ],
            )
        self._drop(COLLECTION)
        building.modify(name=COLLECTION)
        built = self.state()
        if built is None:
            raise StorageError("the new index was not put in place")
        return built

    def search(self, vector: Sequence[float], k: int) -> tuple[PassageHit, ...]:
        """The ``k`` passages nearest ``vector``, nearest first."""
        collection = self._named(COLLECTION)
        if collection is None:
            raise IndexNotBuilt("the documents have not been indexed")
        held = collection.count()
        if held == 0:
            return ()
        found = collection.query(
            query_embeddings=[list(vector)],
            n_results=min(k, held),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for passage_id, text, meta, distance in zip(
            found["ids"][0],
            (found["documents"] or [[]])[0],
            (found["metadatas"] or [[]])[0],
            (found["distances"] or [[]])[0],
            strict=True,
        ):
            passage = IndexedPassage(
                passage_id=passage_id,
                path=str(meta["path"]),
                document=str(meta["document"]),
                heading=str(meta["heading"]),
                location=str(meta["location"]),
                text=str(text),
            )
            hits.append(PassageHit(passage=passage, distance=float(distance)))
        return tuple(hits)
