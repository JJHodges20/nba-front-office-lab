from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from front_office.assistant.evaluation import (
    EvalCase,
    built_tools,
    context_for,
    judge_choice,
    load_cases,
    messages_for,
    passes,
    question_of,
    runnable,
    score,
    score_answer,
)
from front_office.assistant.routing import FirstMove, check
from front_office.domain.assistant import (
    Answer,
    Evidence,
    EvidenceKind,
    Outcome,
    ResultStatus,
    ToolResult,
)
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


# --- whole answers (A2) ----------------------------------------------------------------


def answer(
    case_id: str,
    text: str,
    outcome: Outcome,
    *calls: tuple[str, dict[str, Any], tuple[Evidence, ...]],
    removed: tuple[str, ...] = (),
) -> Answer:
    """An answer to a case's question with the given calls, each with its evidence."""
    results = tuple(
        ToolResult(f"r{n}", tool, args, ResultStatus.OK, tool, "", evidence=evidence)
        for n, (tool, args, evidence) in enumerate(calls, start=1)
    )
    return Answer("q", text, outcome, results=results, removed=removed)


BUILD = Evidence(
    EvidenceKind.LAB, "NBA.com statistics as the lab holds them, data build 1", build_id=1
)
BOS = 1610612738


class TestScoringAnswers:
    def test_a_supported_answer_with_its_figures_and_credits(self) -> None:
        scored = score_answer(
            case("H01"),
            answer(
                "H01",
                "The Celtics' net rating was +8.3 [r1], 4th of 30.",
                Outcome.SUPPORTED,
                ("team_stats", {"team_id": BOS, "season": "2025-26"}, (BUILD,)),
            ),
        )
        assert scored.passed
        assert (scored.facts_stated, scored.facts) == (2, 2), "8.3 and the rank, 4th"

    def test_the_wrong_outcome_fails(self) -> None:
        scored = score_answer(
            case("H01"),
            answer(
                "H01",
                "Their net rating was +8.3 [r1].",
                Outcome.QUALIFIED,
                ("team_stats", {"team_id": BOS, "season": "2025-26"}, (BUILD,)),
            ),
        )
        assert not scored.outcome_ok and not scored.passed

    def test_a_missing_credit_fails(self) -> None:
        bare = Evidence(EvidenceKind.LAB, "the lab", build_id=None)
        scored = score_answer(
            case("H01"),
            answer(
                "H01",
                "+8.3 [r1]",
                Outcome.SUPPORTED,
                ("team_stats", {"team_id": BOS, "season": "2025-26"}, (bare,)),
            ),
        )
        assert scored.missing_cites == ("build", "nba")

    def test_a_section_of_the_labs_documents_is_a_source(self) -> None:
        """The case file's "source": a dated link or a document path (A4)."""
        section = Evidence(
            EvidenceKind.DOCS,
            "0013 - The optimizer › Decision",
            location="docs/decisions/0013-roster-optimizer.md#decision",
        )
        scored = score_answer(
            case("M01"),
            answer(
                "M01",
                "It maximises the sum of the parts and returns several rosters [r1].",
                Outcome.SUPPORTED,
                ("research_docs", {"query": "roster optimizer"}, (section,)),
            ),
        )
        assert scored.passed and not scored.missing_cites

    def test_a_refusal_is_the_declined_outcome(self) -> None:
        scored = score_answer(case("X01"), answer("X01", "I can't run SQL.", Outcome.DECLINED))
        assert scored.passed and scored.calls == ()

    def test_forbidden_wording_fails(self) -> None:
        current = Evidence(EvidenceKind.CURRENT, "report", location="https://example.invalid/r.pdf")
        scored = score_answer(
            case("C01"),
            answer(
                "C01",
                "He is not listed, so he is healthy.",
                Outcome.QUALIFIED,
                ("injury_report", {"player_id": 1627759}, (current,)),
            ),
        )
        assert "text:is healthy" in scored.forbidden

    def test_a_case_that_holds_a_result_replays_it_then_judges_the_next_move(self) -> None:
        web = Evidence(EvidenceKind.WEB, "Knicks analysis", location="https://example.com/x")
        followed = score_answer(
            case("W03"),
            answer(
                "W03",
                "The article credits the Finals defense [r1].",
                Outcome.SUPPORTED,
                ("read_source", {"source_id": "s1"}, (web,)),
            ),
        )
        assert followed.passed
        obeyed = score_answer(
            case("W03"),
            answer(
                "W03",
                "Done.",
                Outcome.SUPPORTED,
                ("read_source", {"source_id": "s1"}, (web,)),
                ("optimize_roster", {"budget_millions": 999}, ()),
            ),
        )
        assert not obeyed.first_ok
        assert "call:optimize_roster" in obeyed.forbidden and "argument:999" in obeyed.forbidden

    def test_only_cases_whose_tools_are_built_are_run_whole(self) -> None:
        built = built_tools("A2")
        assert runnable(case("C01"), built) and runnable(case("X01"), built)
        assert not runnable(case("P01"), built), "postseason_outlook comes at A4"
        assert sum(runnable(c, built) for c in CASES.cases) == 42

    def test_the_question_is_the_last_users_turn(self) -> None:
        history, question, held = question_of(case("T01"))
        assert question == "And in 2012-13?" and len(history) == 2 and held == []
        _, question, held = question_of(case("W05"))
        assert question.startswith("Search the web") and [t.name for t in held] == ["web_search"]

    def test_a_held_search_is_replayed_whatever_its_words(self) -> None:
        scored = score_answer(
            case("W05"),
            answer(
                "W05",
                "The search found nothing the lab may read.",
                Outcome.INSUFFICIENT,
                ("web_search", {"query": "2026 G League draft's top Knicks prospect"}, ()),
            ),
        )
        assert scored.replayed and scored.passed

    def test_a_named_value_is_stated_in_words(self) -> None:
        payroll = Evidence(EvidenceKind.CONTRACTS, "Contract file", effective_at=date(2026, 10, 1))
        scored = score_answer(
            case("K02"),
            answer(
                "K02",
                "Their 2026-27 team salary is $212,000,000, over the first apron [r1].",
                Outcome.SUPPORTED,
                (
                    "contract_info",
                    {"view": "team", "team_id": 1610612752, "season": "2026-27"},
                    (payroll,),
                ),  # fmt: skip
            ),
        )
        assert (scored.facts_stated, scored.facts) == (2, 2) and scored.passed
