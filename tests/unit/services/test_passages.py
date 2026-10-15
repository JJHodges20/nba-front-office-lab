"""The documents' index as a service: where it stands, and a search (decision 0019)."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import Settings
from front_office.pipelines.rag import index_documents
from front_office.providers.ollama import OllamaProvider
from front_office.services.passages import IndexNotBuilt, PassageService
from tests.rag_fakes import ollama, words, write_documents


@pytest.fixture
def documented(settings: Settings) -> Settings:
    write_documents(settings.project_root)
    return settings


def _index(settings: Settings, **kwargs: object) -> None:
    index_documents(settings, provider=OllamaProvider(transport=ollama()), **kwargs)  # type: ignore[arg-type]


def test_before_a_build(documented: Settings) -> None:
    status = PassageService(documented).status()
    assert status.built is None
    assert status.model == "nomic-embed-text"
    assert status.passages > 0
    assert not documented.rag_dir.exists()  # asking made nothing
    with pytest.raises(IndexNotBuilt):
        PassageService(documented).search(words("tokens"), 3)


def test_after_a_build_it_is_current_and_searchable(documented: Settings) -> None:
    _index(documented)
    service = PassageService(documented)
    status = service.status()
    assert status.is_current and status.can_answer
    assert status.built is not None and status.built.passages == status.passages
    (hit, *_) = service.search(words("search_query: When does a token expire?"), 3)
    assert hit.passage.location == "docs/ARCHITECTURE.md#the-api"


def test_a_changed_document_leaves_it_answering_but_not_current(documented: Settings) -> None:
    _index(documented)
    page = Path(documented.project_root) / "docs" / "WORKBENCH.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nA new line.\n", encoding="utf-8")
    status = PassageService(documented).status()
    assert status.can_answer and not status.is_current


def test_another_embedding_model_cannot_answer_from_it(documented: Settings) -> None:
    _index(documented)
    api_file = documented.config_dir / "api.yaml"
    api_file.write_text(
        api_file.read_text(encoding="utf-8").replace(
            'embedding_model: "nomic-embed-text"', 'embedding_model: "mxbai-embed-large"'
        ),
        encoding="utf-8",
    )
    status = PassageService(documented).status()
    assert status.is_built and not status.can_answer
