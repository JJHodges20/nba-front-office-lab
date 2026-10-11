"""What a workspace keeps (A6): the focus, and the codec that keeps an answer whole."""

from __future__ import annotations

import json
from datetime import date, datetime

import numpy as np
import pandas as pd

from front_office.domain.assistant import (
    Answer,
    Chart,
    Evidence,
    EvidenceKind,
    Mode,
    NameCandidate,
    Outcome,
    ResultStatus,
    Step,
    ToolResult,
)
from front_office.domain.proposals import ProposalBasis, ProposedPlayer, RosterProposal
from front_office.domain.research import (
    Focus,
    SavedTurn,
    answer_from_dict,
    answer_to_dict,
    frame_from_dict,
    frame_to_dict,
    payload_parts,
    turn_payload,
)

PROPOSAL = RosterProposal(
    label="Option A",
    payroll_season="2026-27",
    stats_season="2025-26",
    budget_mode="custom",
    budget_label="Owner's budget",
    budget=150_000_000,
    requirements=("14 to 15 players",),
    players=(
        ProposedPlayer(
            player_id=1628369,
            player_name="Jayson Tatum",
            team="BOS",
            position="F",
            slot="SF",
            salary=40_000_000,
            projected_impact=3.2,
            projected_share=0.7,
            projected_wins=8.1,
        ),
    ),
    payroll=40_000_000,
    room=110_000_000,
    rating=-1.7,
    error=3.63,
    basis=ProposalBasis(build_id=16, value_model="r2", contract_as_of=date(2026, 10, 1)),
)


def an_answer() -> Answer:
    table = pd.DataFrame(
        {
            "season": ["2025-26", "2024-25"],
            "net_rating": [np.float64(8.3), np.nan],
            "wins": [np.int64(56), np.int64(61)],
            "made_playoffs": [True, False],
            "as_of": [pd.Timestamp("2026-10-01 12:00"), pd.NaT],
        }
    )
    chart = Chart(
        "intervals",
        "Chances by round",
        pd.DataFrame({"stage": ["Title"], "p": [0.12], "lo": [0.05], "hi": [0.2], "text": ["12%"]}),
        x="stage",
        y="p",
        text="text",
        low="lo",
        high="hi",
        y_range=(0.0, 1.0),
        reference=0.5,
        estimate=True,
    )
    result = ToolResult(
        result_id="r1",
        tool="team_stats",
        arguments={"team_id": 1610612738, "season": "2025-26"},
        status=ResultStatus.OK,
        title="Boston Celtics, every season",
        text="| Season | Net rating |",
        table=table,
        evidence=(
            Evidence(
                EvidenceKind.WEB,
                "A story",
                "https://example.com/story",
                retrieved_at=datetime(2026, 10, 9, 18, 30),
                published_at=datetime(2026, 10, 8, 9, 0),
                effective_at=date(2026, 10, 8),
            ),
            Evidence(EvidenceKind.LAB, "NBA.com statistics, data build 16", build_id=16),
        ),
        warnings=("A note.",),
        kinds=("measured",),
        limits=("No report published.",),
        charts=(chart,),
        proposals=(PROPOSAL,),
    )
    return Answer(
        question="How have the Celtics done?",
        text="Their net rating was +8.3 [r1].",
        outcome=Outcome.SUPPORTED,
        results=(result,),
        options=(NameCandidate(text="Brown", kind="player", id=1627759, name="Jaylen Brown"),),
        removed=("9.9",),
        warnings=("Checked.",),
        steps=(Step("tool", "team_stats", 0.4),),
        model="qwen3:8b",
        policy="2026-10-10.3",
        seconds=3.5,
    )


class TestFocus:
    def test_a_focus_fills_what_it_leaves_open_from_another(self) -> None:
        workspace = Focus(team_id=1610612752, roster_id=3)
        sidebar = Focus(season="2025-26", season_type="regular", team_id=1610612738)
        assert workspace.over(sidebar) == Focus(
            season="2025-26", season_type="regular", team_id=1610612752, roster_id=3
        )
        assert Focus().is_empty and not workspace.is_empty


class TestCodec:
    def test_an_answer_comes_back_whole(self) -> None:
        answer = an_answer()
        text = json.dumps(answer_to_dict(answer))  # plain JSON all the way down
        again = answer_from_dict(json.loads(text))
        assert (again.question, again.text, again.outcome) == (
            answer.question,
            answer.text,
            answer.outcome,
        )
        assert (again.options, again.removed, again.warnings, again.steps) == (
            answer.options,
            answer.removed,
            answer.warnings,
            answer.steps,
        )
        assert (again.model, again.policy, again.seconds) == ("qwen3:8b", "2026-10-10.3", 3.5)
        (result,) = again.results
        original = answer.results[0]
        assert result.evidence == original.evidence, "dates and times survive"
        assert result.proposals == original.proposals
        assert result.proposals[0].fingerprint == PROPOSAL.fingerprint
        assert (result.arguments, result.limits, result.kinds) == (
            original.arguments,
            original.limits,
            original.kinds,
        )
        assert answer.evidence == again.evidence

    def test_rows_keep_their_values(self) -> None:
        table = an_answer().results[0].table
        again = frame_from_dict(json.loads(json.dumps(frame_to_dict(table))))
        assert again is not None and list(again.columns) == list(table.columns)
        assert again["wins"].tolist() == [56, 61] and again["made_playoffs"].tolist() == [
            True,
            False,
        ]
        assert again.at[0, "net_rating"] == 8.3 and pd.isna(again.at[1, "net_rating"])
        assert again.at[0, "as_of"] == "2026-10-01T12:00:00" and pd.isna(again.at[1, "as_of"])

    def test_a_named_index_becomes_a_column(self) -> None:
        frame = pd.DataFrame({"impact": [1.5]}, index=pd.Index([1628369], name="player_id"))
        again = frame_from_dict(frame_to_dict(frame))
        assert again is not None and again.to_dict("records") == [
            {"player_id": 1628369, "impact": 1.5}
        ]

    def test_a_chart_comes_back_drawable(self) -> None:
        chart = an_answer().results[0].charts[0]
        (again,) = answer_from_dict(answer_to_dict(an_answer())).results[0].charts
        assert (again.kind, again.x, again.y, again.low, again.high) == (
            chart.kind,
            chart.x,
            chart.y,
            chart.low,
            chart.high,
        )
        assert (again.y_range, again.reference, again.estimate) == ((0.0, 1.0), 0.5, True)
        assert again.frame.to_dict("records") == chart.frame.to_dict("records")

    def test_a_turn_payload_keeps_the_answer_the_steps_and_the_readings(self) -> None:
        reading = NameCandidate(text="Brown", kind="player", id=1627759, name="Jaylen Brown")
        turn = SavedTurn(
            workspace_id=1,
            conversation=1,
            asked_at=datetime(2026, 10, 10, 13, 0),
            question="How did Brown shoot?",
            mode=Mode.QUICK,
            focus=Focus(season="2025-26"),
            asked_from="AI Research",
            answer=an_answer(),
            steps=(Step("model", "answered", 1.0),),
            resolved=(reading,),
        )
        answer, steps, resolved = payload_parts(turn_payload(turn))
        assert answer is not None and answer.text == turn.answer.text  # type: ignore[union-attr]
        assert steps == turn.steps and resolved == (reading,)
        empty = SavedTurn(
            workspace_id=1,
            conversation=1,
            asked_at=datetime(2026, 10, 10),
            question="?",
            mode=Mode.DEEP,
            focus=Focus(),
            asked_from="AI Research",
            answer=None,
            error="Ollama is not running.",
        )
        assert payload_parts(turn_payload(empty)) == (None, (), ())
