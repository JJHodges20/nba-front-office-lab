"""Benchmark the AI research assistant's candidate models on this machine (milestone A1).

Plays every frozen case (tests/assistant/fixtures/cases.yaml) against each model through
the assistant's own routing, and scores the model's first move: the right tool with the
right arguments, or rightly none. Each case runs as the workbench would run it, with its
mode's settings from configs/assistant.yaml (Quick: no thinking, a short answer; Deep:
thinking, a longer one). Each model starts cold. Ollama's own counts give the tokens and
timings; /api/ps and nvidia-smi give where the model sits in memory.

    python scripts/benchmark_ollama.py                      run every model, every case
    python scripts/benchmark_ollama.py --models qwen3:8b --cases H01,A01
    python scripts/benchmark_ollama.py --write              ...and write the report
    python scripts/benchmark_ollama.py --report RUN.json --write   the report from a saved run
    python scripts/benchmark_ollama.py --report RUN.json --rescore --write
                                         ...its moves judged again against the cases as they stand

Results go to data/assistant/benchmarks/ (not committed); --write renders
docs/research/ASSISTANT_MODELS.md from them. Nothing here changes the lab's data, models
or settings.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from front_office.assistant.evaluation import (
    CaseFile,
    context_for,
    judge_choice,
    load_cases,
    messages_for,
    passes,
    score,
)
from front_office.assistant.policy import POLICY_VERSION
from front_office.assistant.routing import first_move
from front_office.assistant.tools import REGISTRY, tool_schemas
from front_office.config import load_assistant_settings, load_settings
from front_office.domain.assistant import AssistantSettings
from front_office.providers.ollama import OllamaError, OllamaProvider

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "assistant" / "fixtures" / "cases.yaml"
RESULTS = ROOT / "data" / "assistant" / "benchmarks"
REPORT = ROOT / "docs" / "research" / "ASSISTANT_MODELS.md"
MODELS = ("qwen3:8b", "qwen3:4b", "qwen3:4b-instruct", "qwen2.5:7b")
SHORT_CONTEXT = 4096
SHORT_CASES = ("H01", "H02", "H04", "E01", "A01", "N01", "P02", "K01", "C03", "T01", "X01", "V01")
MIB = 1024 * 1024


def gpu() -> dict[str, Any] | None:
    """The GPU's name and memory in MiB, from nvidia-smi; ``None`` without one."""
    try:
        line = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None
    name, total, used, driver = (part.strip() for part in line.split(","))
    return {"name": name, "total_mib": int(total), "used_mib": int(used), "driver": driver}


def run_model(
    provider: OllamaProvider,
    model: str,
    cases: CaseFile,
    settings: AssistantSettings,
    *,
    context_tokens: int,
    only: set[str] | None,
) -> dict[str, Any]:
    details = provider.details(model)
    for loaded in provider.loaded():
        provider.unload(loaded.name)
    time.sleep(3)
    before = gpu()
    records: list[dict[str, Any]] = []
    memory: dict[str, Any] = {}
    chosen = [case for case in cases.cases if only is None or case.id in only]
    for number, case in enumerate(chosen):
        mode = settings.mode(case.mode).model_copy(update={"context_tokens": context_tokens})
        think = mode.think if details.can_think else None
        started = time.monotonic()
        try:
            move = first_move(
                provider,
                model,
                context_for(cases, case),
                messages_for(case),
                settings=mode,
                think=think,
                temperature=settings.temperature,
                keep_alive=settings.ollama.keep_alive,
            )
        except OllamaError as error:
            records.append({"case": case.id, "category": case.category, "error": str(error)})
            print(f"  {case.id}: error {error}", flush=True)
            continue
        result = score(case, move)
        first = move.replies[0]
        records.append(
            {
                "case": case.id,
                "category": case.category,
                "mode": case.mode.value,
                "think": think,
                "cold": number == 0,
                "none_is_right": result.none_is_right,
                "none_only": not case.expect.calls,
                "chosen": result.chosen,
                "arguments": dict(move.first.arguments or {}) if move.first else None,
                "choice_ok": result.choice_ok,
                "args_ok": result.args_ok,
                "valid": result.valid,
                "valid_first_try": result.valid_first_try,
                "repaired": result.repaired,
                "forbidden": list(result.forbidden),
                "cut_off": result.cut_off,
                "passed": result.passed,
                "seconds": round(time.monotonic() - started, 3),
                "first_token_seconds": first.first_token_seconds,
                "load_seconds": first.load_seconds,
                "prompt_tokens": first.prompt_tokens,
                "output_tokens": sum(reply.output_tokens or 0 for reply in move.replies),
                "tokens_per_second": first.tokens_per_second,
                "thinking_characters": sum(len(reply.thinking) for reply in move.replies),
                "text": move.text[:400],
            }
        )
        mark = "pass" if result.passed else "FAIL"
        print(
            f"  {case.id:4} {mark} {result.chosen or 'none':22} {records[-1]['seconds']:6.1f}s",
            flush=True,
        )
        if number == 0:
            running = [m for m in provider.loaded() if m.name == model]
            memory = {
                "gpu_before": before,
                "gpu_loaded": gpu(),
                "ollama": [
                    {
                        "size": m.size,
                        "size_vram": m.size_vram,
                        "in_system_memory": m.in_system_memory,
                        "context_length": m.context_length,
                    }
                    for m in running
                ],
            }
    return {
        "model": model,
        "context_tokens": context_tokens,
        "capabilities": list(details.capabilities),
        "trained_context": details.context_length,
        "license": details.license,
        "memory": memory,
        "records": records,
    }


def benchmark(arguments: argparse.Namespace) -> dict[str, Any]:
    settings = load_assistant_settings(load_settings(ROOT).config_dir)
    cases = load_cases(CASES)
    provider = OllamaProvider(settings.ollama.host, timeout=settings.ollama.timeout_seconds)
    only = set(arguments.cases.split(",")) if arguments.cases else None
    models = arguments.models.split(",") if arguments.models else list(MODELS)
    run: dict[str, Any] = {
        "started": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "machine": {
            "system": platform.platform(),
            "processor": platform.processor(),
            "gpu": gpu(),
            "ollama": provider.version(),
        },
        "policy": POLICY_VERSION,
        "cases_version": cases.version,
        "tools": len(REGISTRY),
        "tool_schema_characters": len(json.dumps(tool_schemas())),
        "settings": settings.model_dump(mode="json"),
        "runs": [],
    }
    for model in models:
        provider.require_local(model)
        print(f"{model}, context {arguments.context}", flush=True)
        run["runs"].append(
            {
                **run_model(
                    provider, model, cases, settings, context_tokens=arguments.context, only=only
                ),
                "pass": "full",
            }
        )
        if arguments.short and only is None:
            print(f"{model}, context {SHORT_CONTEXT}", flush=True)
            run["runs"].append(
                {
                    **run_model(
                        provider,
                        model,
                        cases,
                        settings,
                        context_tokens=SHORT_CONTEXT,
                        only=set(SHORT_CASES),
                    ),
                    "pass": "short",
                }
            )
    run["finished"] = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return run


# --- the report --------------------------------------------------------------------------


def share(flags: list[bool]) -> str:
    return "-" if not flags else f"{sum(flags)}/{len(flags)} ({100 * sum(flags) / len(flags):.0f}%)"


def quantile(values: list[float], q: float, decimals: int = 1) -> str:
    values = sorted(v for v in values if v is not None)
    if not values:
        return "-"
    if len(values) == 1:
        return f"{values[0]:,.{decimals}f}"
    cut = statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]
    return f"{cut:,.{decimals}f}"


def summary(entry: dict[str, Any]) -> dict[str, str]:
    records = [r for r in entry["records"] if "error" not in r]
    calls = [r for r in records if not r["none_is_right"] or r["chosen"] is not None]
    expected_call = [r for r in records if not r["none_is_right"]]
    expected_none = [r for r in records if r["none_only"]]
    chosen_right = [r for r in records if r["choice_ok"] and r["chosen"] is not None]
    warm = [r for r in records if not r["cold"]]
    cold = next((r for r in records if r["cold"]), None)
    memory = entry.get("memory") or {}
    ollama = (memory.get("ollama") or [{}])[0]
    loaded, before = memory.get("gpu_loaded") or {}, memory.get("gpu_before") or {}
    return {
        "passed": share([r["passed"] for r in records]),
        "right_first_move": share([r["choice_ok"] for r in records]),
        "right_tool": share([r["choice_ok"] for r in expected_call]),
        "rightly_none": share([r["choice_ok"] for r in expected_none]),
        "right_arguments": share([bool(r["args_ok"]) and bool(r["valid"]) for r in chosen_right]),
        "valid_first_try": share([bool(r["valid_first_try"]) for r in calls if r["chosen"]]),
        "repaired": str(sum(r["repaired"] for r in records)),
        "forbidden": str(sum(bool(r["forbidden"]) for r in records)),
        "cut_off": str(sum(r["cut_off"] for r in records)),
        "errors": str(len(entry["records"]) - len(records)),
        "quick_median": quantile([r["seconds"] for r in warm if r["mode"] == "quick"], 0.5),
        "quick_p90": quantile([r["seconds"] for r in warm if r["mode"] == "quick"], 0.9),
        "deep_median": quantile([r["seconds"] for r in warm if r["mode"] == "deep"], 0.5),
        "deep_p90": quantile([r["seconds"] for r in warm if r["mode"] == "deep"], 0.9),
        "first_token": quantile([r["first_token_seconds"] for r in warm], 0.5),
        "tokens_per_second": quantile([r["tokens_per_second"] for r in warm], 0.5, 0),
        "prompt_tokens": quantile([r["prompt_tokens"] for r in records], 0.5, 0),
        "output_tokens": quantile([r["output_tokens"] for r in warm], 0.5, 0),
        "cold_seconds": "-" if cold is None else f"{cold['seconds']:.1f}",
        "load_seconds": "-"
        if not cold or cold["load_seconds"] is None
        else f"{cold['load_seconds']:.1f}",
        "gpu_gb": "-" if "size_vram" not in ollama else f"{ollama['size_vram'] / 1024**3:.2f}",
        "ram_gb": "-"
        if "in_system_memory" not in ollama
        else f"{ollama['in_system_memory'] / 1024**3:.2f}",
        "gpu_used": "-"
        if not loaded
        else f"{loaded['used_mib'] / 1024:.1f} of {loaded['total_mib'] / 1024:.1f} GB (was {before.get('used_mib', 0) / 1024:.1f})",
    }


def rescore(run: dict[str, Any], cases: CaseFile) -> dict[str, Any]:
    """The run's recorded moves judged again against the case file as it stands now.

    The model is not asked again: each record keeps its tool, arguments, validity, cut-off
    and forbidden findings, and only the choice is judged anew. Every verdict that changes
    is listed in the run, so that the report says so.
    """
    by_id = {case.id: case for case in cases.cases}
    changed = []
    for entry in run["runs"]:
        for record in entry["records"]:
            case = by_id.get(record["case"])
            if case is None or "error" in record:
                continue
            choice_ok, args_ok = judge_choice(case, record["chosen"], record["arguments"])
            verdict = passes(
                choice_ok, args_ok, record["valid"], record["forbidden"], record["cut_off"]
            )
            if verdict != record["passed"]:
                changed.append(
                    {
                        "model": entry["model"],
                        "context_tokens": entry["context_tokens"],
                        "case": record["case"],
                        "was": record["passed"],
                        "now": verdict,
                    }
                )
            record.update(
                choice_ok=choice_ok,
                args_ok=args_ok,
                passed=verdict,
                none_is_right=case.expect.none_is_right,
                none_only=not case.expect.calls,
            )
    run["rescored"] = {
        "at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "changed": changed,
    }
    return run


def report(run: dict[str, Any]) -> str:
    machine = run["machine"]
    card = machine.get("gpu") or {}
    full = [entry for entry in run["runs"] if entry.get("pass") != "short"]
    short = [entry for entry in run["runs"] if entry.get("pass") == "short"]
    lines = [
        "# The Assistant's Language Model",
        "",
        "Which local model the AI research assistant runs on, and the evidence for it. Generated by "
        f"`scripts/benchmark_ollama.py --write` from the run of {run['started']} UTC on this machine; "
        "do not edit it by hand - run the benchmark again.",
        "",
        "> Measured on one computer, on the assistant's first move only: given a question and its "
        "context, does the model call the right tool with the right arguments - or rightly call "
        "nothing? Nothing behind the tools runs yet (milestone A2), so answers are not scored "
        "here. The cases are frozen; a model is never helped by changing one.",
        "",
        *_rescored(run),
        "## The machine and the run",
        "",
        f"- {card.get('name', 'no NVIDIA GPU found')}"
        + (
            f", {card['total_mib'] / 1024:.1f} GB of video memory, driver {card['driver']}"
            if card
            else ""
        )
        + f"; {machine['system']}.",
        f"- Ollama {machine['ollama']}; rules {run['policy']}; {run['tools']} tools, "
        f"{run['tool_schema_characters']:,} characters of tool definitions in every request.",
        f"- {len(full[0]['records']) if full else 0} cases, each in its own mode: Quick with thinking "
        f"off and up to {run['settings']['quick']['max_output_tokens']} output tokens, Deep with "
        f"thinking on and up to {run['settings']['deep']['max_output_tokens']}; temperature "
        f"{run['settings']['temperature']}; every model loaded cold for its first case.",
        "",
        f"## First moves, at a context of {full[0]['context_tokens'] if full else '-'} tokens",
        "",
        "| Model | Passed | Right first move | Right tool, when one is needed | Rightly no tool | Right arguments, when the tool is right | Valid first time | Repaired | Forbidden | Cut off |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    summaries = {entry["model"]: summary(entry) for entry in full}
    for model, s in summaries.items():
        lines.append(
            f"| {model} | {s['passed']} | {s['right_first_move']} | {s['right_tool']} | {s['rightly_none']} | "
            f"{s['right_arguments']} | {s['valid_first_try']} | {s['repaired']} | {s['forbidden']} | {s['cut_off']} |"
        )
    lines += [
        "",
        "*Passed* needs all of it: the right tool or rightly none, the expected argument values, "
        "arguments that validate (after at most one repair), nothing forbidden, nothing cut off. "
        "*Rightly no tool* counts the cases where calling nothing is the only right move: "
        "clarifying, declining, and answering from a tool's result already in hand.",
        "",
        "## Time and memory",
        "",
        "| Model | Quick, median (90th) | Deep, median (90th) | First token | Output tokens/s | Prompt tokens | Output tokens | Cold first case (load) | On the GPU | In system memory | GPU memory in use |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for model, s in summaries.items():
        lines.append(
            f"| {model} | {s['quick_median']} s ({s['quick_p90']}) | {s['deep_median']} s ({s['deep_p90']}) | "
            f"{s['first_token']} s | {s['tokens_per_second']} | {s['prompt_tokens']} | {s['output_tokens']} | "
            f"{s['cold_seconds']} s ({s['load_seconds']} s) | {s['gpu_gb']} GB | {s['ram_gb']} GB | {s['gpu_used']} |"
        )
    lines += [
        "",
        "Times are wall-clock seconds for the whole first move, a repair included, on warm cases. "
        "Model sizes are Ollama's, with the context allocated; GPU memory in use is the whole card's "
        "after the model loaded, against what was in use before (the desktop's share).",
        "",
        "## By category",
        "",
        "| Category | Cases | " + " | ".join(summaries) + " |",
        "| --- | ---: | " + " | ".join("---" for _ in summaries) + " |",
    ]
    categories: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for entry in full:
        for record in entry["records"]:
            if "error" not in record:
                categories[record["category"]][entry["model"]].append(record["passed"])
    for category, by_model in categories.items():
        size = len(next(iter(by_model.values())))
        cells = [f"{sum(by_model.get(m, []))}/{len(by_model.get(m, []))}" for m in summaries]
        lines.append(f"| {category} | {size} | " + " | ".join(cells) + " |")
    if short:
        lines += [
            "",
            f"## At a context of {SHORT_CONTEXT} tokens",
            "",
            f"The same models on {len(SHORT_CASES)} cases with half the context. Every request carries "
            "the rules and all the tool definitions before the question.",
            "",
            "| Model | Passed | Cut off | Prompt tokens | Quick, median | On the GPU | In system memory |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: |",
        ]
        for entry in short:
            s = summary(entry)
            lines.append(
                f"| {entry['model']} | {s['passed']} | {s['cut_off']} | {s['prompt_tokens']} | "
                f"{s['quick_median']} s | {s['gpu_gb']} GB | {s['ram_gb']} GB |"
            )
    lines += ["", "## What each model got wrong", ""]
    for entry in full:
        misses = [r for r in entry["records"] if "error" in r or not r["passed"]]
        lines.append(f"**{entry['model']}** - {len(misses)} of {len(entry['records'])}")
        lines.append("")
        for r in misses:
            if "error" in r:
                lines.append(f"- {r['case']}: error - {r['error']}")
                continue
            why = []
            if not r["choice_ok"]:
                why.append(f"called {r['chosen'] or 'nothing'}")
            elif r["args_ok"] is False:
                why.append(f"{r['chosen']} with {json.dumps(r['arguments'])}")
            if r["valid"] is False:
                why.append("arguments invalid after repair")
            if r["forbidden"]:
                why.append("forbidden: " + ", ".join(r["forbidden"]))
            if r["cut_off"]:
                why.append("cut off at the output limit")
            lines.append(f"- {r['case']} ({r['category']}): " + "; ".join(why))
        lines.append("")
    lines += [
        "## Licences",
        "",
        "| Model | Licence, as Ollama reports it | Capabilities | Trained context |",
        "| --- | --- | --- | ---: |",
    ]
    for entry in full:
        lines.append(
            f"| {entry['model']} | {entry['license'] or '-'} | {', '.join(entry['capabilities'])} | "
            f"{format(entry['trained_context'], ',') if entry['trained_context'] else '-'} |"
        )
    lines += [
        "",
        "The assistant's settings (`configs/assistant.yaml`) name "
        f"`{run['settings']['default_model']}` as the default and "
        f"`{run['settings']['fallback_model']}` as the fallback; the reasons are in "
        "`docs/DEVELOPMENT_LOG.md` (milestone A1).",
        "",
    ]
    return "\n".join(lines)


def _rescored(run: dict[str, Any]) -> list[str]:
    """A note that the run was judged again, and what that changed."""
    note = run.get("rescored")
    if not note:
        return []
    changes = "; ".join(
        f"{c['model']} {c['case']} at {c['context_tokens']:,} tokens "
        f"({'failed' if not c['was'] else 'passed'} -> {'passed' if c['now'] else 'failed'})"
        for c in note["changed"]
    )
    return [
        f"**Re-scored on {note['at']} UTC** against the case file as it then stood: the moves "
        "are this run's own and the models were not asked again. A case changes only as the "
        "header of `tests/assistant/fixtures/cases.yaml` allows, and the development log says "
        f"which, why and when. Verdicts that changed: {changes or 'none'}.",
        "",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", help="comma-separated; default: the four candidates")
    parser.add_argument("--cases", help="comma-separated case ids; default: every case")
    parser.add_argument("--context", type=int, default=8192, help="context tokens for the full run")
    parser.add_argument(
        "--no-short",
        dest="short",
        action="store_false",
        help=f"skip the {SHORT_CONTEXT}-token pass",
    )
    parser.add_argument("--report", type=Path, help="render from a saved run instead of running")
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="with --report: judge the saved moves again against the cases as they stand",
    )
    parser.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(ROOT)}")
    arguments = parser.parse_args()

    if arguments.rescore and not arguments.report:
        parser.error("--rescore judges a saved run again: give it with --report")
    if arguments.report:
        run = json.loads(arguments.report.read_text(encoding="utf-8"))
        if arguments.rescore:
            run = rescore(run, load_cases(CASES))
            saved = RESULTS / f"{arguments.report.stem}.rescored.json"
            saved.write_text(json.dumps(run, indent=1), encoding="utf-8", newline="\n")
            print(f"saved {saved}")
    else:
        run = benchmark(arguments)
        RESULTS.mkdir(parents=True, exist_ok=True)
        saved = RESULTS / f"{run['started'].replace(':', '')}.json"
        saved.write_text(json.dumps(run, indent=1), encoding="utf-8", newline="\n")
        print(f"saved {saved}")
    text = report(run)
    if arguments.write:
        REPORT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {REPORT}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
