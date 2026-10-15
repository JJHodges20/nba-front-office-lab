"""The lab's own API, as the Ask the Docs page reaches it (decision 0019).

The one module of the workbench that opens a connection, and only to the address
``FOL_API_URL`` names - ``http://127.0.0.1:8000`` when it names none, ``http://api:8000``
inside Docker Compose - never an address a page or a model wrote. The architecture test
names this module as the exception to "the workbench reaches the network through nothing".

Every call returns the API's JSON as it came, or raises :class:`ApiError` with the API's
own words: the page shows them as they are. The token a sign-in returns is the page's to keep
in the session; nothing here keeps it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

API_URL = "FOL_API_URL"
DEFAULT_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 300.0
"""An answer from the local model can take a minute or more on a slow machine; building the
index, longer."""

Send = Callable[..., tuple[int, Any]]
"""Sends one request - ``send(method, url, json=..., data=..., params=..., headers=...,
timeout=...)`` - and returns the status and the decoded body."""


class ApiError(Exception):
    """The API refused a request, or could not be reached. ``detail`` is what to show."""

    def __init__(self, detail: str, status: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


class ApiUnreachable(ApiError):
    """Nothing answered at the address."""


class SignedOut(ApiError):
    """The token is missing, expired or no longer names a user: sign in again."""


def requests_send(method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException as error:
        raise ApiUnreachable(f"Nothing answered at {url}: {error}") from error
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _detail(body: Any, status: int) -> str:
    """The API's reason, in its words: one line for a refusal, the first field's for 422."""
    detail = body.get("detail") if isinstance(body, Mapping) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail and isinstance(detail[0], Mapping):
        first = detail[0]
        field = ".".join(str(part) for part in first.get("loc", ())[1:])
        message = str(first.get("msg", "not accepted")).removeprefix("Value error, ")
        return f"{field}: {message}" if field else message
    return f"The API answered {status}."


@dataclass(frozen=True, slots=True)
class LabApi:
    """The API at ``base_url``."""

    base_url: str
    send: Send = requests_send
    timeout: float = TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        parts = urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"{API_URL} must be an http address, not {self.base_url!r}")

    def _call(
        self, method: str, path: str, *, token: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        status, body = self.send(
            method,
            self.base_url.rstrip("/") + path,
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        if status == 401 and token is not None:
            raise SignedOut(_detail(body, status), status)
        if status >= 400:
            raise ApiError(_detail(body, status), status)
        return body if isinstance(body, dict) else {}

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/health")

    def register(self, username: str, password: str) -> dict[str, Any]:
        return self._call(
            "POST", "/auth/register", json={"username": username, "password": password}
        )

    def sign_in(self, username: str, password: str) -> dict[str, Any]:
        """The token, as ``access_token``, and how many seconds it lasts."""
        return self._call("POST", "/auth/token", data={"username": username, "password": password})

    def me(self, token: str) -> dict[str, Any]:
        return self._call("GET", "/auth/me", token=token)

    def remove_account(self, token: str) -> dict[str, Any]:
        return self._call("DELETE", "/auth/me", token=token)

    def ask(self, token: str, question: str) -> dict[str, Any]:
        return self._call("POST", "/rag/ask", token=token, json={"question": question})

    def questions(self, token: str, limit: int = 20) -> dict[str, Any]:
        return self._call("GET", "/rag/questions", token=token, params={"limit": limit})

    def forget(self, token: str, question_id: int) -> dict[str, Any]:
        return self._call("DELETE", f"/rag/questions/{int(question_id)}", token=token)

    def index(self, token: str) -> dict[str, Any]:
        return self._call("GET", "/rag/index", token=token)

    def build_index(self, token: str, *, force: bool = False) -> dict[str, Any]:
        return self._call("POST", "/rag/index", token=token, params={"force": force})


def connect() -> LabApi:
    """The API at the address ``FOL_API_URL`` names. Tests put an app of their own here."""
    return LabApi(os.environ.get(API_URL, "").strip() or DEFAULT_URL)
