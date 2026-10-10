"""Reading a web page for the assistant: the guarded fetch, then the page as text.

Decision 0018. The assistant reaches the web through this module and ``providers.web``
alone: the provider fetches - every check, again after every redirect - and
``processing.web`` turns what came into text. Nothing is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from front_office.processing.web import page_text
from front_office.providers.web import WebProvider


@dataclass(frozen=True, slots=True)
class PageRead:
    requested: str
    url: str
    """Where the page was read, after any redirect."""
    title: str
    site_name: str | None
    text: str
    published_at: datetime | None
    """When the page says it was published (UTC), if it says."""
    updated_at: datetime | None
    """When the page says it was last changed (UTC), if it says."""
    retrieved_at: datetime
    truncated: bool
    """Whether the page was longer than the lab reads."""


def read_page(provider: WebProvider, url: str) -> PageRead:
    """A page's text; ``providers.web.Refused`` or ``WebError`` say why there is none."""
    fetched = provider.fetch(url)
    page = page_text(fetched.body, fetched.content_type, fetched.charset)
    return PageRead(
        requested=fetched.requested,
        url=fetched.url,
        title=page.title,
        site_name=page.site_name,
        text=page.text,
        published_at=page.published_at,
        updated_at=page.updated_at,
        retrieved_at=fetched.retrieved_at,
        truncated=fetched.truncated,
    )
