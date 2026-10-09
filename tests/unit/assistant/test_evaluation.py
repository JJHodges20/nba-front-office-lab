from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from front_office.assistant.evaluation import (
    EvalCase,
    context_for,
    judge_choice,
    load_cases,
    messages_for,
    passes,
    score,
)
from front_office.assistant.routing import FirstMove, check
from front_office.providers.ollama import ChatReply, ToolCall

CASES = load_cases(Path(__file__).resolve().parents[2] / "assistant" / "fixtures" / "cases.yaml")
BY_ID = {case.id: case for case in CASES.cases}


def move(
    *replies: tuple[str, list[tuple[str, dict[str, Any]]]], cut_off: bool = False
) -> FirstMove:
    """A first move from (text, calls) replies; a second reply means a repair was asked."""
    built = tuple(
        ChatReply(
            model="m",
            content=text,
            thinking="",
            tool_calls=tuple(ToolCall(name, args) for name, args in calls),
            done_reason="length" if cut_off else "stop",
            prompt_tokens=1,
            output_tokens=1,
            load_seconds=0.0,
            prompt_seconds=0.0,
            output_seconds=0.0,
            total_seconds=0.0,
            first_token_seconds=0.0,
            wall_seconds=0.0,
        )
        for text, calls in replies
    )
    final = tuple(check(call) for call in built[-1].tool_calls)
    return FirstMove(built, final, repaired=len(built) > 1)


def case(case_id: str) -> EvalCase:
    return BY_ID[case_id]


class TestTheFile:
    def test_every_case_loads(self) -> None:
        assert len(CASES.cases) == 59
        assert CASES.today.isoformat() == "2026-10-09"

    def test_a_case_becomes_what_the_model_reads(self) -> None:
        context = context_for(CASES, case("C05"))
        assert context.team_id == 1610612752 and context.data == CASES.databases["fixture"]
        turns = messages_for(case("W03"))
        assert [turn.role for turn in turns] == ["user", "tool"]
        assert turns[1].tool_name == "read_source" and turns[1].arguments == {"source_id": "s1"}


class TestScoring:
    def test_the_right_tool_and_values_pass(self) -> None:
        result = score(
            case("H01"), move(("", [("team_stats", {"team_id": 1610612738, "season": "2025-26"})]))
        )
        assert result.passed and result.choice_ok and result.args_ok and result.valid

    def test_a_wrong_value_fails(self) -> None:
        result = score(
            case("H01"), move(("", [("team_stats", {"team_id": 1610612738, "season": "2024-25"})]))
        )
        assert result.choice_ok and result.args_ok is False and not result.passed

    def test_a_wrong_tool_fails(self) -> None:
        result = score(
            case("H01"), move(("", [("player_stats", {"player_id": 1, "season": "2025-26"})]))
        )
        assert not result.choice_ok and not result.passed

    def test_lists_compare_in_any_order(self) -> None:
        call = ("compare_players", {"player_ids": [1627759, 1628973], "season": "2025-26"})
        assert score(case("T02"), move(("", [call]))).passed

    def test_defaults_count_as_given(self) -> None:
        """H06 expects view games; a call that leaves view out means season, and fails."""
        given = ("player_stats", {"player_id": 1628973, "season": "2025-26", "view": "games"})
        left_out = ("player_stats", {"player_id": 1628973, "season": "2025-26"})
        assert score(case("H06"), move(("", [given]))).passed
        assert not score(case("H06"), move(("", [left_out]))).passed

    def test_calling_nothing_passes_only_where_nothing_is_right(self) -> None:
        assert score(case("A01"), move(("Which Brown do you mean?", []))).passed
        assert not score(case("H01"), move(("The Celtics were good.", []))).passed

    @pytest.mark.parametrize("case_id", ["A01", "X01", "R02"])
    def test_calling_a_tool_where_nothing_is_right_fails(self, case_id: str) -> None:
        assert not score(case(case_id), move(("", [("data_status", {})]))).passed

    def test_a_forbidden_call_fails_even_when_it_was_rejected(self) -> None:
        injected = ("optimize_roster", {"budget_mode": "custom", "budget_millions": 999})
        result = score(case("W03"), move(("", [injected]), ("The article says...", [])))
        assert "call:optimize_roster" in result.forbidden and not result.passed

    def test_forbidden_text_in_an_argument_fails(self) -> None:
        call = ("web_search", {"query": "Celtics stats site:basketball-reference.com"})
        result = score(case("W04"), move(("", [call])))
        assert "argument:basketball-reference" in result.forbidden

    def test_forbidden_wording_in_an_answer_fails(self) -> None:
        result = score(case("R02"), move(("Done - I have saved option B.", [])))
        assert result.forbidden == ("text:I have saved",) and not result.passed

    def test_a_reply_cut_off_fails(self) -> None:
        assert not score(case("A01"), move(("Which", []), cut_off=True)).passed

    def test_a_repaired_call_is_noted(self) -> None:
        bad = ("team_stats", {"team_id": 1610612738, "season": "2025"})
        good = ("team_stats", {"team_id": 1610612738, "season": "2025-26"})
        result = score(case("H01"), move(("", [bad]), ("", [good])))
        assert result.passed and result.repaired and result.valid_first_try is False


class TestJudgingAgain:
    """A recorded move judged again must agree with the live scoring, so that a saved run
    can be re-scored after the user decides a case was wrong."""

    @pytest.mark.parametrize(
        ("case_id", "tool", "arguments"),
        [
            ("H01", "team_stats", {"team_id": 1610612738, "season": "2025-26"}),
            ("H01", "team_stats", {"team_id": 1610612738, "season": "2024-25"}),
            ("H01", "player_stats", {"player_id": 1, "season": "2025-26"}),
            ("A01", None, None),
            ("X01", "data_status", {}),
        ],
    )
    def test_judging_a_recorded_move_agrees_with_scoring_it(
        self, case_id: str, tool: str | None, arguments: dict[str, Any] | None
    ) -> None:
        calls = [] if tool is None else [(tool, arguments)]
        live = score(case(case_id), move(("", calls)))
        assert judge_choice(case(case_id), tool, arguments) == (live.choice_ok, live.args_ok)
        assert passes(live.choice_ok, live.args_ok, live.valid, live.forbidden, live.cut_off) is (
            live.passed
        )


class TestTheWidenedCases:
    """P01 and W01, widened on 2026-10-09 by the user's decision (docs/DEVELOPMENT_LOG.md)."""

    @pytest.mark.parametrize("view", ["team", "season_odds"])
    def test_p01_takes_the_team_or_the_seasons_odds(self, view: str) -> None:
        call = ("postseason_outlook", {"view": view, "team_id": 1610612738, "season": "2025-26"})
        assert score(case("P01"), move(("", [call]))).passed

    def test_p01_still_refuses_a_strength(self) -> None:
        call = ("postseason_outlook", {"view": "strength", "net_rating": 8.3})
        assert not score(case("P01"), move(("", [call]))).passed

    def test_w01_takes_a_look_up_of_the_unresolved_name(self) -> None:
        call = ("resolve_entities", {"text": "Knicks", "kind": "team"})
        assert score(case("W01"), move(("", [call]))).passed
