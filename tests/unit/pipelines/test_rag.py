"""Building the documents' vector index (decision 0019)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from front_office.config import Settings
from front_office.pipelines.rag import IndexingFailed, NothingToIndex, index_documents
from front_office.providers.ollama import NotLocal, OllamaProvider
from front_office.services.passages import PassageService
from front_office.storage.vectors import PassageIndex
from tests.ollama_fakes import ScriptedOllama
from tests.rag_fakes import ollama, write_documents

BUILT_AT = datetime(2026, 10, 15, 12, 0)


@pytest.fixture
def documented(settings: Settings) -> Settings:
    write_documents(settings.project_root)
    return settings


def _build(settings: Settings, transport: ScriptedOllama | None = None, **kwargs: object):
    transport = transport or ollama()
    return index_documents(
        settings,
        provider=OllamaProvider(transport=transport),
        now=lambda: BUILT_AT,
        **kwargs,  # type: ignore[arg-type]
    )


def test_every_passage_of_the_searched_documents_is_embedded(documented: Settings) -> None:
    transport = ollama()
    report = _build(documented, transport)
    assert report.rebuilt
    assert report.built_at == BUILT_AT
    assert report.model == "nomic-embed-text"
    texts = [text for payload in transport.embed_payloads for text in payload["input"]]
    assert len(texts) == report.passages
    assert all(text.startswith("search_document: ") for text in texts)
    # The glossary is left out, as the assistant's keyword search leaves it out.
    assert not any("glossary is generated" in text for text in texts)
    assert any(text.startswith("search_document: Architecture › The API\n\n") for text in texts)


def test_text_a_model_wrote_is_left_out(documented: Settings) -> None:
    drafted = Path(documented.project_root) / "docs" / "research" / "EXPERIMENT_PROPOSALS.md"
    drafted.parent.mkdir(parents=True, exist_ok=True)
    drafted.write_text(
        "# Proposals\n\n## Drafted\n\nA model drafted this idea.\n", encoding="utf-8"
    )
    transport = ollama()
    _build(documented, transport)
    texts = [text for payload in transport.embed_payloads for text in payload["input"]]
    assert not any("drafted this idea" in text for text in texts)


def test_the_passages_go_in_batches(documented: Settings) -> None:
    api_file = documented.config_dir / "api.yaml"
    api_file.write_text(
        api_file.read_text(encoding="utf-8").replace("batch: 32", "batch: 2"), encoding="utf-8"
    )
    transport = ollama()
    report = _build(documented, transport)
    sizes = [len(payload["input"]) for payload in transport.embed_payloads]
    assert sum(sizes) == report.passages
    assert max(sizes) == 2


def test_an_index_that_matches_is_left_alone_unless_forced(documented: Settings) -> None:
    first = _build(documented)
    transport = ollama()
    again = _build(documented, transport)
    assert not again.rebuilt
    assert again.fingerprint == first.fingerprint
    assert transport.embed_payloads == []  # nothing embedded
    forced = _build(documented, ollama(), force=True)
    assert forced.rebuilt


def test_a_changed_document_is_indexed_again(documented: Settings) -> None:
    first = _build(documented)
    page = Path(documented.project_root) / "docs" / "WORKBENCH.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nA new line.\n", encoding="utf-8")
    second = _build(documented)
    assert second.rebuilt
    assert second.fingerprint != first.fingerprint
    assert PassageService(documented).status().is_current


@pytest.mark.parametrize(
    ("transport", "said"),
    [
        (ScriptedOllama(down=True), "Ollama is not answering"),
        (ScriptedOllama(models=["qwen3:8b"]), "ollama pull nomic-embed-text"),
    ],
)
def test_ollama_not_ready_is_said_plainly_and_the_old_index_kept(
    documented: Settings, transport: ScriptedOllama, said: str
) -> None:
    first = _build(documented)
    page = Path(documented.project_root) / "docs" / "WORKBENCH.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")
    with pytest.raises(IndexingFailed, match=said):
        _build(documented, transport)
    with PassageIndex(documented.rag_dir) as index:
        kept = index.state()
    assert kept is not None and kept.fingerprint == first.fingerprint


def test_a_model_off_this_machine_is_refused(documented: Settings) -> None:
    class Refusing:
        def embed(self, model: str, texts: object) -> None:
            raise NotLocal("'http://192.168.1.20:11434' is not a loopback address")

    with pytest.raises(IndexingFailed, match="loopback"):
        index_documents(documented, provider=Refusing(), now=lambda: BUILT_AT)  # type: ignore[arg-type]


def test_no_documents(settings: Settings) -> None:
    with pytest.raises(NothingToIndex, match="no documents to index"):
        _build(settings)
