"""The assistant's frozen evaluation cases: well formed, covering, and true.

``fixtures/cases.yaml`` is what every model is scored against (docs/AI_EVALUATION.md).
These tests need no model and no network. They check the file's shape and coverage, and
recompute every frozen figure through the services on the database the case names, so a
case can never assert what the data does not say.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from front_office.assistant.tools import BY_NAME
from front_office.config import load_settings
from front_office.config.settings import read_yaml
from front_office.pipelines.build import BuildReport
from front_office.services import Lab

CASES_FILE = Path(__file__).parent / "fixtures" / "cases.yaml"
SPEC = read_yaml(CASES_FILE)
CASES: list[dict[str, Any]] = SPEC["cases"]

OUTCOMES = {"supported", "qualified", "insufficient", "clarify", "refuse"}
NO_ANSWER = {"insufficient", "clarify", "refuse"}
MODES = {"quick", "deep"}
CITES = {"build", "model", "interval", "as_of", "source", "nba"}

# The tools the model may be asked to call (docs/AI_ASSISTANT_SPEC.md).
TOOLS = set(BY_NAME)

# The least each category must hold: the plan approved at milestone A0.
COVERAGE = {
    "historical": 6,
    "cross_era": 3,
    "ambiguous": 4,
    "missing": 5,
    "benchmark": 3,
    "model": 4,
    "fit": 2,
    "contracts": 3,
    "current": 5,
    "web": 5,
    "rosters": 3,
    "scenarios": 2,
    "methodology": 3,
    "model_ideas": 2,
    "multi_turn": 3,
    "safety": 4,
    "verdict": 2,
}


def _facts() -> Iterator[Any]:
    for case in CASES:
        for number, fact in enumerate(case["expect"].get("facts", []), start=1):
            yield pytest.param(case["database"], fact, id=f"{case['id']}-{number}")


class TestTheFile:
    def test_ids_are_unique(self) -> None:
        counts = Counter(case["id"] for case in CASES)
        assert not [case_id for case_id, n in counts.items() if n > 1]

    def test_every_case_has_what_scoring_needs(self) -> None:
        for case in CASES:
            where = case["id"]
            assert case["category"] in COVERAGE, where
            assert case["mode"] in MODES, where
            assert case["database"] in SPEC["databases"], where
            # The model's next move is scored: after the user's question, or after a
            # tool's result such as a page carrying instructions.
            assert case["turns"] and "user" in case["turns"][0], where
            assert next(iter(case["turns"][-1])) in {"user", "tool"}, where
            for turn in case["turns"]:
                assert len(turn) == 1 and next(iter(turn)) in {"user", "assistant", "tool"}, where
            expect = case["expect"]
            assert expect["outcome"] in OUTCOMES, where
            assert expect["first_call"], where
            assert set(expect.get("cite", [])) <= CITES, where

    def test_first_calls_name_registered_tools(self) -> None:
        for case in CASES:
            for call in case["expect"]["first_call"]:
                if call == "none":
                    continue
                assert call["tool"] in TOOLS, f"{case['id']}: {call['tool']}"
            for tool in case["expect"].get("forbid_calls", []):
                assert tool in TOOLS, f"{case['id']}: {tool}"

    def test_cases_that_need_no_tool_say_so(self) -> None:
        """Clarifying and declining start without a call; the model must not reach for one."""
        for case in CASES:
            if case["expect"]["outcome"] in {"clarify", "refuse"}:
                assert "none" in case["expect"]["first_call"], case["id"]

    def test_an_ambiguous_case_offers_several_candidates(self) -> None:
        for case in CASES:
            if case["expect"]["outcome"] != "clarify":
                continue
            texts = Counter(item["text"] for item in case["context"].get("resolved", []))
            assert max(texts.values(), default=0) >= 2, case["id"]


class TestCoverage:
    def test_every_category_holds_its_share(self) -> None:
        counts = Counter(case["category"] for case in CASES)
        short = {
            name: (counts[name], least) for name, least in COVERAGE.items() if counts[name] < least
        }
        assert not short, f"categories below their planned count: {short}"

    def test_there_are_enough_cases(self) -> None:
        assert len(CASES) >= 40

    def test_there_are_enough_cases_without_an_answer(self) -> None:
        """Clarifying, declining and saying what is missing are answers too."""
        assert sum(case["expect"]["outcome"] in NO_ANSWER for case in CASES) >= 12

    def test_there_are_known_figures(self) -> None:
        assert sum(len(case["expect"].get("facts", [])) for case in CASES) >= 30


# --- the figures, recomputed ---------------------------------------------------------------


@pytest.fixture(scope="module")
def labs(
    built_template: tuple[Path, BuildReport], contract_template: Path, priced_template: Path
) -> Iterator[dict]:
    opened = {
        "fixture": Lab(load_settings(built_template[0])),
        "contracts": Lab(load_settings(contract_template)),
        "priced": Lab(load_settings(priced_template)),
    }
    yield opened
    for lab in opened.values():
        lab.close()


def _call(lab: Lab, call: str, args: dict[str, Any] | None) -> Any:
    """``teams.table`` with ``{season: ...}`` is ``lab.teams.table(season=...)``."""
    *owners, method = call.split(".")
    target: Any = lab
    for owner in owners:
        target = getattr(target, owner)
    arguments = dict(args or {})
    if "era" in arguments:
        arguments["era"] = lab.benchmarks.era(arguments["era"])
    return getattr(target, method)(**arguments)


def _value(result: Any, fact: dict[str, Any]) -> Any:
    for attribute in filter(None, fact.get("path", "").split(".")):
        result = getattr(result, attribute)
    if "count" in fact:
        return len(result)
    if "row" in fact:
        return result.loc[fact["row"], fact["column"]]
    if "match" in fact:
        rows = result
        for column, wanted in fact["match"].items():
            rows = rows[rows[column] == wanted]
        assert len(rows) == 1, f"{fact['match']} matches {len(rows)} rows"
        return rows.iloc[0][fact["column"]]
    return result


def _agrees(actual: Any, expected: Any, tolerance: float) -> bool:
    if expected is None:
        return actual is None or (not isinstance(actual, str) and bool(pd.isna(actual)))
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, str):
        if isinstance(actual, datetime | date):
            return actual.isoformat()[: len(expected)] == expected
        return str(actual) == expected
    actual = float(actual)
    return not math.isnan(actual) and abs(actual - float(expected)) <= tolerance


@pytest.mark.parametrize(("database", "fact"), list(_facts()))
def test_a_frozen_figure_is_what_the_service_returns(
    labs: dict[str, Lab], database: str, fact: dict[str, Any]
) -> None:
    actual = _value(_call(labs[database], fact["call"], fact.get("args")), fact)
    expected = fact.get("count", fact.get("value"))
    assert _agrees(actual, expected, float(fact.get("tolerance", 0))), (
        f"{fact['call']} gives {actual!r}, the case says {expected!r}"
    )
