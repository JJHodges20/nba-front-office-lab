"""Measure a working session with the AI research assistant on this machine (milestone A9).

Asks a frozen working session - follow-ups, a season the lab does not hold, a verdict,
current information, the news and the web, a scenario, a roster proposal and a request to
save it, an experiment - one question after another in one workspace, exactly as the AI
Research page asks them (``assistant.api``): on the lab's real data, with current
information fetched as it falls due and the web searched when the user's key is set. The
model is first taken out of memory, so that its loading is timed on its own and the first
answer is a cold start. The whole session is then asked again in a second workspace, so that
every question is asked twice and the two answers can be set side by side.

Nothing of the user's changes: the lab's data folder is copied to a temporary folder for the
run (``FOL_DATA_DIR``), and the workspaces, the current information fetched and the pages
read live there and are removed afterwards. The report holds times, outcomes, tools, counts
and memory - never an answer's words, which may quote the injury report or a web page.

    python scripts/measure_session.py              the session, twice
    python scripts/measure_session.py --once       the session once
    python scripts/measure_session.py --write      ...and write the report
    python scripts/measure_session.py --report RUN.json --write   the report from a saved run

Results go to data/assistant/benchmarks/ (not committed); --write renders
docs/research/ASSISTANT_SESSION.md from them.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "assistant" / "benchmarks"
REPORT = ROOT / "docs" / "research" / "ASSISTANT_SESSION.md"
MILESTONE = "A9"
MIB = 1024 * 1024
QUICK, DEEP = "quick", "deep"
SESSION: tuple[tuple[str, str, str], ...] = (
    ("S01", QUICK, "How did the Knicks do last season?"),
    ("S02", QUICK, "How good was their defense?"),
    ("S03", QUICK, "Who were their most valuable players, by the lab's value model?"),
    ("S04", QUICK, "Compare Jalen Brunson and Karl-Anthony Towns last season."),
    ("S05", QUICK, "What was Brunson's true shooting in 2024-25?"),
    ("S06", QUICK, "Who led the league in net rating in 2012-13?"),
    ("S07", QUICK, "What was the Celtics' net rating in 1989-90?"),
    ("S08", QUICK, "How often have teams with a net rating like the Knicks' won the title?"),
    ("S09", QUICK, "What are the Knicks' playoff chances for the season ahead?"),
    ("S10", QUICK, "So are they a real contender?"),
    ("S11", DEEP, "What if Jalen Brunson missed 20 games next season?"),
    ("S12", QUICK, "What does net rating mean?"),
    ("S13", QUICK, "How does the lab decide a player's role?"),
    ("S14", QUICK, "Has anything changed for the Knicks since the contract file was made?"),
    ("S15", QUICK, "Is anyone on the Knicks on the injury report?"),
    ("S16", QUICK, "What are the latest Knicks rumors?"),
    ("S17", QUICK, "Search the web for reporting on the Knicks' preseason."),
    ("S18", DEEP, "Propose two rosters for next season under the salary cap."),
    ("S19", QUICK, "Save the first one as my roster."),
    ("S20", QUICK, "Suggest an experiment that might make the playoff model better."),
)
"""The session, frozen: a question's words never change once measured. Each depends on the
ones before it as a user's would - S02, S03 and S10 name nobody, S19 means S18's roster."""
WAIT_SECONDS = {QUICK: 240.0, DEEP: 600.0}
"""Longer than a mode's own budget (90 s, 300 s), so that a question cut short by it shows."""
FIGURE = re.compile(r"[-+−]?\$?\d[\d,]*(?:\.\d+)?%?")


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


def scratch_data(where: Path) -> Path:
    """A copy of the lab's data folder without the user's research or any benchmark: the
    session's workspaces and fetches go here."""
    source = ROOT / "data"
    target = where / "data"
    shutil.copytree(
        source,
        target,
        ignore=lambda folder, names: (
            [name for name in names if name == "assistant"] if Path(folder) == source else []
        ),
    )
    return target


def measure(arguments: argparse.Namespace) -> dict[str, Any]:
    # Imported after FOL_DATA_DIR is set: every setting read from here on sees the copy.
    import front_office.assistant.api as api
    from front_office.assistant.policy import POLICY_VERSION
    from front_office.config import load_assistant_settings, load_settings
    from front_office.domain.assistant import Mode
    from front_office.providers.ollama import OllamaProvider
    from front_office.services import Lab

    settings = load_assistant_settings(load_settings(ROOT).config_dir)
    ready = api.status(ROOT)
    if not ready.is_ready:
        raise SystemExit(f"the assistant is not ready: {ready.message}")
    model = ready.model
    provider = OllamaProvider(settings.ollama.host, timeout=settings.ollama.timeout_seconds)
    with Lab.open(ROOT) as lab:
        status = lab.status()
        season = status.latest_stats_season
        build = status.build_id
        rosters = len(lab.rosters.list())
    web = ready.web_search
    run: dict[str, Any] = {
        "started": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "milestone": MILESTONE,
        "model": model,
        "policy": POLICY_VERSION,
        "machine": {"python": platform.python_version(), "system": platform.platform()},
        "build_id": build,
        "season": season,
        "web_search": web,
        "keep_alive": settings.ollama.keep_alive,
        "rosters_before": rosters,
        "passes": [],
    }

    for loaded in provider.loaded():
        provider.unload(loaded.name)
    time.sleep(3)
    run["gpu_before"] = gpu()
    quick = settings.mode(Mode.QUICK)
    started = time.monotonic()
    probe = provider.chat(
        model,
        [{"role": "user", "content": "Say OK."}],
        context_tokens=quick.context_tokens,
        max_output_tokens=8,
        keep_alive=settings.ollama.keep_alive,
    )
    run["load"] = {
        "wall_seconds": round(time.monotonic() - started, 2),
        "load_seconds": probe.load_seconds,
    }
    run["loaded"] = [
        {
            "name": item.name,
            "size_mib": round(item.size / MIB),
            "vram_mib": round(item.size_vram / MIB),
            "context_tokens": item.context_length,
        }
        for item in provider.loaded()
    ]
    run["gpu_loaded"] = gpu()
    for loaded in provider.loaded():
        provider.unload(loaded.name)
    time.sleep(3)

    for number in range(1 if arguments.once else 2):
        with Lab.open(ROOT) as lab:
            workspace = lab.workspaces.create(f"Release session {number + 1}").workspace_id
        records = []
        for position, (case, mode, text) in enumerate(SESSION):
            question = api.Question(text, season=season, mode=Mode(mode))
            job = api.start(question, workspace, project_root=ROOT, today=date.today())
            finished = job.wait(WAIT_SECONDS[mode])
            if not finished:
                job.stop()
                job.wait(60)
            answer = job.answer
            steps = answer.steps if answer is not None else job.steps
            record = {
                "case": case,
                "mode": mode,
                "cold": number == 0 and position == 0,
                "finished": finished,
                "seconds": round(job.seconds, 2),
                "outcome": None if answer is None else answer.outcome.value,
                "error": job.error,
                "kept": job.saved is not None,
                "tools": [] if answer is None else [r.tool for r in answer.results],
                "statuses": [] if answer is None else [r.status.value for r in answer.results],
                "warnings": 0 if answer is None else len(answer.warnings),
                "chats": sum(step.kind == "model" for step in steps),
                "model_seconds": round(sum(s.seconds for s in steps if s.kind == "model"), 2),
                "tool_seconds": round(sum(s.seconds for s in steps if s.kind == "tool"), 2),
                "repairs": sum(step.kind == "repair" for step in steps),
                "figures": [] if answer is None else sorted(set(FIGURE.findall(answer.text))),
            }
            if position == 0 and number == 0:
                run["gpu_cold"] = gpu()
            records.append(record)
            calls = ",".join(record["tools"]) or "-"
            print(
                f"  pass {number + 1} {case} {record['outcome'] or 'no answer':12} "
                f"{calls:60} {record['seconds']:6.1f}s",
                flush=True,
            )
        with Lab.open(ROOT) as lab:
            run["rosters_after"] = len(lab.rosters.list())
        run["passes"].append({"workspace": workspace, "records": records})
    run["loaded_after"] = [
        {"name": item.name, "vram_mib": round(item.size_vram / MIB)} for item in provider.loaded()
    ]
    run["gpu_after"] = gpu()
    run["seconds"] = round(time.monotonic() - started, 1)
    run["finished"] = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return run


def report(run: dict[str, Any]) -> str:
    passes = run["passes"]
    first = passes[0]["records"]
    every = [record for one in passes for record in one["records"]]
    warm = [r for r in every if not r["cold"] and r["finished"] and r["outcome"] is not None]
    cold = next((r for r in first if r["cold"]), None)

    def middle(values: list[float]) -> str:
        return f"{statistics.median(values):.1f}" if values else "-"

    def high(values: list[float]) -> str:
        if len(values) < 2:
            return "-"
        return f"{statistics.quantiles(values, n=10, method='inclusive')[-1]:.1f}"

    cold_seconds = "-" if cold is None else f"{cold['seconds']:.1f} s"
    quick = [r["seconds"] for r in warm if r["mode"] == QUICK]
    deep = [r["seconds"] for r in warm if r["mode"] == DEEP]
    before, loaded = run.get("gpu_before"), run.get("gpu_loaded")
    lines = [
        "# A working session with the assistant",
        "",
        f"Generated by `scripts/measure_session.py --write` (milestone {run['milestone']}). "
        "Do not edit by hand.",
        "",
        f"Run {run['started']} UTC on {run['machine']['system']}, Python "
        f"{run['machine']['python']}: model `{run['model']}`, policy {run['policy']}, data build "
        f"{run['build_id']}, season in focus {run['season']}, web search "
        f"{'set up' if run['web_search'] else 'not set up'}. The session's {len(SESSION)} "
        f"questions were asked in order in one workspace, as the AI Research page asks them, "
        f"{'and then again in a second' if len(passes) > 1 else 'once'}; the lab's data folder "
        "was a temporary copy. Times are wall-clock seconds from the question to the answer "
        "kept, everything included: the model, the lab's tools, fetching current information "
        "and pages, and the answer check.",
        "",
        "## Time and memory",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Loading the model into memory | {run['load']['wall_seconds']:.1f} s "
        f"(Ollama's count: {run['load']['load_seconds'] or 0:.1f} s) |",
        f"| First answer, the model not yet loaded (cold) | {cold_seconds} |",
        f"| Quick answers once loaded: median (9 in 10 within) | {middle(quick)} s ({high(quick)} s), "
        f"{len(quick)} answers |",
        f"| Deep answers once loaded: median (slowest) | {middle(deep)} s "
        f"({max(deep):.1f} s), {len(deep)} answers |"
        if deep
        else "| Deep answers once loaded | - |",
        f"| The whole run | {run['seconds'] / 60:.0f} minutes |",
    ]
    for item in run.get("loaded", []):
        lines.append(
            f"| `{item['name']}` in memory | {item['size_mib'] / 1024:.2f} GB, of which "
            f"{item['vram_mib'] / 1024:.2f} GB on the GPU; context {item['context_tokens']} tokens |"
        )
    if before and loaded:
        lines.append(
            f"| GPU memory in use ({loaded['name']}, {loaded['total_mib'] / 1024:.1f} GB) | "
            f"{before['used_mib'] / 1024:.2f} GB before loading, {loaded['used_mib'] / 1024:.2f} GB "
            "loaded |"
        )
    lines += [
        "",
        "## Each question",
        "",
        "Outcome as the answer was labelled; tools in the order called; a repair is the "
        "checker sending a draft back once. A question asked twice is side by side.",
        "",
        "| Question | Mode | " + " | ".join(f"Pass {n + 1}" for n in range(len(passes))) + " |",
        "|---|---|" + "---|" * len(passes),
    ]
    by_case = [{r["case"]: r for r in one["records"]} for one in passes]
    for case, mode, text in SESSION:
        cells = []
        for found in by_case:
            r = found.get(case)
            if r is None:
                cells.append("-")
                continue
            what = r["outcome"] or ("stopped" if not r["finished"] else "no answer")
            tools = ", ".join(r["tools"]) or "no tool"
            extra = f"; {r['repairs']} repair" if r["repairs"] else ""
            cells.append(f"{what}, {r['seconds']:.0f} s: {tools}{extra}")
        lines.append(f"| {case}: {text} | {mode} | " + " | ".join(cells) + " |")
    lines += ["", "## Asked twice", ""]
    if len(passes) > 1:
        same_outcome = same_tools = same_figures = 0
        for case, _, _ in SESSION:
            one, two = by_case[0].get(case), by_case[1].get(case)
            if one is None or two is None:
                continue
            same_outcome += one["outcome"] == two["outcome"]
            same_tools += one["tools"] == two["tools"]
            same_figures += one["figures"] == two["figures"]
        lines += [
            f"Of {len(SESSION)} questions asked twice: the same outcome {same_outcome} times, the "
            f"same tools in the same order {same_tools} times, the same figures in the answer "
            f"{same_figures} times. The model runs at temperature 0; what differs comes from "
            "the time budget, current information fetched between the passes, or the model "
            "itself.",
        ]
    else:
        lines.append("The session was asked once.")
    kept = sum(r["kept"] for r in every)
    errors = [r for r in every if r["error"]]
    lines += [
        "",
        "## What was kept and what went wrong",
        "",
        f"- Answers kept in their workspace: {kept} of {len(every)}.",
        f"- Rosters saved during the session: "
        f"{run['rosters_after'] - run['rosters_before']} (the copy's Team Builder held "
        f"{run['rosters_before']} before and {run['rosters_after']} after). Saving is the "
        "user's click on a proposal, never the assistant's: S19 asks for it in words.",
        f"- Answers with an error: {len(errors)}"
        + (": " + ", ".join(f"{r['case']}" for r in errors) if errors else "."),
        f"- Questions still running at their wait: {sum(not r['finished'] for r in every)}.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--once", action="store_true", help="ask the session once, not twice")
    parser.add_argument("--report", type=Path, help="render from a saved run instead of running")
    parser.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(ROOT)}")
    arguments = parser.parse_args()
    if arguments.report is not None:
        run = json.loads(arguments.report.read_text(encoding="utf-8"))
    else:
        # A file a background thread still holds must not cost the run its results.
        with tempfile.TemporaryDirectory(
            prefix="fol-session-", ignore_cleanup_errors=True
        ) as scratch:
            os.environ["FOL_DATA_DIR"] = str(scratch_data(Path(scratch)))
            try:
                run = measure(arguments)
            finally:
                os.environ.pop("FOL_DATA_DIR", None)
            RESULTS.mkdir(parents=True, exist_ok=True)
            stamp = run["started"].replace(":", "").replace("-", "")[:15]
            saved = RESULTS / f"session-{stamp}.json"
            saved.write_text(json.dumps(run, indent=1), encoding="utf-8", newline="\n")
            print(f"saved {saved}")
    if arguments.write:
        REPORT.write_text(report(run), encoding="utf-8", newline="\n")
        print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
