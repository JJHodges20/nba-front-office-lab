"""Which handlers answer one question: the lab's, the current data's and the web's.

Built afresh for every question, because the web's handlers carry the question's sources
and its budget: searches and pages read, by mode (docs/AI_ASSISTANT_SPEC.md). The lab's
own handlers need nothing but the lab. Tests build a toolbox with fakes, or with the lab's
handlers alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from front_office.assistant.current_tools import Refresh, current_handlers
from front_office.assistant.lab_tools import HANDLERS, Handler
from front_office.assistant.web_tools import SourceBook, WebBudget, web_handlers
from front_office.domain.assistant import Context, Mode
from front_office.pipelines.current import refresh_current
from front_office.providers.web import WebProvider
from front_office.services import Lab

WEB_LIMITS: Mapping[Mode, tuple[int, int]] = {Mode.QUICK: (1, 2), Mode.DEEP: (4, 8)}
"""Web searches and pages read for one question, by mode."""


class Toolbox:
    def __init__(
        self,
        *,
        refresh: Refresh | None = None,
        web: WebProvider | None = None,
        current: bool = True,
        online: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._refresh = refresh
        self._web = web
        self._current = current
        self._online = online
        self._now = now

    @classmethod
    def for_lab(cls, lab: Lab) -> Toolbox:
        """Everything: current data fetched when due, and the web through the user's key."""
        settings = lab.settings

        def refresh(sources: Sequence[str]) -> object:
            return refresh_current(settings, sources=sources)

        return cls(refresh=refresh, web=WebProvider(env_file=settings.project_root / ".env"))

    @classmethod
    def lab_only(cls) -> Toolbox:
        """The lab's own data and nothing fetched: no current data, no web."""
        return cls(current=False, online=False)

    def handlers(self, context: Context) -> dict[str, Handler]:
        found = dict(HANDLERS)
        if self._current:
            clock = {} if self._now is None else {"now": self._now}
            found |= current_handlers(self._refresh, **clock)
        if self._online:
            searches, pages = WEB_LIMITS[context.mode]
            book = SourceBook(context.sources)
            found |= web_handlers(self._web, book, WebBudget(searches, pages))
        return found
