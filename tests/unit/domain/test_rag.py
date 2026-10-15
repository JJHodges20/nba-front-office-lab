"""The documents' passages as the vector index keeps them, and what an index is built from."""

from __future__ import annotations

from datetime import datetime

from front_office.domain.documents import split_sections
from front_office.domain.rag import (
    IndexState,
    IndexStatus,
    document_passages,
    index_fingerprint,
)

DOCUMENT = """\
# Architecture

Built in layers.

## The API

Signs users in with tokens.

Tokens expire.
"""


def _passages(text: str = DOCUMENT, size: int = 900):
    return document_passages(split_sections("docs/ARCHITECTURE.md", text), size=size)


def test_a_passage_keeps_where_it_is_and_its_title() -> None:
    first, second = _passages()
    assert first.title == "Architecture"  # text under the title alone
    assert second.title == "Architecture › The API"
    assert second.location == "docs/ARCHITECTURE.md#the-api"
    assert second.text == "Signs users in with tokens.\n\nTokens expire."
    assert (
        second.embedded == "Architecture › The API\n\nSigns users in with tokens.\n\nTokens expire."
    )


def test_long_sections_are_cut_into_the_assistants_passages() -> None:
    found = _passages(size=30)
    assert [passage.text for passage in found] == [
        "Built in layers.",
        "Signs users in with tokens.",
        "Tokens expire.",
    ]
    assert len({passage.passage_id for passage in found}) == 3


def test_an_id_is_stable_and_changes_with_the_words() -> None:
    assert [p.passage_id for p in _passages()] == [p.passage_id for p in _passages()]
    changed = _passages(DOCUMENT.replace("Tokens expire.", "Tokens expire after an hour."))
    assert changed[0].passage_id == _passages()[0].passage_id
    assert changed[1].passage_id != _passages()[1].passage_id


def test_a_document_can_be_left_out() -> None:
    sections = (
        *split_sections("docs/A.md", "# A\n\nKept.\n"),
        *split_sections("docs/research/DRAFTED.md", "# Drafted\n\nA model wrote this.\n"),
    )
    found = document_passages(sections, left_out=("docs/research/DRAFTED.md",))
    assert [passage.path for passage in found] == ["docs/A.md"]


def test_passages_alike_in_place_and_words_get_ids_of_their_own() -> None:
    sections = split_sections("docs/X.md", "# X\n\n## A\n\nSame.\n")
    found = document_passages((*sections, *sections))
    assert len({passage.passage_id for passage in found}) == 2


def test_the_fingerprint_follows_the_passages_the_model_and_the_prefix() -> None:
    found = _passages()
    base = index_fingerprint(found, model="m", prefix="p: ")
    assert base == index_fingerprint(found, model="m", prefix="p: ")
    assert base != index_fingerprint(found, model="other", prefix="p: ")
    assert base != index_fingerprint(found, model="m", prefix="")
    assert base != index_fingerprint(found[:1], model="m", prefix="p: ")


def test_an_index_status_says_built_current_and_able_to_answer() -> None:
    built = IndexState(passages=3, model="m", fingerprint="f", built_at=datetime(2026, 10, 15))
    assert not IndexStatus(None, "m", "f", 3).is_built
    assert not IndexStatus(None, "m", "f", 3).can_answer
    current = IndexStatus(built, "m", "f", 3)
    assert current.is_current and current.can_answer
    older = IndexStatus(built, "m", "g", 4)
    assert not older.is_current and older.can_answer  # older documents still answer
    other_model = IndexStatus(built, "n", "h", 3)
    assert not other_model.is_current and not other_model.can_answer
