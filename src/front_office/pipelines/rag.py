"""Build the vector index of the lab's documents (decision 0019): ``fol rag index``, the
API's ``POST /rag/index``, and the first start of Docker Compose.

Reads the sections the assistant's keyword search reads, cuts them into its passages, embeds
each with the local Ollama embedding model, and puts them in ``data/rag`` in place of the old
index. When the index already matches the documents and the model nothing is done, unless a
rebuild is asked for.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from front_office.config.api import load_api_settings
from front_office.config.assistant import load_assistant_settings
from front_office.config.documents import load_sections
from front_office.config.settings import Settings
from front_office.domain.rag import IndexReport, document_passages, index_fingerprint
from front_office.providers.ollama import (
    ModelNotAvailable,
    NotLocal,
    OllamaError,
    OllamaProvider,
    OllamaUnavailable,
)
from front_office.storage.vectors import PassageIndex


class IndexingFailed(RuntimeError):
    """The index could not be built. The message says why and what to do, in plain words;
    the index already there, if any, is left as it was."""


class NothingToIndex(IndexingFailed):
    """There are no documents to index."""


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def index_documents(
    settings: Settings,
    *,
    provider: OllamaProvider | None = None,
    force: bool = False,
    now: Callable[[], datetime] = _utc_now,
    clock: Callable[[], float] = time.monotonic,
) -> IndexReport:
    """Build the index if it does not match the documents and the model, or ``force``.
    Raises :class:`IndexingFailed` when Ollama cannot embed the passages."""
    started = clock()
    rag = load_api_settings(settings.config_dir).rag
    found = document_passages(load_sections(settings.project_root), left_out=rag.left_out)
    if not found:
        raise NothingToIndex(f"there are no documents to index in {settings.project_root / 'docs'}")
    fingerprint = index_fingerprint(found, model=rag.embedding_model, prefix=rag.document_prefix)
    if not force and PassageIndex.exists(settings.rag_dir):
        with PassageIndex(settings.rag_dir) as index:
            built = index.state()
        if built is not None and built.fingerprint == fingerprint:
            return IndexReport(
                rebuilt=False,
                passages=built.passages,
                model=built.model,
                fingerprint=built.fingerprint,
                built_at=built.built_at,
                seconds=clock() - started,
            )
    ollama = load_assistant_settings(settings.config_dir).ollama
    vectors: list[tuple[float, ...]] = []
    try:
        if provider is None:
            provider = OllamaProvider(ollama.host, timeout=ollama.timeout_seconds)
        for start in range(0, len(found), rag.batch):
            batch = found[start : start + rag.batch]
            texts = [rag.document_prefix + passage.embedded for passage in batch]
            vectors.extend(provider.embed(rag.embedding_model, texts))
    except OllamaUnavailable as error:
        raise IndexingFailed(
            f"Ollama is not answering at {ollama.host} ({error}). Start the Ollama app (or "
            "run: ollama serve), then build the index again."
        ) from error
    except (ModelNotAvailable, NotLocal) as error:
        raise IndexingFailed(str(error)) from error
    except OllamaError as error:
        raise IndexingFailed(f"Ollama answered with an error: {error}") from error
    with PassageIndex(settings.rag_dir) as index:
        built = index.replace(
            found, vectors, model=rag.embedding_model, fingerprint=fingerprint, built_at=now()
        )
    return IndexReport(
        rebuilt=True,
        passages=built.passages,
        model=built.model,
        fingerprint=built.fingerprint,
        built_at=built.built_at,
        seconds=clock() - started,
    )
