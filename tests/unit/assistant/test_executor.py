from __future__ import annotations

from front_office.assistant.executor import Executor
from front_office.assistant.lab_tools import HANDLERS, Found
from front_office.assistant.routing import Call
from front_office.domain.assistant import ResultStatus
from front_office.services import Lab
from tests.helpers import BOS, BROWN


def call(tool: str, **arguments) -> Call:  # type: ignore[no-untyped-def]
    return Call(tool, arguments, None)


def test_a_call_runs_and_is_numbered(lab: Lab) -> None:
    executor = Executor(lab)
    first = executor.run(call("team_stats", team_id=BOS, season="2025-26"))
    second = executor.run(call("data_status"))
    assert (first.result_id, first.status, second.result_id) == ("r1", ResultStatus.OK, "r2")
    assert first.arguments == {"team_id": BOS, "season": "2025-26"}
    assert first.evidence and isinstance(first.table, object)


def test_only_built_tools_are_offered(lab: Lab) -> None:
    offered = {spec.name for spec in Executor(lab).available()}
    assert {"team_stats", "player_stats", "contract_info"} <= offered
    assert {"player_value", "roster_fit", "postseason_outlook", "simulate_scenario"} <= offered
    assert {"research_docs", "optimize_roster"} <= offered
    data_only = {spec.name for spec in Executor(lab, handlers=HANDLERS).available()}
    assert "team_stats" in data_only and "optimize_roster" not in data_only


def test_a_tool_without_a_handler_says_so(lab: Lab) -> None:
    """Every tool in the registry is built since A5; a toolbox may still leave one out."""
    result = Executor(lab, handlers=HANDLERS).run(call("optimize_roster", budget_mode="salary_cap"))
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.text == "optimize_roster is not built yet (milestone A5); nothing was run."


def test_an_invalid_call_is_refused_without_running(lab: Lab) -> None:
    result = Executor(lab).run(Call("team_stats", {"season": "2025"}, "season: bad"))
    assert (
        result.status is ResultStatus.ERROR
        and result.text == "Rejected, nothing was run: season: bad"
    )


def test_an_invented_team_id_is_refused(lab: Lab) -> None:
    """A1: qwen3:8b called team_stats with team_id 1 for the unresolved Bulls."""
    result = Executor(lab).run(call("team_stats", team_id=1, season="1996-97"))
    assert result.status is ResultStatus.ERROR
    assert "no team with id 1" in result.text and "resolve_entities" in result.text


def test_an_invented_player_id_in_a_list_is_refused(lab: Lab) -> None:
    result = Executor(lab).run(call("compare_players", player_ids=[BROWN, 99], season="2025-26"))
    assert result.status is ResultStatus.ERROR and "no player with id 99" in result.text


def test_a_team_s_id_given_for_a_player_is_sent_where_it_belongs(lab: Lab) -> None:
    """Live at A7: asked what had changed for the Knicks since the contract file, the model
    gave the team's id for the player as well, was told only that no player has it, and
    gave up."""
    result = Executor(lab).run(call("player_stats", player_id=BOS, season="2025-26"))
    assert result.status is ResultStatus.ERROR
    assert f"{BOS} is the id of the Boston Celtics, a team: give it as team_id" in result.text
    assert "resolve_entities" not in result.text


def test_a_player_s_id_given_for_a_team_is_sent_where_it_belongs(lab: Lab) -> None:
    result = Executor(lab).run(call("team_stats", team_id=BROWN, season="2025-26"))
    assert f"{BROWN} is the id of Jaylen Brown, a player: give it as player_id" in result.text


def test_a_failing_handler_becomes_an_error_result(lab: Lab) -> None:
    def broken(lab: Lab, args: object) -> Found:
        raise KeyError("no such row")

    result = Executor(lab, handlers={"data_status": broken}).run(call("data_status"))
    assert result.status is ResultStatus.ERROR and "could not answer" in result.text


def test_the_text_the_model_reads_is_bounded(lab: Lab) -> None:
    def wordy(lab: Lab, args: object) -> Found:
        return Found(ResultStatus.OK, "Wordy", "\n".join(f"line {i}" for i in range(1000)))

    result = Executor(lab, handlers={"data_status": wordy}, max_characters=200).run(
        call("data_status")
    )
    assert len(result.text) < 260 and result.text.endswith("(cut short; the page has the rest)")
