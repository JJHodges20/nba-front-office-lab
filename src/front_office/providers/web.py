"""The public web for the assistant: Ollama's web search, and a guarded page fetch.

Decision 0018 and docs/AI_ASSISTANT_SPEC.md ("Safety"). A search goes to Ollama's web
search API on the user's own free account. Its key is read here and nowhere else - from the
environment variable ``FOL_OLLAMA_API_KEY``, else from that line of the project's ``.env``
- is sent to ollama.com alone, and never appears in a message, a log or an error. It is
never ``OLLAMA_API_KEY``: Ollama's own tools pick that one up by themselves.

A page - or a news feed, from A7 - is fetched only once its address passes every check,
again after every redirect: http or https on the standard port, no credentials in it, not a
site the lab refuses, every address its name resolves to public, and robots.txt allowing it
to AI agents as well as to the lab. Nothing is sent but the lab's name - no cookies, no
credentials - and a page that asks for a login, a payment or a bot check is not worked
around. What comes back is returned as it came, bounded in size and time;
``processing.web`` reads it.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from front_office.domain.env_file import setting_in

KEY_VARIABLE = "FOL_OLLAMA_API_KEY"
SEARCH_URL = "https://ollama.com/api/web_search"
USER_AGENT = "NBAFrontOfficeLab/0.1 (personal research; local)"
AGENT = "NBAFrontOfficeLab"
AI_AGENTS = (
    "ChatGPT-User",
    "Claude-User",
    "Perplexity-User",
    "GPTBot",
    "ClaudeBot",
    "PerplexityBot",
)
"""A site's robots rules are read for these as well: one that turns AI agents away turns
the lab away too."""
REFUSED_SITES: Mapping[str, str] = {
    "basketball-reference.com": "Sports Reference's terms bar using its data to prompt AI models",
    "sports-reference.com": "Sports Reference's terms bar using its data to prompt AI models",
    "baseball-reference.com": "Sports Reference's terms bar using its data to prompt AI models",
    "pro-football-reference.com": "Sports Reference's terms bar using its data to prompt AI models",
    "hockey-reference.com": "Sports Reference's terms bar using its data to prompt AI models",
    "fbref.com": "Sports Reference's terms bar using its data to prompt AI models",
    "stathead.com": "Sports Reference's terms bar using its data to prompt AI models",
    "spotrac.com": "Spotrac refuses automated requests",
    "nba.com": "the league's data comes through the lab's own sources; www.nba.com's robots.txt shuts AI agents out",
}
"""Sites never read, each with the reason (docs/DATA_SOURCE_REGISTER.md)."""
PAGE_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
PAGE_ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.9"
FEED_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "text/html",
)
"""A feed's types - and a web page's, since some sites label their feeds so (Hoops Rumors'
general feeds, at A7); what is not a feed fails to read as one."""
FEED_ACCEPT = "application/rss+xml,application/atom+xml,application/xml;q=0.9,text/xml;q=0.9"
PORTS = {"http": 80, "https": 443}
REDIRECTS = {301, 302, 303, 307, 308}
GATED = {401, 402, 403, 407, 429, 451}
"""Answers that mean a login, a payment, a bot check or a block: never worked around."""
MAX_REDIRECTS = 5
PAGE_BYTES = 2_000_000
ROBOTS_BYTES = 500_000
SEARCH_BYTES = 1_000_000


class WebError(RuntimeError):
    """The web could not be reached, or answered with something unusable."""


class Refused(WebError):
    """The lab does not read this address; the message says why."""


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: Mapping[str, str]
    """Header names in lower case."""
    body: bytes
    peer: str | None = None
    """The address actually connected to, when the transport can tell."""
    truncated: bool = False


Send = Callable[[str, str, Mapping[str, str], bytes | None, float, int], Response]
"""``(method, url, headers, body, timeout, byte limit)``: one request, no redirects followed."""
Resolve = Callable[[str], Sequence[str]]


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result as Ollama returns it."""

    title: str
    url: str
    content: str


@dataclass(frozen=True, slots=True)
class Fetched:
    """A page as it came: where it was asked for, where it ended, what it held."""

    requested: str
    url: str
    content_type: str
    charset: str | None
    body: bytes
    truncated: bool
    retrieved_at: datetime
    """UTC, without a zone marker."""


def requests_send(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
    limit: int,
) -> Response:
    """One request through ``requests``: no redirects, no cookies kept, at most ``limit``
    bytes read and ``timeout`` seconds spent reading."""
    deadline = time.monotonic() + timeout
    try:
        with requests.request(
            method,
            url,
            headers=dict(headers),
            data=body,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        ) as response:
            peer = _peer(response)
            chunks, size, truncated = [], 0, False
            for chunk in response.iter_content(65_536):
                chunks.append(chunk)
                size += len(chunk)
                if size >= limit or time.monotonic() > deadline:
                    truncated = True
                    break
            return Response(
                response.status_code,
                {name.lower(): value for name, value in response.headers.items()},
                b"".join(chunks)[:limit],
                peer,
                truncated,
            )
    except requests.RequestException as error:
        # The exception's own text may carry the request; only its kind is kept.
        raise WebError(f"{_host(url)} could not be reached ({type(error).__name__})") from None


def _peer(response: requests.Response) -> str | None:
    try:
        # urllib3 keeps the open connection on a streamed response.
        return str(response.raw._connection.sock.getpeername()[0])
    except (AttributeError, OSError, IndexError, TypeError):
        return None


def resolve_host(host: str) -> list[str]:
    try:
        found = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as error:
        raise WebError(f"{host} could not be found") from error
    return sorted({str(info[4][0]) for info in found})


def is_public(address: str) -> bool:
    """Whether an IP address is on the public internet: not loopback, private, link-local,
    shared, reserved or multicast."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def refused_site(host: str) -> str | None:
    """Why the lab does not read ``host``, or ``None`` when it may."""
    host = host.rstrip(".").lower()
    for domain, why in REFUSED_SITES.items():
        if host == domain or host.endswith("." + domain):
            return why
    return None


def search_key(env_file: Path | None) -> str | None:
    """The user's Ollama key: the environment variable, else its line in ``env_file``."""
    value = os.environ.get(KEY_VARIABLE, "").strip()
    if value:
        return value
    if env_file is None or not env_file.is_file():
        return None
    return setting_in(env_file.read_bytes(), KEY_VARIABLE)


class WebProvider:
    """The web as the assistant may reach it: one search API, and pages that pass the checks."""

    def __init__(
        self,
        *,
        env_file: Path | None = None,
        send: Send = requests_send,
        resolve: Resolve = resolve_host,
        timeout: float = 20.0,
        page_bytes: int = PAGE_BYTES,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._key = search_key(env_file)
        self._send = send
        self._resolve = resolve
        self._timeout = timeout
        self._page_bytes = page_bytes
        self._now = now
        self._robots: dict[str, RobotFileParser] = {}

    def __repr__(self) -> str:  # never the key
        return f"WebProvider(can_search={self.can_search})"

    @property
    def can_search(self) -> bool:
        return bool(self._key)

    def now(self) -> datetime:
        return self._now().astimezone(UTC).replace(tzinfo=None, microsecond=0)

    # --- search ------------------------------------------------------------------------------

    def search(self, query: str, max_results: int = 5) -> list[Hit]:
        if not self._key:
            raise WebError(
                f"web search is not set up: {KEY_VARIABLE} is in neither the environment nor "
                "the project's .env file"
            )
        body = json.dumps({"query": query, "max_results": max_results}).encode()
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        response = self._send("POST", SEARCH_URL, headers, body, self._timeout, SEARCH_BYTES)
        if response.status in (401, 403):
            raise WebError(f"Ollama's web search refused the key ({response.status})")
        if response.status == 429:
            raise WebError("Ollama's web search allowance is used up for now (429)")
        if response.status != 200:
            raise WebError(f"Ollama's web search answered {response.status}")
        try:
            payload = json.loads(response.body)
        except ValueError:
            raise WebError("Ollama's web search answered with something that is not JSON") from None
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise WebError("Ollama's web search answered without a list of results")
        return [
            Hit(str(item.get("title") or "").strip(), item["url"], str(item.get("content") or ""))
            for item in results
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        ]

    # --- pages -------------------------------------------------------------------------------

    def check(self, url: str) -> str:
        """The host of ``url`` when the lab may fetch it; otherwise :class:`Refused`."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise Refused("not a valid web address") from None
        if parts.scheme not in PORTS:
            raise Refused("only http and https addresses are read")
        if parts.username or parts.password:
            raise Refused("an address with credentials in it is not read")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise Refused("the address names no host")
        if port is not None and port != PORTS[parts.scheme]:
            raise Refused("only the standard web ports are read")
        why = refused_site(host)
        if why:
            raise Refused(f"{host} is not read: {why}")
        try:
            addresses: Sequence[str] = [str(ipaddress.ip_address(host))]
        except ValueError:
            addresses = self._resolve(host)
        if not addresses or not all(is_public(address) for address in addresses):
            raise Refused(f"{host} is not a public address")
        return host

    def fetch(self, url: str) -> Fetched:
        """A page, after the checks; redirects are followed, each checked again."""
        return self._fetch(url, PAGE_TYPES, PAGE_ACCEPT, "a web page")

    def fetch_feed(self, url: str) -> Fetched:
        """A news feed, after the same checks as a page (A7). Some sites send their feeds
        labelled as web pages; ``processing.feeds`` decides whether it is a feed."""
        return self._fetch(url, FEED_TYPES, FEED_ACCEPT, "a feed")

    def _fetch(self, url: str, types: Sequence[str], accept: str, wanted: str) -> Fetched:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host = self.check(current)
            self._allowed_by_robots(current, host)
            response = self._get(current, self._page_bytes, accept=accept)
            if response.status in REDIRECTS:
                location = response.headers.get("location")
                if not location:
                    raise WebError(f"{host} redirected without saying where")
                current = urljoin(current, location)
                continue
            if response.status in GATED:
                raise Refused(
                    f"{host} answered {response.status}: a login, a payment or a bot check "
                    "is not worked around"
                )
            if response.status != 200:
                raise WebError(f"{host} answered {response.status}")
            kind, charset = _content_type(response.headers.get("content-type", ""))
            if kind not in types:
                raise Refused(f"{host} sent {kind or 'something untyped'}, not {wanted}")
            return Fetched(
                url, current, kind, charset, response.body, response.truncated, self.now()
            )
        raise WebError(f"more than {MAX_REDIRECTS} redirects from {_host(url)}")

    def _get(self, url: str, limit: int, *, accept: str | None = None) -> Response:
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        response = self._send("GET", url, headers, None, self._timeout, limit)
        if response.peer is not None and not is_public(response.peer):
            raise Refused(f"{_host(url)} led to an address that is not public")
        return response

    def _allowed_by_robots(self, url: str, host: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        rules = self._robots.get(origin)
        if rules is None:
            rules = self._robots[origin] = self._read_robots(origin)
        for agent in (AGENT, *AI_AGENTS):
            if not rules.can_fetch(agent, url):
                who = "the lab" if agent == AGENT else f"AI agents ({agent})"
                raise Refused(f"{host}'s robots.txt asks {who} not to read this page")

    def _read_robots(self, origin: str) -> RobotFileParser:
        """The site's rules. Rules that cannot be read allow nothing; no file allows all."""
        rules = RobotFileParser()
        current = origin + "/robots.txt"
        try:
            for _ in range(MAX_REDIRECTS + 1):
                self.check(current)
                response = self._get(current, ROBOTS_BYTES)
                if response.status in REDIRECTS and response.headers.get("location"):
                    current = urljoin(current, response.headers["location"])
                    continue
                break
            else:
                rules.disallow_all = True
                return rules
        except WebError:
            rules.disallow_all = True
            return rules
        if response.status in (401, 403) or response.status >= 500:
            rules.disallow_all = True
        elif response.status >= 400:
            rules.allow_all = True
        else:
            rules.parse(response.body.decode("utf-8", "replace").splitlines())
        return rules


def _content_type(header: str) -> tuple[str, str | None]:
    kind, _, rest = header.partition(";")
    charset = None
    for part in rest.split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "charset" and value:
            charset = value.strip("\"' ").lower()
    return kind.strip().lower(), charset


def _host(url: str) -> str:
    try:
        return urlsplit(url).hostname or "the address"
    except ValueError:
        return "the address"
