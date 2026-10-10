"""A web page as text the assistant can quote: its title, its site, when it was published,
its words.

A pure function of the bytes a page came as (decision 0018), with the standard library's
HTML parser. Scripts, styles, navigation, forms and the like are dropped, and an article's
text - or the main section's - is preferred to the whole page's. The publication time is
the page's own claim: a meta tag, the structured data, or the first ``<time>`` element, in
that order. Nothing in a page is acted on; this only turns markup into plain text, and the
text stays the page's - reporting, not the lab's data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

SKIPPED = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "iframe",
        "nav",
        "footer",
        "aside",
        "form",
        "button",
        "select",
        "dialog",
    }
)
"""Elements whose text is not the page's content."""
BLOCKS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "section",
        "article",
        "main",
        "blockquote",
        "pre",
        "table",
        "ul",
        "ol",
        "dd",
        "dt",
        "figcaption",
        "header",
    }
)
PUBLISHED_META = (
    "article:published_time",
    "og:published_time",
    "datepublished",
    "publishdate",
    "pubdate",
    "date",
    "dc.date",
    "dc.date.issued",
    "parsely-pub-date",
    "sailthru.date",
)
JSON_LD_PUBLISHED = re.compile(r'"datePublished"\s*:\s*"([^"]{8,40})"')
UPDATED_META = ("article:modified_time", "og:updated_time", "datemodified", "last-modified")
JSON_LD_UPDATED = re.compile(r'"dateModified"\s*:\s*"([^"]{8,40})"')
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.IGNORECASE)
MIN_ARTICLE = 200
"""Characters an article or main section needs to be taken instead of the whole page."""


@dataclass(frozen=True, slots=True)
class PageText:
    title: str
    text: str
    published_at: datetime | None
    """When the page says it was published, UTC without a zone marker."""
    site_name: str | None
    updated_at: datetime | None = None
    """When the page says it was last changed: an encyclopedia article first published
    years ago may have been changed yesterday."""


def page_text(body: bytes, content_type: str = "text/html", charset: str | None = None) -> PageText:
    """The text of a fetched page; plain text is returned as it is."""
    decoded = body.decode(_charset(body, charset), errors="replace")
    if content_type == "text/plain":
        return PageText("", _tidy(decoded), None, None)
    reader = _Reader()
    reader.feed(decoded)
    reader.close()
    sections = (_tidy("".join(parts)) for parts in (reader.article, reader.main))
    text = next((part for part in sections if len(part) >= MIN_ARTICLE), None)
    if text is None:
        text = _tidy("".join(reader.body))
    published = reader.meta_published or reader.json_published or reader.time_published
    updated = next((reader.meta[name] for name in UPDATED_META if name in reader.meta), None)
    return PageText(
        title=_tidy(reader.meta.get("og:title") or "".join(reader.title)).replace("\n", " "),
        text=text,
        published_at=_when(published),
        site_name=(reader.meta.get("og:site_name") or "").strip() or None,
        updated_at=_when(updated or reader.json_updated),
    )


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.body: list[str] = []
        self.article: list[str] = []
        self.main: list[str] = []
        self.meta: dict[str, str] = {}
        self.meta_published: str | None = None
        self.json_published: str | None = None
        self.json_updated: str | None = None
        self.time_published: str | None = None
        self._skipping = 0
        self._in_title = False
        self._in_json_ld = False
        self._json: list[str] = []
        self._article = 0
        self._main = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value or "" for name, value in attrs}
        if tag == "meta":
            self._read_meta(values)
            return
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True
        if tag == "time" and self.time_published is None and values.get("datetime"):
            self.time_published = values["datetime"]
        if tag in SKIPPED:
            self._skipping += 1
            return
        if tag == "title":
            # The document's own title: the first, and not an icon's inside an <svg>.
            self._in_title = not self._skipping and not self.title
        elif tag == "article":
            self._article += 1
        elif tag == "main":
            self._main += 1
        if tag in BLOCKS:
            self._write("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            self._read_meta({name.lower(): value or "" for name, value in attrs})
        elif tag in BLOCKS:
            self._write("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            data = "".join(self._json)
            found = JSON_LD_PUBLISHED.search(data)
            if found and self.json_published is None:
                self.json_published = found.group(1)
            changed = JSON_LD_UPDATED.search(data)
            if changed and self.json_updated is None:
                self.json_updated = changed.group(1)
            self._json = []
        if tag in SKIPPED:
            self._skipping = max(0, self._skipping - 1)
            return
        if tag == "title":
            self._in_title = False
        elif tag == "article":
            self._article = max(0, self._article - 1)
        elif tag == "main":
            self._main = max(0, self._main - 1)
        if tag in BLOCKS:
            self._write("\n")

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json.append(data)
            return
        if self._in_title:
            self.title.append(data)
            return
        if not self._skipping:
            self._write(data)

    def _write(self, text: str) -> None:
        if self._skipping:
            return
        self.body.append(text)
        if self._article:
            self.article.append(text)
        if self._main:
            self.main.append(text)

    def _read_meta(self, values: dict[str, str]) -> None:
        name = (
            values.get("property") or values.get("name") or values.get("itemprop") or ""
        ).lower()
        content = values.get("content", "").strip()
        if not name or not content:
            return
        self.meta.setdefault(name, content)
        if name in PUBLISHED_META and self.meta_published is None:
            self.meta_published = content


def _charset(body: bytes, stated: str | None) -> str:
    for candidate in (stated, _sniffed(body)):
        if candidate:
            try:
                "".encode(candidate)
            except LookupError:
                continue
            return candidate
    return "utf-8"


def _sniffed(body: bytes) -> str | None:
    found = META_CHARSET.search(body[:4096])
    return found.group(1).decode("ascii", "replace").lower() if found else None


def _tidy(text: str) -> str:
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", line).strip() for line in text.split("\n"))
    kept: list[str] = []
    for line in lines:
        if line and (not kept or kept[-1] != line):
            kept.append(line)
    return "\n".join(kept)


def _when(value: str | None) -> datetime | None:
    """A page's date as UTC; a bare date is taken as midnight UTC."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:19], text[:10]):
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if moment.tzinfo is not None:
            moment = moment.astimezone(UTC).replace(tzinfo=None)
        return moment
    return None
