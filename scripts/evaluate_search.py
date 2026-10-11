"""Evaluate the assistant's search: frozen research queries through Ollama's web search, held
against the news feeds (decision 0018, A7).

    python scripts/evaluate_search.py                          run every query, save the run
    python scripts/evaluate_search.py --write                  ...and write the report
    python scripts/evaluate_search.py --report RUN.json --write   the report from a saved run

Uses the user's own search key (FOL_OLLAMA_API_KEY, from the environment or the project's
.env), one search per query, and reads each news feed once through the guarded provider.
The run goes to data/assistant/benchmarks/ (not committed); --write renders
docs/research/SEARCH_QUALITY.md from it. Nothing else is stored: the lab's data and its
current-information cache are not touched.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

from front_office.assistant.search_quality import (  # noqa: E402
    Result,
    load_search_cases,
    report,
    score_case,
    score_record,
)
from front_office.assistant.web_tools import address_date  # noqa: E402
from front_office.config import load_assistant_settings, load_settings  # noqa: E402
from front_office.domain.assistant import NewsFeed  # noqa: E402
from front_office.pipelines.web import article_address  # noqa: E402
from front_office.processing.feeds import FeedError, parse_feed  # noqa: E402
from front_office.providers.web import WebError, WebProvider, refused_site  # noqa: E402

CASES = ROOT / "tests" / "assistant" / "fixtures" / "search_cases.yaml"
RESULTS = ROOT / "data" / "assistant" / "benchmarks"
REPORT = ROOT / "docs" / "research" / "SEARCH_QUALITY.md"
MAX_RESULTS = 10
SNIPPET = 600


def evaluate() -> dict[str, Any]:
    cases = load_search_cases(CASES)
    news = load_assistant_settings(load_settings(ROOT).config_dir).news
    web = WebProvider(env_file=ROOT / ".env")
    if not web.can_search:
        raise SystemExit(
            "web search is not set up: put FOL_OLLAMA_API_KEY in the environment or the "
            "project's .env file"
        )
    now = web.now()
    held: dict[str, list[Result]] = {}

    def items(feeds: list[NewsFeed]) -> list[Result]:
        seen: dict[str, Result] = {}
        for feed in feeds:
            if feed.url not in held:
                try:
                    found = parse_feed(web.fetch_feed(feed.url).body)
                except (WebError, FeedError) as error:
                    print(f"  feed {feed.id} not read: {error}", flush=True)
                    found = []
                held[feed.url] = [
                    Result(item.title, item.link, item.summary or "", item.published_at)
                    for item in found
                ]
            for item in held[feed.url]:
                seen.setdefault(article_address(item.url), item)
        return list(seen.values())

    scores = []
    for case in cases.cases:
        try:
            hits = web.search(case.query, MAX_RESULTS)
        except WebError as error:
            scores.append(score_case(case, [], None, now=now, error=str(error)))
            print(f"{case.id} not run: {error}", flush=True)
            continue
        seen: set[str] = set()
        found = []
        for hit in hits:
            address = article_address(hit.url)
            found.append(
                Result(
                    hit.title,
                    hit.url,
                    hit.content[:SNIPPET],
                    _published(hit.url),
                    refused=refused_site(urlsplit(hit.url).hostname or "") is not None,
                    duplicate=address in seen,
                )
            )
            seen.add(address)
        if case.team is not None:
            team = news.team_feed(case.team)
            feed = items([team]) if team is not None else None
        elif case.kind == "news":
            feed = items(list(news.general))
        else:
            feed = None
        score = score_case(case, found, feed, now=now)
        scores.append(score)
        print(
            f"{case.id} {score.results:>2} results, {score.on_topic} on topic, {score.dated} "
            f"dated, fresh {score.fresh}, feeds {score.feed_items}",
            flush=True,
        )
    return {
        "ran_at": f"{now:%Y-%m-%d %H:%M}",
        "frozen_on": cases.frozen_on,
        "max_results": MAX_RESULTS,
        "scores": [score_record(score) for score in scores],
    }


def _published(url: str) -> datetime | None:
    """The day an address dates a result; a month alone counts from its first day."""
    moment, written = address_date(url)
    if moment is not None or written is None:
        return moment
    year, month = written.split("-")
    return datetime(int(year), int(month), 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--report", type=Path, help="render from a saved run instead of running")
    parser.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(ROOT)}")
    arguments = parser.parse_args()
    if arguments.report is not None:
        run = json.loads(arguments.report.read_text(encoding="utf-8"))
    else:
        run = evaluate()
        RESULTS.mkdir(parents=True, exist_ok=True)
        saved = RESULTS / f"search-{run['ran_at'].replace(' ', 'T').replace(':', '')}.json"
        saved.write_text(json.dumps(run, indent=2), encoding="utf-8", newline="\n")
        print(f"saved {saved}")
    if arguments.write:
        REPORT.write_text(report(run), encoding="utf-8", newline="\n")
        print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
