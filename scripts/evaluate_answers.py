"""Evaluate the AI research assistant's whole answers on this machine (from milestone A2).

Runs every frozen case whose tools are built (tests/assistant/fixtures/cases.yaml) through
the assistant end to end - the name pre-pass, the local model calling the lab's tools, the
answer checker - on the two test databases, built here from the fixture store exactly as
the tests build them. Current information and the web come from the recorded world of
tests/assistant/recorded.py: invented payloads, consistent with the case file's day. Nothing
is fetched, and no search account is used. Each answer is scored by
``assistant.evaluation.score_answer``.

    python scripts/evaluate_answers.py                       every runnable case, the default model
    python scripts/evaluate_answers.py --cases H01,C01       some of them
    python scripts/evaluate_answers.py --write               ...and write the report
    python scripts/evaluate_answers.py --report RUN.json --write   the report from a saved run
    python scripts/evaluate_answers.py --report RUN.json --rescore --write
                                          ...its figures counted again by the scoring as it stands

Results go to data/assistant/benchmarks/ (not committed); --write renders
docs/research/ASSISTANT_ANSWERS.md from them. Nothing here changes the lab's data, models or
settings: the test databases live in a temporary folder that is removed afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # the recorded world and the test databases' recipe live in tests/

from tests.assistant.recorded import world_toolbox  # noqa: E402
from tests.conftest import (  # noqa: E402
    BUILD_TOOK,
    BUILT_AT,
    FIXTURE_RAW,
    PRICED_CONTRACT_FILE,
    with_contracts,
)
from tests.helpers import CONTRACT_FILE  # noqa: E402

from front_office.assistant.evaluation import (  # noqa: E402
    built_tools,
    context_for,
    facts_stated,
    load_cases,
    question_of,
    runnable,
    score_answer,
)
from front_office.assistant.orchestrator import Assistant  # noqa: E402
from front_office.assistant.policy import POLICY_VERSION  # noqa: E402
from front_office.config import load_assistant_settings, load_settings  # noqa: E402
from front_office.pipelines.build import build_database  # noqa: E402
from front_office.providers.ollama import OllamaError, OllamaProvider  # noqa: E402
from front_office.providers.web import KEY_VARIABLE  # noqa: E402
from front_office.services import Lab  # noqa: E402

CASES = ROOT / "tests" / "assistant" / "fixtures" / "cases.yaml"
RESULTS = ROOT / "data" / "assistant" / "benchmarks"
REPORT = ROOT / "docs" / "research" / "ASSISTANT_ANSWERS.md"
MILESTONE = "A9"


def build_labs(where: Path) -> dict[str, Path]:
    """The case file's three databases: the fixture build, and the same with each of the
    tests' invented contract files - the recipe of tests/conftest.py - each with the lab's
    own documents beside it, for research_docs."""
    fixture = where / "fixture"
    shutil.copytree(ROOT / "configs", fixture / "configs")
    shutil.copytree(ROOT / "docs", fixture / "docs")
    shutil.copytree(FIXTURE_RAW, fixture / "data" / "raw")
    moments = iter([BUILT_AT, BUILT_AT + BUILD_TOOK])
    if not build_database(load_settings(fixture), now=lambda: next(moments)).loaded:
        raise SystemExit("the fixture database could not be built")
    with_contracts(fixture, where / "contracts", CONTRACT_FILE)
    with_contracts(fixture, where / "priced", PRICED_CONTRACT_FILE.read_text(encoding="utf-8"))
    return {"fixture": fixture, "contracts": where / "contracts", "priced": where / "priced"}


def evaluate(arguments: argparse.Namespace) -> dict[str, Any]:
    # The recorded world opens nothing with a key, and the user's own is never read here.
    os.environ.pop(KEY_VARIABLE, None)
    settings = load_assistant_settings(load_settings(ROOT).config_dir)
    model = arguments.model or settings.default_model
    cases = load_cases(CASES)
    built = built_tools(MILESTONE)
    only = set(arguments.cases.split(",")) if arguments.cases else None
    chosen = [
        case for case in cases.cases if runnable(case, built) and (only is None or case.id in only)
    ]
    provider = OllamaProvider(settings.ollama.host, timeout=settings.ollama.timeout_seconds)
    provider.require_local(model)
    run: dict[str, Any] = {
        "started": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "machine": {"system": platform.platform(), "ollama": provider.version()},
        "model": model,
        "milestone": MILESTONE,
        "policy": POLICY_VERSION,
        "cases_version": cases.version,
        "settings": settings.model_dump(mode="json"),
        "records": [],
    }
    with tempfile.TemporaryDirectory(prefix="fol-answers-") as scratch:
        where = Path(scratch)
        print("building the test databases", flush=True)
        homes = build_labs(where)
        labs = {name: Lab(load_settings(home)) for name, home in homes.items()}
        try:
            for case in chosen:
                lab = labs[case.database]
                history, question, _ = question_of(case)
                assistant = Assistant(
                    lab,
                    settings,
                    provider,
                    model=model,
                    toolbox=world_toolbox(lab, case, where),
                )
                started = time.monotonic()
                try:
                    answer = assistant.ask(question, context_for(cases, case), history=history)
                except OllamaError as error:
                    run["records"].append({"case": case.id, "category": case.category, "error": str(error)})  # fmt: skip
                    print(f"  {case.id}: error {error}", flush=True)
                    continue
                scored = score_answer(case, answer)
                run["records"].append(
                    {
                        "case": case.id,
                        "category": case.category,
                        "mode": case.mode.value,
                        "expected": scored.expected,
                        "outcome": scored.outcome,
                        "outcome_ok": scored.outcome_ok,
                        "calls": [
                            {"tool": r.tool, "arguments": r.arguments, "status": r.status.value}
                            for r in answer.results
                        ],
                        "replayed": scored.replayed,
                        "first_ok": scored.first_ok,
                        "args_ok": scored.args_ok,
                        "forbidden": list(scored.forbidden),
                        "missing_cites": list(scored.missing_cites),
                        "facts_stated": scored.facts_stated,
                        "facts": scored.facts,
                        "removed": list(answer.removed),
                        "repaired": any(step.kind == "repair" for step in answer.steps),
                        "model_calls": sum(step.kind == "model" for step in answer.steps),
                        "passed": scored.passed,
                        "seconds": round(time.monotonic() - started, 2),
                        "warnings": list(answer.warnings),
                        "evidence": [item.label for item in answer.evidence],
                        "text": answer.text,
                    }
                )
                record = run["records"][-1]
                mark = "pass" if scored.passed else "FAIL"
                print(
                    f"  {case.id:4} {mark} {scored.outcome:12} {','.join(scored.calls) or '-':40} "
                    f"{record['seconds']:6.1f}s",
                    flush=True,
                )
        finally:
            for lab in labs.values():
                lab.close()
    run["finished"] = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return run


def rescore(run: dict[str, Any]) -> dict[str, Any]:
    """The saved answers' frozen figures counted again, by the scoring as it stands. What
    was called and said is the run's own; nothing is asked again."""
    cases = {case.id: case for case in load_cases(CASES).cases}
    records = [
        record
        if "error" in record
        else {
            **record,
            "facts_stated": facts_stated(cases[record["case"]], record["text"]),
        }  # fmt: skip
        for record in run["records"]
    ]
    return {**run, "records": records, "rescored": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")}  # fmt: skip


# --- the report --------------------------------------------------------------------------


def share(flags: list[bool]) -> str:
    return "-" if not flags else f"{sum(flags)}/{len(flags)} ({100 * sum(flags) / len(flags):.0f}%)"


def first_right(record: dict[str, Any]) -> bool:
    return record["first_ok"] and record["replayed"] and record["args_ok"] is not False


def report(run: dict[str, Any]) -> str:
    records = [r for r in run["records"] if "error" not in r]
    errors = [r for r in run["records"] if "error" in r]
    seconds = [r["seconds"] for r in records]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_category[record["category"]].append(record)
    lines = [
        "# The assistant's answers, end to end",
        "",
        "<!-- Generated by `scripts/evaluate_answers.py --write`. Do not edit by hand. -->",
        "",
        f"Every frozen case whose tools are built by milestone {run['milestone']}, asked of "
        f"`{run['model']}` through the whole assistant: the name pre-pass, the tools on the "
        "case's test database, the answer checker. Current information and the web came from "
        "the recorded world of `tests/assistant/recorded.py` - invented, and dated the case "
        "file's day - so nothing was fetched. See [AI_EVALUATION.md](../AI_EVALUATION.md).",
        "",
        f"- Run: {run['started']} to {run['finished']} UTC, rules {run['policy']}, "
        f"case file version {run['cases_version']}, Ollama {run['machine'].get('ollama') or '-'}.",
        f"- Cases: {len(run['records'])}; errors: {len(errors)}."
        + (f" Figures counted again on {run['rescored']}." if run.get("rescored") else ""),
        "",
        "## Summary",
        "",
        "| Measure | Result |",
        "| --- | --- |",
        f"| Passed (every part below) | {share([r['passed'] for r in records])} |",
        f"| The outcome the case expects | {share([r['outcome_ok'] for r in records])} |",
        f"| The right first call - tool and values - or rightly none | {share([first_right(r) for r in records])} |",
        f"| Nothing forbidden called, sent or said | {share([not r['forbidden'] for r in records])} |",
        f"| The evidence the case asks for | {share([not r['missing_cites'] for r in records])} |",
        f"| Frozen figures stated | {sum(r['facts_stated'] for r in records)} of {sum(r['facts'] for r in records)} |",
        f"| Answers the checker had to repair | {sum(r['repaired'] for r in records)} |",
        f"| Figures cut out as unsupported | {sum(len(r['removed']) for r in records)} |",
        f"| Seconds per answer, median (slowest) | {statistics.median(seconds):.1f} ({max(seconds):.1f}) |"
        if seconds
        else "| Seconds per answer | - |",
        "",
        "## By category",
        "",
        "| Category | Cases | Passed | Outcome | First call | Evidence |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for category, group in by_category.items():
        lines.append(
            f"| {category} | {len(group)} | {share([r['passed'] for r in group])} | "
            f"{share([r['outcome_ok'] for r in group])} | "
            f"{share([first_right(r) for r in group])} | "
            f"{share([not r['missing_cites'] for r in group])} |"
        )
    lines += [
        "",
        "## Case by case",
        "",
        "| Case | Mode | Expected | Outcome | Calls | Forbidden | Missing evidence | Figures | Seconds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for r in records:
        calls = ", ".join(f"{c['tool']} ({c['status']})" for c in r["calls"]) or "none"
        figures = f"{r['facts_stated']}/{r['facts']}" if r["facts"] else "-"
        lines.append(
            f"| {r['case']}{'' if r['passed'] else ' ✗'} | {r['mode']} | {r['expected']} | "
            f"{r['outcome']} | {calls} | {', '.join(r['forbidden']) or '-'} | "
            f"{', '.join(r['missing_cites']) or '-'} | {figures} | {r['seconds']:.1f} |"
        )
    if errors:
        lines += ["", "## Errors", ""]
        lines += [f"- {r['case']}: {r['error']}" for r in errors]
    lines += [
        "",
        "## The answers",
        "",
        "Each as the user would read it, before the tables and the evidence the page adds.",
        "",
    ]
    for r in records:
        quoted = "\n".join(f"> {line}" if line else ">" for line in r["text"].splitlines())
        lines += [f"**{r['case']}** ({r['outcome']})", "", quoted, ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", help="default: the assistant's default model")
    parser.add_argument("--cases", help="comma-separated case ids; default: every runnable case")
    parser.add_argument("--report", type=Path, help="render from a saved run instead of running")
    parser.add_argument(
        "--rescore", action="store_true", help="with --report: count the figures again"
    )
    parser.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(ROOT)}")
    arguments = parser.parse_args()
    if arguments.rescore and not arguments.report:
        parser.error("--rescore counts a saved run again: give it with --report")
    if arguments.report:
        run = json.loads(arguments.report.read_text(encoding="utf-8"))
        if arguments.rescore:
            run = rescore(run)
            saved = RESULTS / f"{arguments.report.stem}.rescored.json"
            saved.write_text(json.dumps(run, indent=1), encoding="utf-8", newline="\n")
            print(f"saved {saved}")
    else:
        run = evaluate(arguments)
        RESULTS.mkdir(parents=True, exist_ok=True)
        saved = RESULTS / f"answers-{run['started'].replace(':', '')}.json"
        saved.write_text(json.dumps(run, indent=1), encoding="utf-8", newline="\n")
        print(f"saved {saved}")
    text = report(run)
    if arguments.write:
        REPORT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {REPORT}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
