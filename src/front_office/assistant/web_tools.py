"""The web as the assistant's tools: the news feeds, a search, and reading one source by its id.

The model never writes an address (decision 0018). ``moves_and_rumors`` (A7) and
``web_search`` give each item or result an id - s1, s2... - and ``read_source`` takes an id:
theirs, or a link's the user pasted (u1...). One article is one source however it was found.
Results from sites the lab refuses are left out, and the result says so. What a page says
reaches the model quoted, as data, and stays the page's own reporting; an instruction in it
is text like any other. Each question may search and read only so much: its mode's budget.
The feeds are not counted against it: they are fetched when due, like the other current
information. The feeds' tool is named for what they carry: called ``news``, it drew every
question about "reporting", why a title was won included, away from the web (A7).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import Found, Handler
from front_office.domain.assistant import Evidence, EvidenceKind, ResultStatus, Source
from front_office.pipelines.web import PageRead, article_address, read_page
from front_office.providers.web import KEY_VARIABLE, Refused, WebError, WebProvider, refused_site
from front_office.services import Lab
from front_office.services.current import FAILING

NewsRefresh = Callable[[Sequence[str]], object]
"""Fetches the news feeds that are due, with the named teams' own (abbreviations):
``pipelines.current.refresh_current`` for news."""
NEWS_SHOWN = 12
"""Items the model reads, newest first: about two weeks of a team's own feed."""
NEWS_EXCERPT = 220

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
        """The id of ``url``: the one it already has - a feed's item and a search's result
        for one article are one source - or the next ``s`` number."""
        address = article_address(url)
        for source in self._by_id.values():
            if source.url == url or article_address(source.url) == address:
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
    web: WebProvider | None,
    book: SourceBook,
    budget: WebBudget,
    *,
    news_refresh: NewsRefresh | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC).replace(tzinfo=None, microsecond=0),
) -> dict[str, Handler]:
    """``news``, ``web_search`` and ``read_source`` for one question. ``news_refresh``
    fetches the feeds when due (``None``: never); ``now`` (naive UTC) dates the window."""

    def moves_and_rumors(lab: Lab, args: t.MovesAndRumors) -> Found:
        labels = lab.team_labels()
        team = args.team_id if args.team_id in labels.index else None
        abbreviation = None if team is None else str(labels.at[team, "abbreviation"])
        about = _about(lab, team, args.player_id)
        title = "Reporting from the news feeds" + (f": {about}" if about else "")
        notes: list[str] = []
        if news_refresh is not None:
            try:
                news_refresh([abbreviation] if abbreviation else [])
            except Exception as error:  # a feed that fails must not fail the question
                notes.append(f"The news feeds could not be refreshed ({error}); the last copies are used.")  # fmt: skip
        moment = now()
        state = next((s for s in lab.current.status(now=moment) if s.source == "news"), None)
        if state is None or state.stored_at is None:
            return Found(
                ResultStatus.UNAVAILABLE,
                title,
                "The news feeds could not be read"
                + (f" ({state.detail})" if state is not None and state.detail else "")
                + ", and nothing is held from before.",
                warnings=tuple(notes),
            )
        fetched = f"{state.stored_at:%Y-%m-%d %H:%M} UTC"
        if state.state == FAILING:
            notes.append(f"The last attempt to read a news feed failed ({state.detail}); the copy of {fetched} is used.")  # fmt: skip
        items = lab.current.news(
            team,
            args.player_id,
            since=moment - timedelta(days=args.days),
            moves_only=args.moves_only,
        )
        what = "moves" if args.moves_only else "items"
        window = f"the last {args.days} day{'s' if args.days != 1 else ''}"
        feeds_evidence = Evidence(
            EvidenceKind.WEB,
            "Hoops Rumors news feeds, as last fetched",
            location=state.url,
            retrieved_at=state.stored_at,
        )
        if items.empty:
            limit = (
                f"No {what} in the news feeds from {window}"
                + (f" about {about}" if about else "")
                + f", as fetched {fetched}. The feeds carry what the site wrote lately; an older "
                "story may still be found with web_search."
            )
            return Found(
                ResultStatus.OK, title, limit, None, (feeds_evidence,), tuple(notes), ("reported",), (limit,)
            )  # fmt: skip
        shown = items.head(NEWS_SHOWN)
        sites = ", ".join(sorted(set(items["site"])))
        lines = [
            f"{sites}: the {what} of {window}, newest first, as fetched {fetched}. Each headline "
            "and excerpt is the site's own words, unchecked by the lab - reporting, which "
            "changes no roster and no contract in the lab. To read an article, call read_source "
            'with its source id, such as source_id "s1". Nothing older is here: an older story, '
            "or reporting on why something happened, may be found with web_search."
        ]
        rows, evidence = [], []
        for _, item in shown.iterrows():
            source = book.add(str(item["link"]), str(item["title"]))
            published = _moment(item["published_at"])
            lines.append(
                f"{source.id}: {item['title']} - {item['site']}, {_dated(published, moment)}"
            )
            if isinstance(item["summary"], str) and item["summary"].strip():
                lines.append(f"    {_snippet(item['summary'], NEWS_EXCERPT)}")
            rows.append((source.id, published, item["title"], item["site"], bool(item["transactions"]), item["link"]))  # fmt: skip
            evidence.append(
                Evidence(
                    EvidenceKind.WEB,
                    f"{item['title']} ({item['site']}), a news item",
                    location=str(item["link"]),
                    retrieved_at=_moment(item["retrieved_at"]),
                    published_at=published,
                )
            )
        if len(items) > len(shown):
            lines.append(f"({len(items) - len(shown)} older {what} of {window} are not shown.)")
        table = pd.DataFrame(rows, columns=["source_id", "published", "headline", "site", "move", "url"])  # fmt: skip
        return Found(
            ResultStatus.OK, title, "\n".join(lines), table, tuple(evidence), tuple(notes), ("reported",)
        )  # fmt: skip

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
        dates = [address_date(hit.url) for hit in kept]
        lines = [
            f"Found {when:%Y-%m-%d %H:%M} UTC by Ollama web search, not in date order: "
            f"{sum(written is not None for _, written in dates)} of {len(kept)} results give a date "
            "in their address, and reading a page gives its own. Each snippet is the site's "
            "own text, unchecked by the lab. To read a page, call read_source with its source "
            'id, such as source_id "s1" - not the result id.'
        ]
        rows, evidence = [], []
        for hit, (dated, written) in zip(kept, dates, strict=True):
            source = book.add(hit.url, hit.title)
            host = _host(hit.url)
            said = f"dated {written} by its address" if written else "no date in its address"
            lines.append(f"{source.id}: {hit.title or 'Untitled'} ({host}) <{hit.url}>, {said}")
            lines.append(f"    {_snippet(hit.content)}")
            rows.append((source.id, hit.title, host, written, hit.url))
            evidence.append(
                Evidence(
                    EvidenceKind.WEB,
                    f"{hit.title or host} ({host}), a search result",
                    location=hit.url,
                    retrieved_at=when,
                    published_at=dated,
                )
            )
        return Found(
            ResultStatus.OK,
            title,
            "\n".join(lines),
            pd.DataFrame(rows, columns=["source_id", "title", "site", "dated", "url"]),
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

    return {
        "moves_and_rumors": moves_and_rumors,
        "web_search": web_search,
        "read_source": read_source,
    }


def _about(lab: Lab, team_id: int | None, player_id: int | None) -> str:
    """Whom a news question is about, in words."""
    parts = []
    if player_id is not None:
        players = lab.entities.players()
        if player_id in players.index:
            parts.append(str(players.at[player_id, "full_name"]))
    if team_id is not None:
        parts.append(str(lab.team_labels().at[team_id, "full_name"]))
    return ", ".join(parts)


ADDRESS_DATE = re.compile(
    r"/((?:19|20)\d{2})/(0?[1-9]|1[0-2])(?:/(0?[1-9]|[12]\d|3[01]))?(?=/|$|[-_.])"
)
"""A date in an address, as news sites write it: /2026/10/ or /2026/10/10/."""


def address_date(url: str) -> tuple[datetime | None, str | None]:
    """When a result's address says it was published, and how to say so: to the day, or to
    the month alone - which is no publication time to record. A search result carries no
    date of its own (A7)."""
    try:
        path = urlsplit(url).path
    except ValueError:
        return None, None
    found = ADDRESS_DATE.search(path)
    if found is None:
        return None, None
    year, month, day = found.group(1), found.group(2), found.group(3)
    try:
        moment = datetime(int(year), int(month), int(day or 1))
    except ValueError:
        return None, None
    return (moment, f"{moment:%Y-%m-%d}") if day else (None, f"{moment:%Y-%m}")


def _moment(value: object) -> datetime | None:
    if value is None or pd.isna(value):  # type: ignore[arg-type]
        return None
    return pd.Timestamp(value).to_pydatetime()  # type: ignore[arg-type]


def _dated(published: datetime | None, moment: datetime) -> str:
    """When an item was published, and how long ago: the answer must say how old it is."""
    if published is None:
        return "undated"
    hours = (moment - published).total_seconds() / 3600
    if hours < 1:
        ago = "within the hour"
    elif hours < 24:
        ago = f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
    else:
        days = int(hours // 24)
        ago = f"{days} day{'s' if days != 1 else ''} ago"
    return f"{published:%Y-%m-%d %H:%M} UTC, {ago}"


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").removeprefix("www.") or url
    except ValueError:
        return url


def _snippet(text: str, limit: int = SNIPPET) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: flat.rfind(" ", 0, limit)] + " ..."


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = text.rfind(" ", 0, limit)
    return text[:cut] + "\n(the page goes on)"
