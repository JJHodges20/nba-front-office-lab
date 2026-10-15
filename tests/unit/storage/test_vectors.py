"""The documents' vector index in ChromaDB: built whole, swapped in, searched (decision 0019)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pytest

from front_office.domain.documents import split_sections
from front_office.domain.rag import document_passages
from front_office.storage import StorageError
from front_office.storage.vectors import IndexNotBuilt, PassageIndex
from tests.rag_fakes import DOCUMENTS, words

BUILT_AT = datetime(2026, 10, 15, 12, 0)


def _passages():
    sections = [
        section for path, text in DOCUMENTS.items() for section in split_sections(path, text)
    ]
    return document_passages(sections)


def _build(path: Path, passages=None, *, model: str = "words", fingerprint: str = "f1"):
    found = passages if passages is not None else _passages()
    with PassageIndex(path) as index:
        return index.replace(
            found,
            [words(passage.embedded) for passage in found],
            model=model,
            fingerprint=fingerprint,
            built_at=BUILT_AT,
        )


def test_nothing_is_made_until_asked(tmp_path: Path) -> None:
    assert not PassageIndex.exists(tmp_path / "rag")
    with PassageIndex(tmp_path / "rag") as index:
        assert index.state() is None
        with pytest.raises(IndexNotBuilt):
            index.search(words("tokens"), 3)


def test_a_build_records_what_it_was_built_from(tmp_path: Path) -> None:
    state = _build(tmp_path / "rag")
    assert state.passages == len(_passages())
    assert (state.model, state.fingerprint, state.built_at) == ("words", "f1", BUILT_AT)
    assert PassageIndex.exists(tmp_path / "rag")
    with PassageIndex(tmp_path / "rag") as index:
        assert index.state() == state


def test_the_nearest_passages_come_first_with_where_they_are(tmp_path: Path) -> None:
    _build(tmp_path / "rag")
    with PassageIndex(tmp_path / "rag") as index:
        hits = index.search(words("When does a token expire?"), 2)
    assert len(hits) == 2
    nearest = hits[0]
    assert nearest.passage.location == "docs/ARCHITECTURE.md#the-api"
    assert nearest.passage.title == "Architecture › The API"
    assert "60 minutes" in nearest.passage.text
    assert 0 <= nearest.distance < hits[1].distance


def test_more_asked_than_held(tmp_path: Path) -> None:
    found = _passages()[:2]
    _build(tmp_path / "rag", found)
    with PassageIndex(tmp_path / "rag") as index:
        assert len(index.search(words("tokens"), 10)) == 2


def test_a_rebuild_replaces_the_index_whole(tmp_path: Path) -> None:
    path = tmp_path / "rag"
    _build(path)
    fewer = _passages()[:1]
    state = _build(path, fewer, model="other", fingerprint="f2")
    assert (state.passages, state.model, state.fingerprint) == (1, "other", "f2")
    with PassageIndex(path) as index:
        (hit,) = index.search(words("tokens"), 5)
    assert hit.passage.passage_id == fewer[0].passage_id


def test_passages_and_vectors_must_pair_up(tmp_path: Path) -> None:
    with PassageIndex(tmp_path / "rag") as index, pytest.raises(StorageError, match="2 embeddings"):
        index.replace(
            _passages()[:3], [[1.0], [1.0]], model="m", fingerprint="f", built_at=BUILT_AT
        )


def test_closing_releases_the_files(tmp_path: Path) -> None:
    path = tmp_path / "rag"
    _build(path)
    shutil.rmtree(path)  # on Windows an open index would keep its files locked
    assert not path.exists()
