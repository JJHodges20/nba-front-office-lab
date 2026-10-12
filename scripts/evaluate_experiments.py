"""Evaluate how the AI research assistant drafts experiment proposals (milestone A8).

Runs the frozen questions of tests/assistant/fixtures/experiment_cases.yaml through the
whole assistant - the local model, the lab's tools, the answer checker - on the fixture
database, built here from the fixture store exactly as the tests build it, with the lab's
own documents beside it. Each answer is scored by ``assistant.experiment_evaluation``.
Nothing is fetched. Nothing in the lab changes: the database lives in a temporary folder
that is removed afterwards, and every case checks that no model file changed and no
workspace was written.

    python scripts/evaluate_experiments.py                    every case, the default model
    python scripts/evaluate_experiments.py --cases X01,X07    some of them
    python scripts/evaluate_experiments.py --write            ...and write the report
    python scripts/evaluate_experiments.py --report RUN.json --write   the report from a saved run

Results go to data/assistant/benchmarks/ (not committed); --write renders
docs/research/EXPERIMENT_PROPOSALS.md from them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # the test databases' recipe lives in tests/

from tests.conftest import BUILD_TOOK, BUILT_AT, FIXTURE_RAW  # noqa: E402

from front_office.assistant.experiment_evaluation import (  # noqa: E402
    load_experiment_cases,
    report,
    score_experiment,
    score_record,
)
from front_office.assistant.orchestrator import Assistant  # noqa: E402
from front_office.assistant.policy import POLICY_VERSION  # noqa: E402
from front_office.assistant.toolbox import Toolbox  # noqa: E402
from front_office.config import load_assistant_settings, load_settings  # noqa: E402
from front_office.domain.assistant import Context  # noqa: E402
from front_office.pipelines.build import build_database  # noqa: E402
from front_office.providers.ollama import OllamaError, OllamaProvider  # noqa: E402
from front_office.services import Lab  # noqa: E402

CASES = ROOT / "tests" / "assistant" / "fixtures" / "experiment_cases.yaml"
RESULTS = ROOT / "data" / "assistant" / "benchmarks"
REPORT = ROOT / "docs" / "research" / "EXPERIMENT_PROPOSALS.md"
MILESTONE = "A9"


def model_files(project: Path) -> dict[str, str]:
    folder = project / "configs" / "models"
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()}


def build_fixture(where: Path) -> Path:
    """The fixture build, the tests' recipe, with the lab's own documents beside it."""
    home = where / "fixture"
    shutil.copytree(ROOT / "configs", home / "configs")
    shutil.copytree(ROOT / "docs", home / "docs")
    shutil.copytree(FIXTURE_RAW, home / "data" / "raw")
    moments = iter([BUILT_AT, BUILT_AT + BUILD_TOOK])
    if not build_database(load_settings(home), now=lambda: next(moments)).loaded:
        raise SystemExit("the fixture database could not be built")
    return home


def evaluate(arguments: argparse.Namespace) -> dict[str, Any]:
    settings = load_assistant_settings(load_settings(ROOT).config_dir)
    model = arguments.model or settings.default_model
    cases = load_experiment_cases(CASES)
    only = set(arguments.cases.split(",")) if arguments.cases else None
    chosen = [case for case in cases.cases if only is None or case.id in only]
    provider = OllamaProvider(settings.ollama.host, timeout=settings.ollama.timeout_seconds)
    provider.require_local(model)
    shipped = model_files(ROOT)
    run: dict[str, Any] = {
        "started": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "model": model,
        "milestone": MILESTONE,
        "policy": POLICY_VERSION,
        "frozen_on": cases.frozen_on.isoformat(),
        "records": [],
    }
    with tempfile.TemporaryDirectory(prefix="fol-experiments-") as scratch:
        print("building the test database", flush=True)
        home = build_fixture(Path(scratch))
        lab = Lab(load_settings(home))
        try:
            for case in chosen:
                context = Context(
                    today=cases.today,
                    calendar=cases.calendar,
                    data=" ".join(cases.data.split()),
                    season=cases.season,
                    mode=case.mode,
                )
                assistant = Assistant(
                    lab, settings, provider, model=model, toolbox=Toolbox.lab_only()
                )
                before = model_files(home)
                started = time.monotonic()
                try:
                    answer = assistant.ask(case.question, context)
                except OllamaError as error:
                    run["records"].append(
                        {"case": case.id, "question": case.question, "error": str(error)}
                    )
                    print(f"  {case.id}: error {error}", flush=True)
                    continue
                untouched = model_files(home) == before and not lab.settings.research_path.exists()
                score = score_experiment(
                    case, answer, untouched=untouched, seconds=round(time.monotonic() - started, 2)
                )
                run["records"].append(
                    {
                        **score_record(score),
                        "calls": [
                            {"tool": r.tool, "arguments": r.arguments, "status": r.status.value}
                            for r in answer.results
                        ],
                        "warnings": list(answer.warnings),
                        "text": answer.text,
                    }
                )
                mark = "pass" if score.passed else "FAIL"
                calls = ",".join(r.tool for r in answer.results) or "-"
                print(
                    f"  {case.id:4} {mark} {score.outcome:12} {calls:50} {score.seconds:6.1f}s",
                    flush=True,
                )
        finally:
            lab.close()
    if model_files(ROOT) != shipped:
        raise SystemExit("a model file of the project changed during the run")
    run["finished"] = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", help="default: the assistant's default model")
    parser.add_argument("--cases", help="comma-separated case ids; default: every case")
    parser.add_argument("--report", type=Path, help="render from a saved run instead of running")
    parser.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(ROOT)}")
    arguments = parser.parse_args()
    if arguments.report is not None:
        run = json.loads(arguments.report.read_text(encoding="utf-8"))
    else:
        run = evaluate(arguments)
        RESULTS.mkdir(parents=True, exist_ok=True)
        stamp = run["started"].replace(":", "").replace("-", "")[:15]
        saved = RESULTS / f"experiments-{stamp}.json"
        saved.write_text(json.dumps(run, indent=1), encoding="utf-8", newline="\n")
        print(f"saved {saved}")
    if arguments.write:
        REPORT.write_text(report(run), encoding="utf-8", newline="\n")
        print(f"wrote {REPORT}")
    passed = sum(record.get("passed", False) for record in run["records"])
    print(f"passed {passed}/{len(run['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
