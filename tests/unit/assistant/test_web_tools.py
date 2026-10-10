"""The web tools: sources by id, a budget per question, refused sites left out."""

from __future__ import annotations

import pytest

from front_office.assistant import tools as t
from front_office.assistant.web_tools import SourceBook, WebBudget, links_in, web_handlers
from front_office.domain.assistant import EvidenceKind, ResultStatus, Source
from front_office.providers.web import KEY_VARIABLE, SEARCH_URL
from front_office.services import Lab
from tests.web_fakes import ARTICLE, FakeWeb, page, robots, search_results

STORY = "https://news.example.org/knicks"
OTHER = "https://blog.example.net/finals"
SPOTRAC = "https://www.spotrac.com/nba/new-york-knicks/"
HITS = search_results(
    ("How the Knicks won it all", STORY, "The Knicks held opponents to their lowest rate. " * 20),
    ("Knicks contracts", SPOTRAC, "Salaries."),
    ("Finals notebook", OTHER, "Brunson's Finals."),
)


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VARIABLE, "test-key-not-real")


def handlers(web: FakeWeb | None, *, sources: tuple[Source, ...] = (), searches: int = 1, pages: int = 2):  # type: ignore[no-untyped-def]  # fmt: skip
    book = SourceBook(sources)
    provider = None if web is None else web.provider()
    return web_handlers(provider, book, WebBudget(searches, pages)), book


class TestSources:
    def test_search_results_take_the_next_ids_and_keep_them(self) -> None:
        book = SourceBook((Source(id="s1", url=OTHER, title="Given"),))
        assert book.add(STORY, "Story").id == "s2"
        assert book.add(OTHER, "Again").id == "s1", "an address keeps its id"

    def test_links_pasted_into_a_message(self) -> None:
        given = (Source(id="u1", url=OTHER, title="Pasted by the user"),)
        found = links_in(f"Compare {STORY}, and {OTHER}. Also ({STORY}/2).", given)
        assert [(s.id, s.url) for s in found] == [("u2", STORY), ("u3", STORY + "/2")]

    def test_no_more_than_five_links_from_one_message(self) -> None:
        text = " ".join(f"https://example.org/{n}" for n in range(9))
        assert len(links_in(text)) == 5


class TestWebSearch:
    def test_without_a_key_nothing_is_searched_and_links_still_work(self, lab: Lab) -> None:
        web = FakeWeb()
        tools, _ = handlers(web)
        found = tools["web_search"](lab, t.WebSearch(query="Knicks title"))
        assert found.status is ResultStatus.UNAVAILABLE
        assert (
            KEY_VARIABLE in found.text and "Links the user pastes can still be read" in found.text
        )
        assert web.requests == []

    def test_results_get_ids_and_refused_sites_are_left_out(self, keyed: None, lab: Lab) -> None:
        tools, book = handlers(FakeWeb({SEARCH_URL: HITS}))
        found = tools["web_search"](lab, t.WebSearch(query="Knicks title"))
        assert found.status is ResultStatus.OK
        assert (
            "s1: How the Knicks won it all (news.example.org) <https://news.example.org/knicks>"
            in found.text
        )
        assert "s2: Finals notebook (blog.example.net)" in found.text
        assert "spotrac" not in found.text
        assert found.warnings == ("1 result(s) from sites the lab does not read were left out.",)
        assert [s.id for s in book.sources] == ["s1", "s2"]
        assert {e.kind for e in found.evidence} == {EvidenceKind.WEB}
        assert found.kinds == ("reported",)
        snippet = found.text.splitlines()[2]
        assert len(snippet) < 340 and snippet.endswith("...")

    def test_a_question_searches_only_as_often_as_its_mode_allows(
        self, keyed: None, lab: Lab
    ) -> None:
        web = FakeWeb({SEARCH_URL: HITS})
        tools, _ = handlers(web, searches=1)
        tools["web_search"](lab, t.WebSearch(query="Knicks title"))
        again = tools["web_search"](lab, t.WebSearch(query="Knicks title again"))
        assert again.status is ResultStatus.UNAVAILABLE and "used up" in again.text
        assert len(web.searched()) == 1

    def test_a_search_that_finds_nothing(self, keyed: None, lab: Lab) -> None:
        tools, _ = handlers(FakeWeb({SEARCH_URL: search_results()}))
        found = tools["web_search"](lab, t.WebSearch(query="G League draft prospect"))
        assert found.status is ResultStatus.EMPTY


class TestReadSource:
    def test_a_source_is_read_by_its_id_as_the_sites_own_words(self, lab: Lab) -> None:
        pasted = (Source(id="u1", url=STORY, title="Pasted by the user"),)
        tools, _ = handlers(FakeWeb({STORY: page(ARTICLE)}), sources=pasted)
        found = tools["read_source"](lab, t.ReadSource(source_id="u1"))
        assert found.status is ResultStatus.OK
        head = found.text.splitlines()[0]
        assert head.startswith("How the Knicks won it all - Example Sports, published 2026-06-20")
        assert "The page's own words, unchecked by the lab" in head
        (evidence,) = found.evidence
        assert (evidence.kind, evidence.location) == (EvidenceKind.WEB, STORY)
        assert evidence.published_at is not None and evidence.retrieved_at is not None

    def test_an_id_the_conversation_does_not_hold(self, lab: Lab) -> None:
        tools, _ = handlers(FakeWeb())
        found = tools["read_source"](lab, t.ReadSource(source_id="s7"))
        assert found.status is ResultStatus.ERROR
        assert "comes from web_search or from a link the user pasted" in found.text

    def test_a_refused_page_says_why(self, lab: Lab) -> None:
        rules = robots("User-agent: ClaudeBot\nDisallow: /\n")
        web = FakeWeb({"https://news.example.org/robots.txt": rules, STORY: page(ARTICLE)})
        tools, _ = handlers(web, sources=(Source(id="u1", url=STORY),))
        found = tools["read_source"](lab, t.ReadSource(source_id="u1"))
        assert found.status is ResultStatus.UNAVAILABLE
        assert "u1 was not read" in found.text and "robots.txt" in found.text

    def test_pages_count_against_the_budget_once_each(self, lab: Lab) -> None:
        sources = (Source(id="u1", url=STORY), Source(id="u2", url=OTHER), Source(id="u3", url=STORY + "/2"))  # fmt: skip
        web = FakeWeb({STORY: page(ARTICLE), OTHER: page(ARTICLE), STORY + "/2": page(ARTICLE)})
        tools, _ = handlers(web, sources=sources, pages=2)
        read = tools["read_source"]
        assert read(lab, t.ReadSource(source_id="u1")).status is ResultStatus.OK
        assert read(lab, t.ReadSource(source_id="u1")).status is ResultStatus.OK
        assert read(lab, t.ReadSource(source_id="u2")).status is ResultStatus.OK
        last = read(lab, t.ReadSource(source_id="u3"))
        assert last.status is ResultStatus.UNAVAILABLE and "used up" in last.text
        assert web.urls.count(STORY) == 1, "a page read once is not fetched again"

    def test_a_long_page_is_cut_for_the_model(self, lab: Lab) -> None:
        long = "<article>" + "".join(f"<p>Paragraph {n} of the story.</p>" for n in range(400)) + "</article>"  # fmt: skip
        tools, _ = handlers(FakeWeb({STORY: page(long)}), sources=(Source(id="u1", url=STORY),))
        found = tools["read_source"](lab, t.ReadSource(source_id="u1"))
        assert found.text.endswith("(the page goes on)")
        assert len(found.text) < 2400


def test_a_result_id_given_as_a_source_id_is_explained(lab: Lab) -> None:
    tools, _ = handlers(FakeWeb(), sources=(Source(id="s1", url=STORY),))
    found = tools["read_source"](lab, t.ReadSource(source_id="r1"))
    assert found.status is ResultStatus.ERROR
    assert found.text.startswith("r1 names a tool result, not a source. The sources are: s1.")
