"""The web provider's guards: what may be fetched, how, and the search key's handling."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from front_office.providers.web import (
    KEY_VARIABLE,
    SEARCH_URL,
    USER_AGENT,
    Refused,
    Response,
    WebError,
    is_public,
    refused_site,
    search_key,
)
from tests.web_fakes import ARTICLE, FakeWeb, Story, page, redirect, robots, rss, search_results

URL = "https://news.example.org/knicks"
KEY = "test-key-not-real-0123456789"


class TestAddresses:
    @pytest.mark.parametrize(
        ("url", "why"),
        [
            ("ftp://news.example.org/file", "only http and https"),
            ("file:///C:/Users/notes.txt", "only http and https"),
            ("https://user:secret@news.example.org/", "credentials"),
            ("https://news.example.org:8443/", "standard web ports"),
            ("https://www.basketball-reference.com/teams/BOS/2026.html", "Sports Reference"),
            ("https://stathead.com/basketball/", "Sports Reference"),
            ("https://www.spotrac.com/nba/", "Spotrac refuses"),
            ("https://www.nba.com/news", "the league's data comes through the lab's own sources"),
            ("http://127.0.0.1/admin", "not a public address"),
            ("http://[::1]/", "not a public address"),
            ("http://169.254.169.254/latest/meta-data", "not a public address"),
            ("http://10.0.0.5/", "not a public address"),
            ("https:///no-host", "names no host"),
        ],
    )
    def test_refused(self, url: str, why: str) -> None:
        with pytest.raises(Refused, match=why):
            FakeWeb().provider().check(url)

    def test_a_name_that_resolves_to_a_private_address_is_refused(self) -> None:
        web = FakeWeb(addresses={"intranet.example.org": ["93.184.216.34", "192.168.1.20"]})
        with pytest.raises(Refused, match="not a public address"):
            web.provider().check("https://intranet.example.org/")

    def test_a_public_page_passes(self) -> None:
        assert FakeWeb().provider().check(URL) == "news.example.org"

    @pytest.mark.parametrize(
        ("address", "public"),
        [
            ("8.8.8.8", True),
            ("127.0.0.1", False),
            ("100.64.0.1", False),
            ("::ffff:127.0.0.1", False),
            ("224.0.0.1", False),
            ("fe80::1%eth0", False),
            ("not an address", False),
        ],
    )
    def test_public_addresses(self, address: str, public: bool) -> None:
        assert is_public(address) is public

    def test_refused_sites_cover_their_subdomains(self) -> None:
        assert refused_site("WWW.Basketball-Reference.com.") is not None
        assert refused_site("stats.nba.com") is not None
        assert refused_site("nbaexample.com") is None


class TestFetching:
    def test_a_page_comes_back_as_it_came_with_where_it_ended(self) -> None:
        web = FakeWeb({URL: page(ARTICLE)})
        fetched = web.provider().fetch(URL)
        assert fetched.body.decode() == ARTICLE
        assert (fetched.content_type, fetched.charset) == ("text/html", "utf-8")
        assert fetched.retrieved_at.isoformat() == "2026-10-09T18:00:00"
        method, url, headers, _ = web.requests[-1]
        assert (method, url) == ("GET", URL)
        assert headers["User-Agent"] == USER_AGENT
        assert "Authorization" not in headers and "Cookie" not in headers

    def test_every_redirect_is_checked_again(self) -> None:
        web = FakeWeb({URL: redirect("http://127.0.0.1/secret")})
        with pytest.raises(Refused, match="not a public address"):
            web.provider().fetch(URL)
        assert "http://127.0.0.1/secret" not in web.urls

    def test_a_redirect_to_a_refused_site_is_not_followed(self) -> None:
        web = FakeWeb({URL: redirect("https://www.spotrac.com/nba/contracts/")})
        with pytest.raises(Refused, match="Spotrac"):
            web.provider().fetch(URL)

    def test_a_redirect_is_followed_to_the_page(self) -> None:
        moved = "https://news.example.org/2026/knicks"
        web = FakeWeb({URL: redirect("/2026/knicks"), moved: page(ARTICLE)})
        fetched = web.provider().fetch(URL)
        assert (fetched.requested, fetched.url) == (URL, moved)

    def test_too_many_redirects_end_it(self) -> None:
        web = FakeWeb({URL: redirect(URL)})
        with pytest.raises(WebError, match="more than 5 redirects"):
            web.provider().fetch(URL)

    @pytest.mark.parametrize("status", [401, 402, 403, 429, 451])
    def test_a_login_payment_or_bot_check_is_not_worked_around(self, status: int) -> None:
        web = FakeWeb({URL: page("Subscribe", status=status)})
        with pytest.raises(Refused, match="not worked around"):
            web.provider().fetch(URL)
        assert web.urls.count(URL) == 1, "asked once, never again in another guise"

    def test_only_web_pages_are_read(self) -> None:
        web = FakeWeb({URL: page("%PDF-1.7", kind="application/pdf")})
        with pytest.raises(Refused, match="not a web page"):
            web.provider().fetch(URL)

    def test_a_connection_that_lands_on_a_private_address_is_refused(self) -> None:
        sneaky = Response(200, {"content-type": "text/html"}, b"<p>hi</p>", peer="10.1.2.3")
        with pytest.raises(Refused, match="not public"):
            FakeWeb({URL: sneaky}).provider().fetch(URL)

    def test_a_long_page_is_cut_and_says_so(self) -> None:
        web = FakeWeb({URL: page("<p>" + "word " * 5000 + "</p>")})
        fetched = web.provider(page_bytes=1000).fetch(URL)
        assert len(fetched.body) == 1000 and fetched.truncated


class TestFeeds:
    """A7: a news feed is fetched with every check a page passes."""

    FEED = "https://news.example.org/feed"
    STORY = Story("A signing", "https://news.example.org/a-signing", datetime(2026, 10, 10))

    @pytest.mark.parametrize(
        "kind",
        ["application/rss+xml", "application/atom+xml", "text/xml", "text/html; charset=UTF-8"],
    )
    def test_a_feed_comes_as_a_feed_or_labelled_as_a_page(self, kind: str) -> None:
        web = FakeWeb({self.FEED: rss(self.STORY, kind=kind)})
        fetched = web.provider().fetch_feed(self.FEED)
        assert fetched.body.startswith(b"<?xml") and fetched.url == self.FEED
        (_, _, headers, _) = web.requests[-1]
        assert "application/rss+xml" in headers["Accept"]

    def test_anything_else_is_not_a_feed(self) -> None:
        web = FakeWeb({self.FEED: page("{}", kind="application/json")})
        with pytest.raises(Refused, match="not a feed"):
            web.provider().fetch_feed(self.FEED)

    def test_robots_rules_for_ai_agents_hold_for_feeds_too(self) -> None:
        rules = robots("User-agent: ChatGPT-User\nDisallow: /\n")
        web = FakeWeb({"https://news.example.org/robots.txt": rules, self.FEED: rss(self.STORY)})
        with pytest.raises(Refused, match=r"AI agents \(ChatGPT-User\)"):
            web.provider().fetch_feed(self.FEED)
        assert self.FEED not in web.urls

    def test_a_feed_redirected_elsewhere_is_checked_again(self) -> None:
        web = FakeWeb({self.FEED: redirect("https://www.nba.com/feed")})
        with pytest.raises(Refused, match="the league's data comes through"):
            web.provider().fetch_feed(self.FEED)


class TestRobots:
    ROBOTS = "https://news.example.org/robots.txt"

    def test_a_site_that_turns_ai_agents_away_turns_the_lab_away(self) -> None:
        rules = robots("User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
        web = FakeWeb({self.ROBOTS: rules, URL: page(ARTICLE)})
        with pytest.raises(Refused, match=r"robots.txt asks AI agents \(GPTBot\)"):
            web.provider().fetch(URL)
        assert URL not in web.urls

    def test_rules_for_everyone_apply_to_the_lab(self) -> None:
        web = FakeWeb(
            {self.ROBOTS: robots("User-agent: *\nDisallow: /knicks\n"), URL: page(ARTICLE)}
        )
        with pytest.raises(Refused, match="robots.txt asks the lab"):
            web.provider().fetch(URL)

    def test_no_robots_file_allows_the_page(self) -> None:
        web = FakeWeb({URL: page(ARTICLE)})
        assert web.provider().fetch(URL).url == URL

    @pytest.mark.parametrize("status", [403, 500, 503])
    def test_rules_that_cannot_be_read_allow_nothing(self, status: int) -> None:
        web = FakeWeb({self.ROBOTS: Response(status, {}, b""), URL: page(ARTICLE)})
        with pytest.raises(Refused, match="robots.txt"):
            web.provider().fetch(URL)

    def test_a_sites_rules_are_read_once(self) -> None:
        other = "https://news.example.org/celtics"
        web = FakeWeb({URL: page(ARTICLE), other: page(ARTICLE)})
        provider = web.provider()
        provider.fetch(URL)
        provider.fetch(other)
        assert web.urls.count(self.ROBOTS) == 1


class TestTheSearchKey:
    def test_the_environment_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text(f"{KEY_VARIABLE}=from-the-file\n", encoding="utf-8")
        monkeypatch.setenv(KEY_VARIABLE, "from-the-environment")
        assert search_key(env) == "from-the-environment"

    @pytest.mark.parametrize(
        ("content", "encoding"),
        [
            (f"# my keys\n{KEY_VARIABLE}={KEY}\n", "utf-8"),
            (f'export {KEY_VARIABLE}="{KEY}"\r\n', "utf-8-sig"),
            (f"{KEY_VARIABLE} = '{KEY}'\r\n", "utf-16"),
        ],
    )
    def test_the_env_file_however_it_was_saved(
        self, tmp_path: Path, content: str, encoding: str
    ) -> None:
        env = tmp_path / ".env"
        env.write_bytes(content.encode(encoding))
        assert search_key(env) == KEY

    def test_ollamas_own_variable_is_never_read(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", KEY)
        env = tmp_path / ".env"
        env.write_text(f"OLLAMA_API_KEY={KEY}\n", encoding="utf-8")
        assert search_key(env) is None
        assert search_key(None) is None

    def test_the_key_goes_to_ollama_alone_and_is_never_shown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(KEY_VARIABLE, KEY)
        hit = search_results(("Knicks win", URL, "The Knicks won."))
        web = FakeWeb({SEARCH_URL: hit, URL: page(ARTICLE)})
        provider = web.provider()
        assert KEY not in repr(provider)
        hits = provider.search("Knicks title", max_results=3)
        assert [hit.url for hit in hits] == [URL]
        method, url, headers, _ = web.requests[0]
        assert (method, url, headers["Authorization"]) == ("POST", SEARCH_URL, f"Bearer {KEY}")
        assert web.searched() == [{"query": "Knicks title", "max_results": 3}]
        provider.fetch(URL)
        assert all("Authorization" not in h for _, u, h, _ in web.requests if u != SEARCH_URL)

    @pytest.mark.parametrize(
        ("answer", "message"),
        [
            (Response(401, {}, b""), "refused the key"),
            (Response(429, {}, b""), "allowance is used up"),
            (Response(500, {}, b""), "answered 500"),
            (Response(200, {}, b"<html>"), "not JSON"),
            (Response(200, {}, b'{"answer": 1}'), "without a list"),
        ],
    )
    def test_a_search_that_goes_wrong_says_how_and_never_shows_the_key(
        self, monkeypatch: pytest.MonkeyPatch, answer: Response, message: str
    ) -> None:
        monkeypatch.setenv(KEY_VARIABLE, KEY)
        with pytest.raises(WebError, match=message) as raised:
            FakeWeb({SEARCH_URL: answer}).provider().search("Knicks")
        assert KEY not in str(raised.value)

    def test_without_a_key_nothing_is_sent(self) -> None:
        web = FakeWeb()
        provider = web.provider()
        assert not provider.can_search
        with pytest.raises(WebError, match="not set up"):
            provider.search("Knicks")
        assert web.requests == []
