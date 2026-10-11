"""The web tools: sources by id, a budget per question, refused sites left out."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest

from front_office.assistant import tools as t
from front_office.assistant.web_tools import SourceBook, WebBudget, links_in, web_handlers
from front_office.domain.assistant import EvidenceKind, ResultStatus, Source
from front_office.pipelines.current import refresh_current
from front_office.providers.web import KEY_VARIABLE, SEARCH_URL
from front_office.services import Lab
from tests.helpers import BOS, NYK
from tests.web_fakes import ARTICLE, FakeWeb, Story, atom, page, robots, rss, search_results

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


def test_a_result_says_when_its_address_dates_it(keyed: None, lab: Lab) -> None:
    """A7: a search result carries no date of its own; its address often does."""
    dated = search_results(
        ("Extension", "https://www.hoopsrumors.com/2026/10/warriors-extension.html", "Agreed."),
        ("Recap", "https://example.org/nba/2026/10/09/recap/", "Won."),
        ("Team page", "https://example.org/teams/knicks", "Roster."),
    )
    tools, _ = handlers(FakeWeb({SEARCH_URL: dated}))
    found = tools["web_search"](lab, t.WebSearch(query="Warriors extension"))
    assert "not in date order: 2 of 3 results give a date in their address" in found.text
    assert "<https://www.hoopsrumors.com/2026/10/warriors-extension.html>, dated 2026-10 by its address" in found.text  # fmt: skip
    assert "<https://example.org/nba/2026/10/09/recap/>, dated 2026-10-09 by its address" in found.text  # fmt: skip
    assert "<https://example.org/teams/knicks>, no date in its address" in found.text
    published = [item.published_at for item in found.evidence]
    assert published == [None, datetime(2026, 10, 9), None], "a month alone is no publication time"


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


class TestNews:
    """A7: reporting from the feeds - dated, each item a source to read, never the lab's data."""

    NOW = datetime(2026, 10, 21, 21, 50)
    MAIN = "https://www.hoopsrumors.com/feed"
    MOVES = "https://www.hoopsrumors.com/transactions/feed"
    CELTICS = "https://www.hoopsrumors.com/boston-celtics/feed/atom"
    EXTENSION = Story(
        "Celtics Sign Pritchard To Extension",
        "https://www.hoopsrumors.com/2026/10/pritchard.html",
        datetime(2026, 10, 21, 18, 50),
        ("Boston Celtics", "Transactions", "Payton Pritchard"),
        "<p>The Celtics and Payton Pritchard have agreed to an extension.</p>",
    )
    NOTES = Story(
        "Celtics Notes: Tatum",
        "https://www.hoopsrumors.com/2026/10/tatum.html",
        datetime(2026, 10, 18, 12, 0),
        ("Boston Celtics", "Jayson Tatum"),
    )

    def world(self, **overrides: object) -> FakeWeb:
        answers = {
            self.MAIN: rss(self.EXTENSION),
            self.MOVES: rss(self.EXTENSION),
            self.CELTICS: atom(self.EXTENSION, self.NOTES),
            self.EXTENSION.link: page(ARTICLE),
        }
        answers.update(overrides)  # type: ignore[arg-type]
        return FakeWeb(answers)

    def tools(self, scratch: Lab, web: FakeWeb, asked: list | None = None):  # type: ignore[no-untyped-def]
        provider = web.provider()

        def news_refresh(teams: Sequence[str]) -> object:
            if asked is not None:
                asked.append(list(teams))
            return refresh_current(
                scratch.settings, sources=("news",), teams=teams, now=lambda: self.NOW, web=provider
            )

        book = SourceBook(())
        found = web_handlers(
            provider, book, WebBudget(1, 2), news_refresh=news_refresh, now=lambda: self.NOW
        )
        return found, book

    def test_a_teams_news_fetches_its_own_feed_and_dates_every_item(self, scratch: Lab) -> None:
        asked: list = []
        web = self.world()
        tools, _ = self.tools(scratch, web, asked)
        found = tools["moves_and_rumors"](scratch, t.MovesAndRumors(team_id=BOS))
        assert asked == [["BOS"]] and self.CELTICS in web.urls
        assert found.status is ResultStatus.OK and found.kinds == ("reported",)
        assert found.title == "Reporting from the news feeds: Boston Celtics"
        lines = found.text.splitlines()
        assert "changes no roster and no contract in the lab" in lines[0]
        assert lines[1] == (
            "s1: Celtics Sign Pritchard To Extension - Hoops Rumors, 2026-10-21 18:50 UTC, "
            "3 hours ago"
        )
        assert lines[2] == "    The Celtics and Payton Pritchard have agreed to an extension."
        assert (
            lines[3] == "s2: Celtics Notes: Tatum - Hoops Rumors, 2026-10-18 12:00 UTC, 3 days ago"
        )
        assert found.table is not None and found.table["source_id"].tolist() == ["s1", "s2"]
        assert {e.kind for e in found.evidence} == {EvidenceKind.WEB}
        assert found.evidence[0].published_at == self.EXTENSION.published

    def test_an_item_is_read_by_its_id_and_a_search_finds_the_same_source(
        self, keyed: None, scratch: Lab
    ) -> None:
        tagged = self.EXTENSION.link + "?utm_source=search#comments"
        web = self.world(**{SEARCH_URL: search_results(("Pritchard extension", tagged, "Agreed."))})
        tools, book = self.tools(scratch, web)
        tools["moves_and_rumors"](scratch, t.MovesAndRumors(team_id=BOS))
        read = tools["read_source"](scratch, t.ReadSource(source_id="s1"))
        assert read.status is ResultStatus.OK and "How the Knicks won it all" in read.text
        searched = tools["web_search"](scratch, t.WebSearch(query="Pritchard extension"))
        assert "s1: Pritchard extension" in searched.text, "one article is one source"
        assert [source.id for source in book.sources] == ["s1", "s2"]

    def test_moves_alone_and_a_shorter_window(self, scratch: Lab) -> None:
        tools, _ = self.tools(scratch, self.world())
        moves = tools["moves_and_rumors"](scratch, t.MovesAndRumors(team_id=BOS, moves_only=True))
        recent = tools["moves_and_rumors"](scratch, t.MovesAndRumors(team_id=BOS, days=1))
        assert moves.table is not None and moves.table["headline"].tolist() == [
            self.EXTENSION.title
        ]
        assert "the moves of the last 14 days" in moves.text
        assert recent.table is not None and len(recent.table) == 1

    def test_nothing_in_the_window_is_a_dated_answer_with_its_limit(self, scratch: Lab) -> None:
        tools, _ = self.tools(scratch, self.world())
        found = tools["moves_and_rumors"](scratch, t.MovesAndRumors(team_id=NYK))
        assert found.status is ResultStatus.OK and found.table is None
        assert found.limits == (found.text,)
        assert found.text.startswith(
            "No items in the news feeds from the last 14 days about New York Knicks, as fetched "
            "2026-10-21 21:50 UTC."
        )

    def test_feeds_never_reached_are_unavailable(self, scratch: Lab) -> None:
        tools, _ = self.tools(scratch, FakeWeb())
        found = tools["moves_and_rumors"](scratch, t.MovesAndRumors())
        assert found.status is ResultStatus.UNAVAILABLE
        assert "nothing is held from before" in found.text

    def test_a_feed_that_fails_later_leaves_the_last_copy_and_says_so(self, scratch: Lab) -> None:
        tools, _ = self.tools(scratch, self.world())
        tools["moves_and_rumors"](scratch, t.MovesAndRumors())
        self.NOW += timedelta(hours=1)
        try:
            broken, _ = self.tools(scratch, FakeWeb())
            found = broken["moves_and_rumors"](scratch, t.MovesAndRumors())
        finally:
            self.NOW -= timedelta(hours=1)
        assert found.status is ResultStatus.OK
        assert any("last attempt to read a news feed failed" in note for note in found.warnings)
        assert "as fetched 2026-10-21 21:50 UTC" in found.text
