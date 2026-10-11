"""A news feed as items the assistant can show: RSS 2.0 or Atom, read as a feed reader reads
it (decision 0018, A7).

A pure function of the bytes a feed came as. A feed that declares a document type or an
entity is not read: no feed needs one, and expanding them is how XML is turned against its
reader. Each item keeps the site's own headline, dates, author, tags and the start of its
excerpt as plain text, with its address; nothing in it is acted on. The same article in
several feeds - a site's main feed, its feed of moves and a team's - is one item, known by
its address without tracking parameters (:func:`item_id`).
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from front_office.domain.schema import conform_frame
from front_office.domain.tables.current import NEWS_ITEMS
from front_office.processing.web import page_text

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
DECLARATIONS = re.compile(rb"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
SUMMARY = 400
"""Characters of an item's excerpt kept: enough to say what it is about."""
TRACKING = ("utm_", "fbclid", "gclid", "mc_", "ref")
SEPARATOR = "; "


class FeedError(ValueError):
    """What came is not a feed the lab reads."""


@dataclass(frozen=True, slots=True)
class FeedItem:
    title: str
    link: str
    published_at: datetime | None
    """UTC, without a zone marker."""
    updated_at: datetime | None
    author: str | None
    categories: tuple[str, ...]
    summary: str | None


def parse_feed(body: bytes) -> list[FeedItem]:
    """The items of an RSS 2.0 or Atom feed, in the order the feed gives them."""
    if b"\x00" in body:
        # In UTF-16 or UTF-32 a declaration is not the bytes looked for below; XML itself
        # never holds a zero byte.
        raise FeedError("a feed not in an ASCII-compatible encoding is not read")
    if DECLARATIONS.search(body):
        raise FeedError("a feed that declares a document type or entities is not read")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise FeedError(f"not a feed: {error}") from None
    if root.tag == "rss":
        entries, read = root.iter("item"), _rss_item
    elif root.tag == f"{ATOM}feed":
        entries, read = root.iter(f"{ATOM}entry"), _atom_entry
    else:
        raise FeedError(f"not an RSS or Atom feed (its root is {root.tag!r})")
    items = []
    for entry in entries:
        item = read(entry)
        if item.title and item.link:
            items.append(item)
    return items


def item_id(link: str) -> str:
    """An article's id: its address, without tracking parameters or a fragment, hashed."""
    return hashlib.sha256(canonical_link(link).encode("utf-8")).hexdigest()[:16]


def canonical_link(link: str) -> str:
    parts = urlsplit(link.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING)
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )


def news_frame(
    items: Iterable[FeedItem],
    *,
    site: str,
    feed_id: str,
    transactions: bool,
    retrieved_at: datetime,
) -> pd.DataFrame:
    """One feed's items as rows of ``news_items``, once each."""
    rows = {}
    for item in items:
        key = item_id(item.link)
        rows.setdefault(
            key,
            {
                "item_id": key,
                "site": site,
                "title": item.title,
                "link": canonical_link(item.link),
                "published_at": item.published_at,
                "updated_at": item.updated_at,
                "author": item.author,
                "categories": SEPARATOR.join(item.categories) or None,
                "summary": item.summary,
                "feeds": feed_id,
                "transactions": transactions,
                "retrieved_at": retrieved_at,
            },
        )
    frame = pd.DataFrame(list(rows.values()), columns=list(NEWS_ITEMS.column_names))
    return conform_frame(frame, NEWS_ITEMS)


def merge_news(held: pd.DataFrame, fresh: pd.DataFrame, *, kept_since: datetime) -> pd.DataFrame:
    """The items held and those just fetched, each article once: the feeds that carried it
    joined, the newest copy of its words kept, and anything published before
    ``kept_since`` let go."""
    frames = [frame for frame in (held, fresh) if not frame.empty]
    if not frames:
        return conform_frame(pd.DataFrame(columns=list(NEWS_ITEMS.column_names)), NEWS_ITEMS)
    both = pd.concat(frames, ignore_index=True).sort_values("retrieved_at", kind="stable")
    feeds = both.groupby("item_id")["feeds"].agg(_joined)
    moves = both.groupby("item_id")["transactions"].any()
    merged = both.drop_duplicates("item_id", keep="last").set_index("item_id")
    merged["feeds"] = feeds
    merged["transactions"] = moves
    merged = merged.reset_index()
    published = pd.to_datetime(merged["published_at"])
    merged = merged[published.isna() | (published >= pd.Timestamp(kept_since))]
    merged = merged.sort_values(["published_at", "item_id"], ascending=False, na_position="last")
    return conform_frame(merged.reset_index(drop=True), NEWS_ITEMS)


def _joined(values: Iterable[str]) -> str:
    feeds: dict[str, None] = {}
    for value in values:
        for feed in str(value).split(SEPARATOR):
            if feed:
                feeds.setdefault(feed, None)
    return SEPARATOR.join(sorted(feeds))


def _rss_item(item: ET.Element) -> FeedItem:
    author = item.findtext(f"{DC}creator") or item.findtext("author")
    return FeedItem(
        title=_plain(item.findtext("title")),
        link=(item.findtext("link") or "").strip(),
        published_at=_rfc822(item.findtext("pubDate")),
        updated_at=None,
        author=_plain(author) or None,
        categories=_tags(element.text for element in item.findall("category")),
        summary=_excerpt(item.findtext("description")),
    )


def _atom_entry(entry: ET.Element) -> FeedItem:
    links = entry.findall(f"{ATOM}link")
    link = next(
        (
            element.get("href")
            for element in links
            if element.get("rel", "alternate") == "alternate"
        ),
        None,
    )
    published = _iso(entry.findtext(f"{ATOM}published"))
    updated = _iso(entry.findtext(f"{ATOM}updated"))
    return FeedItem(
        title=_plain(entry.findtext(f"{ATOM}title")),
        link=(link or "").strip(),
        published_at=published or updated,
        updated_at=updated if updated != published else None,
        author=_plain(entry.findtext(f"{ATOM}author/{ATOM}name")) or None,
        categories=_tags(element.get("term") for element in entry.findall(f"{ATOM}category")),
        summary=_excerpt(entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content")),
    )


def _plain(text: str | None) -> str:
    """Text that may carry escaped markup, as plain words on one line."""
    if not text:
        return ""
    flat = unescape(re.sub(r"<[^>]+>", " ", unescape(text)))
    return " ".join(flat.split())


def _excerpt(html: str | None) -> str | None:
    if not html:
        return None
    text = " ".join(page_text(html.encode("utf-8"), "text/html", "utf-8").text.split())
    text = re.sub(r"\s*\[(?:…|&#8230;|\.\.\.)\]\s*$", "", text).strip()
    if not text:
        return None
    if len(text) <= SUMMARY:
        return text
    cut = text.rfind(" ", 0, SUMMARY)
    return text[: cut if cut > SUMMARY // 2 else SUMMARY].rstrip(" ,;:") + " ..."


def _tags(values: Iterable[str | None]) -> tuple[str, ...]:
    tags: dict[str, None] = {}
    for value in values:
        tag = _plain(value)
        if tag:
            tags.setdefault(tag, None)
    return tuple(tags)


def _rfc822(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        moment = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError):
        return None
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def _iso(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)
