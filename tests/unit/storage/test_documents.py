from __future__ import annotations

import pytest

from front_office.domain.documents import Section
from front_office.storage.documents import query_words, search_sections


def section(path: str, heading: str, text: str, document: str = "A document") -> Section:
    return Section(path, document, heading, heading.lower().replace(" ", "-"), text)


SECTIONS = (
    section(
        "docs/a.md",
        "What else was tried",
        "Winning percentage predicts better on seasons already played, and is left out on "
        "purpose: the model is read for a roster before its season.",
    ),
    section(
        "docs/b.md",
        "Probabilities",
        "A chance is shown with its interval and the model's record on seasons it had not seen.",
    ),
    section(
        "docs/c.md",
        "The optimizer",
        "The optimizer maximises the sum of the parts under two budgets and returns several "
        "distinct rosters. " * 3,
    ),
    section("docs/d.md", "Status", "Date: 2026-10-04."),
)


def test_the_best_matching_section_comes_first() -> None:
    hits = search_sections(SECTIONS, "Why is winning percentage left out?", limit=3)
    assert hits[0].section.path == "docs/a.md"
    assert "Winning percentage" in hits[0].excerpt


def test_words_match_on_their_stems() -> None:
    (hit,) = search_sections(SECTIONS, "probability", limit=1)
    assert hit.section.path == "docs/b.md"


def test_each_section_is_returned_once_with_its_best_passage() -> None:
    long = section("docs/e.md", "Rosters", "\n\n".join(["rosters " * 120] * 3))
    hits = search_sections((long, *SECTIONS), "rosters", limit=5)
    paths = [hit.section.path for hit in hits]
    assert len(paths) == len(set(paths)) and "docs/e.md" in paths


def test_a_section_too_short_to_say_anything_is_not_searched() -> None:
    assert search_sections(SECTIONS, "status date", limit=4) == ()


def test_the_common_words_of_a_question_are_left_out() -> None:
    assert query_words("How does the optimizer decide which rosters to show?") == (
        "optimizer",
        "rosters",
    )
    assert query_words("how does it") == ("how", "does", "it")


@pytest.mark.parametrize(
    "query",
    ['"unclosed', "optimizer OR", "NOT optimizer", "optim*", "heading:optimizer", "a(b) ^ c - d"],
)
def test_nothing_in_a_query_is_read_as_search_syntax(query: str) -> None:
    hits = search_sections(SECTIONS, query, limit=2)
    assert all(hit.section in SECTIONS for hit in hits)


def test_nothing_to_search_finds_nothing() -> None:
    assert search_sections((), "optimizer", limit=3) == ()
    assert search_sections(SECTIONS, "...", limit=3) == ()
    assert search_sections(SECTIONS, "optimizer", limit=0) == ()
