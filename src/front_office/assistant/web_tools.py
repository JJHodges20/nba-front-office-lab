"""The web as the assistant's tools: a search, and reading one source by its id.

The model never writes an address (decision 0018). ``web_search`` gives each result an id -
s1, s2... - and ``read_source`` takes an id: a search result's, or a link's the user pasted
(u1...). Results from sites the lab refuses are left out, and the result says so. What a
page says reaches the model quoted, as data, and stays the page's own reporting; an
instruction in it is text like any other. Each question may search and read only so much:
its mode's budget.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import Found, Handler
from front_office.domain.assistant import Evidence, EvidenceKind, ResultStatus, Source
from front_office.pipelines.web import PageRead, read_page
from front_office.providers.web import KEY_VARIABLE, Refused, WebError, WebProvider, refused_site
from front_office.services import Lab

SNIPPET = 320
"""Characters of a search result's text the model reads."""
PAGE_TEXT = 1900
"""Characters of a page the model reads; with its heading, within one result's bound."""
MAX_LINKS = 5
"""Links taken from one message."""
LINK = re.compile(r"https?://[^\s<>\"'`)\]]+", re.IGNORECASE)


@dataclass(slots=True)
class WebBudget:
    """What one question may still do on the web."""

    searches: int
    pages: int


class SourceBook:
    """The sources one question may read, by id: those it came with, then each search's."""

    def __init__(self, given: Sequence[Source] = ()) -> None:
        self._by_id: dict[str, Source] = {}
        for source in given:
            self._by_id.setdefault(source.id, source)
        self.read: dict[str, PageRead] = {}

    def add(self, url: str, title: str) -> Source:
        """The id of ``url``: the one it already has, or the next ``s`` number."""
        for source in self._by_id.values():
            if source.url == url:
                return source
        taken = [int(key[1:]) for key in self._by_id if key[0] == "s" and key[1:].isdigit()]
        source = Source(id=f"s{max(taken, default=0) + 1}", url=url, title=title[:200])
        self._by_id[source.id] = source
        return source

    def get(self, source_id: str) -> Source | None:
        return self._by_id.get(source_id)

    @property
    def sources(self) -> tuple[Source, ...]:
        return tuple(self._by_id.values())


def links_in(text: str, already: Sequence[Source] = ()) -> tuple[Source, ...]:
    """The links pasted into a message, as sources ``u1``, ``u2``... after those already
    given; a link given before keeps its id."""
    known = {source.url for source in already}
    taken = [int(s.id[1:]) for s in already if s.id[0] == "u" and s.id[1:].isdigit()]
    number = max(taken, default=0)
    found: list[Source] = []
    for match in LINK.finditer(text):
        url = match.group(0).rstrip(".,;:!?")
        if url in known or len(found) >= MAX_LINKS:
            continue
        known.add(url)
        number += 1
        found.append(Source(id=f"u{number}", url=url, title="Pasted by the user"))
    return tuple(found)


def web_handlers(
    web: WebProvider | None, book: SourceBook, budget: WebBudget
) -> dict[str, Handler]:
    """``web_search`` and ``read_source`` for one question."""

    def web_search(lab: Lab, args: t.WebSearch) -> Found:
        title = f'Web search: "{args.query}"'
        if web is None or not web.can_search:
            return Found(
                ResultStatus.UNAVAILABLE,
                title,
                f"Web search is not set up on this machine ({KEY_VARIABLE} is in neither the "
                "environment nor the project's .env file), so nothing was searched. Links the "
                "user pastes can still be read.",
            )
        if budget.searches <= 0:
            return Found(
                ResultStatus.UNAVAILABLE,
                title,
                "This question's searches are used up; answer from the results above.",
            )
        budget.searches -= 1
        try:
            hits = web.search(args.query, args.max_results)
        except WebError as error:
            return Found(ResultStatus.UNAVAILABLE, title, f"The search failed: {error}.")
        when = web.now()
        kept = [hit for hit in hits if refused_site(_host(hit.url)) is None]
        left_out = len(hits) - len(kept)
        warnings = (
            (f"{left_out} result(s) from sites the lab does not read were left out.",)
            if left_out
            else ()
        )
        if not kept:
            return Found(
                ResultStatus.EMPTY,
                title,
                "The search found nothing the lab may read.",
                None,
                (),
                warnings,
            )
        lines = [
            f"Found {when:%Y-%m-%d %H:%M} UTC by Ollama web search. Each snippet is the site's "
            "own text, unchecked by the lab. To read a page, call read_source with its source "
            'id, such as source_id "s1" - not the result id.'
        ]
        rows, evidence = [], []
        for hit in kept:
            source = book.add(hit.url, hit.title)
            host = _host(hit.url)
            lines.append(f"{source.id}: {hit.title or 'Untitled'} ({host}) <{hit.url}>")
            lines.append(f"    {_snippet(hit.content)}")
            rows.append((source.id, hit.title, host, hit.url))
            evidence.append(
                Evidence(
                    EvidenceKind.WEB,
                    f"{hit.title or host} ({host}), a search result",
                    location=hit.url,
                    retrieved_at=when,
                )
            )
        return Found(
            ResultStatus.OK,
            title,
            "\n".join(lines),
            pd.DataFrame(rows, columns=["source_id", "title", "site", "url"]),
            tuple(evidence),
            warnings,
            ("reported",),
        )

    def read_source(lab: Lab, args: t.ReadSource) -> Found:
        source = book.get(args.source_id)
        if source is None:
            known = ", ".join(s.id for s in book.sources) or "none yet"
            # Live at A2 the model asked for "r1": a result's id, not a source's.
            what = (
                f"{args.source_id} names a tool result, not a source"
                if args.source_id.startswith("r")
                else f"There is no source {args.source_id} in this conversation"
            )
            return Found(
                ResultStatus.ERROR,
                f"Source {args.source_id}",
                f"{what}. The sources are: {known}. A source id comes from web_search or from "
                "a link the user pasted; call read_source with one of them.",
            )
        host = _host(source.url)
        title = f"{source.id}: {source.title or host}"
        page = book.read.get(source.id)
        if page is None:
            if web is None:
                return Found(ResultStatus.UNAVAILABLE, title, "Pages cannot be read here.")
            if budget.pages <= 0:
                return Found(
                    ResultStatus.UNAVAILABLE,
                    title,
                    "This question's page reads are used up; answer from the results above.",
                )
            budget.pages -= 1
            try:
                page = read_page(web, source.url)
            except Refused as why:
                return Found(ResultStatus.UNAVAILABLE, title, f"{source.id} was not read: {why}.")
            except WebError as error:
                return Found(
                    ResultStatus.UNAVAILABLE, title, f"{source.id} could not be read: {error}."
                )
            book.read[source.id] = page
        site = page.site_name or _host(page.url)
        published = (
            f"published {page.published_at:%Y-%m-%d}"
            if page.published_at
            else "no publication date given"
        )
        if page.updated_at and (page.published_at is None or page.updated_at > page.published_at):
            published += f", updated {page.updated_at:%Y-%m-%d}"
        evidence = Evidence(
            EvidenceKind.WEB,
            f"{page.title or source.title or site} ({site})",
            location=page.url,
            retrieved_at=page.retrieved_at,
            published_at=page.published_at,
        )
        if not page.text.strip():
            return Found(
                ResultStatus.EMPTY,
                title,
                f"{source.id} has no text the lab can read; it may need a browser to show it.",
                None,
                (evidence,),
            )
        head = (
            f"{page.title or source.title or 'Untitled'} - {site}, {published}; read "
            f"{page.retrieved_at:%Y-%m-%d %H:%M} UTC from <{page.url}>. The page's own words, "
            "unchecked by the lab:"
        )
        warnings = []
        if page.truncated:
            warnings.append("The page was longer than the lab reads; only its start was read.")
        return Found(
            ResultStatus.OK,
            title,
            head + "\n" + _excerpt(page.text, PAGE_TEXT),
            None,
            (evidence,),
            tuple(warnings),
            ("reported",),
        )

    return {"web_search": web_search, "read_source": read_source}


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").removeprefix("www.") or url
    except ValueError:
        return url


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET else flat[: flat.rfind(" ", 0, SNIPPET)] + " ..."


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = text.rfind(" ", 0, limit)
    return text[:cut] + "\n(the page goes on)"
