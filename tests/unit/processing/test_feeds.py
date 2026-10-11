"""A news feed read as a feed reader reads it (A7): RSS and Atom, each article once, nothing
in it acted on, and a feed that declares entities not read at all."""

from __future__ import annotations

from datetime import datetime

import pytest

from front_office.processing.feeds import (
    SUMMARY,
    FeedError,
    canonical_link,
    item_id,
    merge_news,
    news_frame,
    parse_feed,
)
from tests.web_fakes import Story, atom, rss

PODZIEMSKI = Story(
    "Warriors Sign Podziemski To Five-Year Extension",
    "https://www.hoopsrumors.com/2026/10/warriors-podziemski-extension.html",
    datetime(2026, 10, 10, 23, 47, 27),
    ("Golden State Warriors", "Transactions", "Brandin Podziemski"),
    "<p>6:48 pm: Podziemski&#8217;s extension is official, the Warriors announced. "
    "<a href='https://x.example'>Read more</a> [&#8230;]</p>",
)
NOTES = Story(
    "Celtics Notes: Tatum, Mazzulla",
    "https://www.hoopsrumors.com/2026/10/celtics-notes.html?utm_source=rss#comments",
    datetime(2026, 10, 11, 1, 23, 44),
    ("Boston Celtics", "Jayson Tatum", "Brandon Williams (Player)"),
    "Tatum is ahead of schedule. " * 40,
)


def test_rss_as_the_site_writes_it() -> None:
    (item,) = parse_feed(rss(PODZIEMSKI).body)
    assert item.title == "Warriors Sign Podziemski To Five-Year Extension"
    assert item.published_at == datetime(2026, 10, 10, 23, 47, 27), "UTC, without a zone"
    assert item.categories == ("Golden State Warriors", "Transactions", "Brandin Podziemski")
    assert item.author == "A Writer"
    assert item.summary == (
        "6:48 pm: Podziemski’s extension is official, the Warriors announced. Read more"
    ), "plain text: no markup, entities read, the site's [...] dropped"


def test_atom_as_a_team_feed_writes_it() -> None:
    (item,) = parse_feed(atom(NOTES).body)
    assert item.link == NOTES.link
    assert item.published_at == datetime(2026, 10, 11, 1, 23, 44)
    assert item.categories[-1] == "Brandon Williams (Player)"
    assert item.summary is not None and len(item.summary) <= SUMMARY + 4
    assert item.summary.endswith(" ...")


def test_a_feed_that_declares_entities_is_not_read() -> None:
    laughs = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;">]><rss><channel><item><title>&lol2;</title>'
        b"</item></channel></rss>"
    )
    with pytest.raises(FeedError, match="declares a document type or entities"):
        parse_feed(laughs)


def test_a_feed_whose_declarations_cannot_be_seen_is_not_read() -> None:
    """In UTF-16 a declaration is not the bytes the check looks for; XML holds no zero byte."""
    laughs = (
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        "<rss><channel><item><title>&lol;</title></item></channel></rss>"
    )
    with pytest.raises(FeedError, match="ASCII-compatible"):
        parse_feed(laughs.encode("utf-16"))


@pytest.mark.parametrize(
    "body",
    [b"<html><body><p>A web page</p></body></html>", b"not xml at all <<", b"{}"],
)
def test_what_is_not_a_feed_says_so(body: bytes) -> None:
    with pytest.raises(FeedError):
        parse_feed(body)


def test_an_item_without_a_headline_or_a_link_is_left_out() -> None:
    blank = Story("", "https://example.org/a", datetime(2026, 10, 1))
    assert [item.title for item in parse_feed(rss(blank, PODZIEMSKI).body)] == [PODZIEMSKI.title]


def test_one_article_has_one_id_however_its_address_is_dressed() -> None:
    plain = "https://www.hoopsrumors.com/2026/10/celtics-notes.html"
    assert canonical_link(NOTES.link) == plain
    assert item_id(NOTES.link) == item_id(plain) == item_id(plain + "#top")
    assert item_id(plain) != item_id("https://www.hoopsrumors.com/2026/10/other.html")
    assert canonical_link("https://Example.ORG/a?id=7&utm_medium=x") == "https://example.org/a?id=7"


def test_an_article_in_several_feeds_is_kept_once_with_each_feed() -> None:
    when = datetime(2026, 10, 11, 2, 0)
    moves = news_frame(
        parse_feed(rss(PODZIEMSKI).body),
        site="Hoops Rumors",
        feed_id="hoopsrumors-transactions",
        transactions=True,
        retrieved_at=when,
    )
    team = news_frame(
        parse_feed(atom(PODZIEMSKI, NOTES).body),
        site="Hoops Rumors",
        feed_id="hoopsrumors-gsw",
        transactions=False,
        retrieved_at=when,
    )
    merged = merge_news(moves, team, kept_since=datetime(2026, 6, 1))
    assert len(merged) == 2
    extension = merged.set_index("title").loc[PODZIEMSKI.title]
    assert extension["feeds"] == "hoopsrumors-gsw; hoopsrumors-transactions"
    assert bool(extension["transactions"]), "a feed of moves carried it"
    assert merged["title"].tolist() == [NOTES.title, PODZIEMSKI.title], "newest first"


def test_items_are_let_go_after_their_days() -> None:
    old = Story("Summer League notes", "https://example.org/old", datetime(2026, 7, 10))
    frame = news_frame(
        parse_feed(rss(old, PODZIEMSKI).body),
        site="Hoops Rumors",
        feed_id="hoopsrumors",
        transactions=False,
        retrieved_at=datetime(2026, 10, 11),
    )
    held = merge_news(frame.iloc[0:0], frame, kept_since=datetime(2026, 8, 1))
    assert held["title"].tolist() == [PODZIEMSKI.title]
