"""Workspaces (A6): what a workspace keeps, what a follow-up reads, and that the user's
research outlasts a build. Each test works on a private copy of a built project."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from front_office.config import Settings, load_settings
from front_office.config.assistant import load_assistant_settings
from front_office.domain.assistant import (
    Answer,
    Evidence,
    EvidenceKind,
    Mode,
    Outcome,
    ResultStatus,
    ToolResult,
)
from front_office.domain.experiments import ExperimentIdea
from front_office.domain.optimizer import BudgetMode
from front_office.domain.proposals import RosterProposal
from front_office.domain.research import Focus, SavedTurn
from front_office.domain.tables.current import SOURCES
from front_office.pipelines.build import build_database
from front_office.services import Lab, WorkspaceError
from front_office.services.workspaces import DEFAULT_NAME, HISTORY_TURNS

START = datetime(2026, 10, 10, 13, 0, 0)


@pytest.fixture
def home(built_lab: Settings) -> Iterator[Lab]:
    with Lab(built_lab) as opened:
        yield opened


@pytest.fixture
def priced_home(priced_template: Path, tmp_path: Path) -> Iterator[Lab]:
    target = tmp_path / "priced"
    shutil.copytree(priced_template, target)
    with Lab(load_settings(target)) as opened:
        yield opened


def answer(text: str, *, proposals: tuple[RosterProposal, ...] = ()) -> Answer:
    result = ToolResult(
        result_id="r1",
        tool="optimize_roster" if proposals else "team_stats",
        arguments={},
        status=ResultStatus.OK,
        title="A result",
        text="| Season | Net rating |",
        table=pd.DataFrame({"season": ["2025-26"], "net_rating": [8.3]}),
        evidence=(Evidence(EvidenceKind.LAB, "NBA.com statistics, data build 2", build_id=2),),
        proposals=proposals,
    )
    return Answer(
        question=text, text=f"Answer: {text}", outcome=Outcome.SUPPORTED, results=(result,)
    )


def asked(lab: Lab, workspace_id: int, question: str, *, minutes: int = 0, **changes) -> SavedTurn:  # type: ignore[no-untyped-def]
    build, value = lab.workspaces.stamp()
    workspace = lab.workspaces.get(workspace_id)
    turn = SavedTurn(
        workspace_id=workspace_id,
        conversation=workspace.conversation,
        asked_at=START + timedelta(minutes=minutes),
        question=question,
        mode=Mode.QUICK,
        focus=Focus(season="2025-26", season_type="regular"),
        asked_from="AI Research",
        answer=answer(question),
        build_id=build,
        value_model=value,
    )
    return lab.workspaces.record(replace(turn, **changes))


class TestWorkspaces:
    def test_one_is_made_the_first_time_one_is_needed(self, home: Lab) -> None:
        service = home.workspaces
        first = service.default()
        assert first.name == DEFAULT_NAME and service.default() == first
        later = service.create("Knicks rebuild", goal="Find a starting center")
        asked(home, later.workspace_id, "Who started at center?")
        assert service.default().workspace_id == later.workspace_id, "the most recently used"
        for workspace in service.list():
            service.update(workspace.workspace_id, archived=True)
        fresh = service.default()
        assert fresh.name == f"{DEFAULT_NAME} 2", "a name no workspace has, archived ones too"

    def test_a_workspace_is_named_described_focused_and_put_away(self, home: Lab) -> None:
        service = home.workspaces
        made = service.create("Budget contender", focus=Focus(team_id=1610612752))
        changed = service.update(
            made.workspace_id,
            name="Budget contender 2026",
            goal="A contender under $150M",
            notes="Prefer young wings.",
            focus=Focus(season="2025-26", roster_id=4),
        )
        assert (changed.name, changed.goal, changed.notes) == (
            "Budget contender 2026",
            "A contender under $150M",
            "Prefer young wings.",
        )
        assert changed.focus == Focus(season="2025-26", roster_id=4), "the focus is set whole"
        service.update(made.workspace_id, archived=True)
        assert made.workspace_id not in [w.workspace_id for w in service.list()]
        assert [w.name for w in service.list(archived=True)] == ["Budget contender 2026"]
        with pytest.raises(WorkspaceError, match="already exists"):
            service.create("budget CONTENDER 2026")


class TestTurns:
    def test_a_turn_is_kept_as_it_came_back(self, home: Lab) -> None:
        service = home.workspaces
        workspace = service.create("History")
        recorded = asked(home, workspace.workspace_id, "How did the Celtics do?")
        (kept,) = service.turns(workspace.workspace_id)
        assert kept.turn_id == recorded.turn_id and kept.turn_id is not None
        assert kept.answer is not None and kept.answer.text == "Answer: How did the Celtics do?"
        table = kept.answer.results[0].table
        assert table is not None and table.to_dict("records") == [
            {"season": "2025-26", "net_rating": 8.3}
        ]
        assert (kept.build_id, kept.value_model) == home.workspaces.stamp()
        assert kept.focus == Focus(season="2025-26", season_type="regular")

    def test_a_follow_up_reads_only_its_own_workspace_and_conversation(self, home: Lab) -> None:
        service = home.workspaces
        knicks, celtics = service.create("Knicks"), service.create("Celtics")
        for n in range(HISTORY_TURNS + 1):
            asked(home, knicks.workspace_id, f"Knicks question {n}", minutes=n)
        asked(home, celtics.workspace_id, "Celtics question", minutes=10)
        asked(home, knicks.workspace_id, "Unanswered", minutes=11, answer=None, error="Ollama down")
        history = [turn.question for turn in service.history(knicks.workspace_id)]
        assert history == [f"Knicks question {n}" for n in range(1, HISTORY_TURNS + 1)]
        assert [t.question for t in service.history(celtics.workspace_id)] == ["Celtics question"]
        service.new_conversation(knicks.workspace_id)
        assert service.history(knicks.workspace_id) == (), "a new conversation follows nothing"
        assert len(service.turns(knicks.workspace_id)) == HISTORY_TURNS + 2, "history is kept"

    def test_what_changed_since_an_answer_is_said(self, home: Lab) -> None:
        service = home.workspaces
        workspace = service.create("Old answers")
        current = asked(home, workspace.workspace_id, "Now?")
        assert service.changed_since(current) == ()
        build, value = service.stamp()
        old = asked(home, workspace.workspace_id, "Then?", build_id=build + 7, value_model="r1")
        assert service.changed_since(old) == (
            f"The lab's data has been rebuilt since (build {build + 7} then, {build} now).",
            f"The player value model has changed since (r1 then, {value} now).",
        )

    def test_current_information_and_the_web_are_said_to_age(self, home: Lab) -> None:
        """They change without a build: once a question would fetch the soonest current
        source again, an answer that read them says when it did."""
        service = home.workspaces
        workspace = service.create("The news")
        turn = asked(home, workspace.workspace_id, "Who is out tonight?")
        assert turn.answer is not None
        current = load_assistant_settings(home.settings.config_dir).current
        soonest = timedelta(minutes=min(current.minutes(source) for source in SOURCES))
        said = (
            "It read current information or the web as of 2026-10-10 13:00 UTC, which may "
            "have changed since.",
        )
        for kind in (EvidenceKind.CURRENT, EvidenceKind.WEB):
            read = Evidence(kind, "What was read", retrieved_at=START)
            result = replace(turn.answer.results[0], evidence=(read,))
            news = replace(turn, answer=replace(turn.answer, results=(result,)))
            assert service.changed_since(news, now=START + soonest - timedelta(minutes=1)) == ()
            assert service.changed_since(news, now=START + soonest) == said
        assert service.changed_since(turn, now=START + timedelta(days=3)) == (), "the lab's alone"

    def test_findings_outlast_the_history(self, home: Lab) -> None:
        service = home.workspaces
        workspace = service.create("Findings")
        turn = asked(home, workspace.workspace_id, "How good was their defense?")
        finding = service.save_finding(turn, "Their defense", note="Check again in March.")
        assert finding.title == "Their defense" and finding.turn_id == turn.turn_id
        assert finding.evidence == "The lab's data: NBA.com statistics, data build 2"
        assert service.clear_history(workspace.workspace_id) == 1
        assert service.turns(workspace.workspace_id) == ()
        (kept,) = service.findings(workspace.workspace_id)
        assert kept.answer_text == "Answer: How good was their defense?"
        service.update_finding(kept.finding_id, title="Defense, 2025-26", note=None)
        assert service.findings(workspace.workspace_id)[0].title == "Defense, 2025-26"
        service.delete_finding(kept.finding_id)
        assert service.findings(workspace.workspace_id) == ()

    def test_the_users_research_outlasts_a_build(self, home: Lab, built_lab: Settings) -> None:
        workspace = home.workspaces.create("Kept through a build")
        asked(home, workspace.workspace_id, "Before the build")
        assert build_database(built_lab).loaded
        (turn,) = home.workspaces.turns(workspace.workspace_id)
        assert turn.question == "Before the build"
        assert home.workspaces.changed_since(turn), "and it says the data was rebuilt since"


class TestProposals:
    @pytest.fixture
    def proposals(self, priced_home: Lab) -> tuple[RosterProposal, ...]:
        request = priced_home.optimizer.defaults().model_copy(
            update={
                "budget_mode": BudgetMode.CUSTOM,
                "budget": 150_000_000,
                "solutions": 3,
                "roles": {},
                "bigs": 0,
            }
        )
        report = priced_home.optimizer.solve(request)
        return priced_home.proposals.from_report(report)

    def test_proposals_wait_until_the_user_saves_or_declines_them(
        self, priced_home: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        service = priced_home.workspaces
        workspace = service.create("Rosters")
        asked(
            priced_home,
            workspace.workspace_id,
            "Three rosters under $150M?",
            answer=answer("rosters", proposals=proposals),
        )
        held = {
            record.proposal.label: record for record in service.proposals(workspace.workspace_id)
        }
        assert set(held) == {"Option A", "Option B", "Option C"}
        assert {record.status for record in held.values()} == {"draft"}
        assert held["Option A"].proposal == proposals[0]

        saved = service.save_proposal(workspace.workspace_id, proposals[0], "From the workspace")
        again = service.save_proposal(workspace.workspace_id, proposals[0], "Pressed twice")
        service.decline_proposal(workspace.workspace_id, proposals[1].fingerprint)
        assert saved.created and not again.created and again.roster_id == saved.roster_id

        held = {
            record.proposal.label: record for record in service.proposals(workspace.workspace_id)
        }
        assert (held["Option A"].status, held["Option A"].roster_id) == ("saved", saved.roster_id)
        assert held["Option B"].status == "declined" and held["Option B"].decided_at is not None
        assert held["Option C"].status == "draft"
        log = service.approvals(workspace.workspace_id)
        assert [entry.action for entry in log] == ["saved", "already_saved", "declined"]
        assert len(priced_home.rosters.list()) == 1

    def test_a_refused_save_is_logged_and_the_proposal_waits(
        self, priced_home: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        service = priced_home.workspaces
        workspace = service.create("Stale")
        first, *rest = proposals[0].players
        stale = proposals[0].model_copy(
            update={"players": (first.model_copy(update={"salary": 1}), *rest)}
        )
        asked(
            priced_home, workspace.workspace_id, "A roster?", answer=answer("r", proposals=(stale,))
        )
        saved = service.save_proposal(workspace.workspace_id, stale, "Never saved")
        assert not saved.saved
        (record,) = service.proposals(workspace.workspace_id)
        assert record.status == "draft"
        (entry,) = service.approvals(workspace.workspace_id)
        assert entry.action == "refused" and "no longer gives the same salary" in entry.detail  # type: ignore[operator]
        assert priced_home.rosters.list().empty

    def test_deleting_a_workspace_leaves_the_rosters_saved_from_it(
        self, priced_home: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        service = priced_home.workspaces
        workspace = service.create("Gone soon")
        asked(
            priced_home, workspace.workspace_id, "R?", answer=answer("r", proposals=proposals[:1])
        )
        saved = service.save_proposal(workspace.workspace_id, proposals[0], "Outlives it")
        service.delete(workspace.workspace_id)
        assert workspace.workspace_id not in [w.workspace_id for w in service.list(archived=None)]
        assert priced_home.rosters.get(saved.roster_id)["name"] == "Outlives it"  # type: ignore[arg-type]


IDEA = ExperimentIdea(
    title="Rookies by draft place",
    observation="The value model knows little of a rookie, and its projections miss them most.",
    hypothesis="Where a rookie was drafted says how good they are before they play.",
    change="Start a rookie's estimate from the level of players drafted at the same place.",
    failure_modes=("Too few rookies each season to tell a difference from nothing.",),
)


def model_files(lab: Lab) -> dict[str, bytes]:
    folder = lab.settings.config_dir / "models"
    return {path.name: path.read_bytes() for path in folder.iterdir()}


class TestExperiments:
    """A8: experiment proposals the user keeps, for review only."""

    def test_kept_once_noted_and_deleted_and_nothing_else_changes(self, home: Lab) -> None:
        service = home.workspaces
        workspace = service.create("Ideas")
        before = model_files(home)
        proposal = home.experiments.draft("player_value", IDEA)
        kept = service.keep_experiment(workspace.workspace_id, proposal, turn_id=None)
        again = service.keep_experiment(workspace.workspace_id, proposal, note="pressed twice")
        assert again.experiment_id == kept.experiment_id and again.note is None
        assert kept.proposal == proposal and kept.fingerprint == proposal.fingerprint
        service.annotate_experiment(kept.experiment_id, "After the season.")
        (listed,) = service.experiments(workspace.workspace_id)
        assert listed.note == "After the season."
        assert model_files(home) == before, "keeping a proposal changes no model"
        service.delete_experiment(kept.experiment_id)
        assert service.experiments(workspace.workspace_id) == ()

    def test_they_are_exported_with_the_workspace(self, home: Lab) -> None:
        service = home.workspaces
        workspace = service.create("Exported ideas")
        proposal = home.experiments.draft("roster_fit", IDEA)
        service.keep_experiment(workspace.workspace_id, proposal, note="Ask for lineups.")
        document = json.loads(service.export_json(workspace.workspace_id))
        (exported,) = document["experiments"]
        assert exported["model"] == "roster_fit" and exported["note"] == "Ask for lineups."
        assert exported["proposal"]["idea"]["title"] == "Rookies by draft place"
        markdown = service.export_markdown(workspace.workspace_id)
        assert "## Experiment proposals" in markdown
        assert "### Experiment proposal: Rookies by draft place" in markdown
        assert "#### The test - the lab's" in markdown and "Note: Ask for lineups." in markdown


class TestExport:
    def test_json_holds_everything_and_markdown_reads(self, home: Lab) -> None:
        service = home.workspaces
        workspace = service.create("Exported", goal="Compare two teams")
        service.update(workspace.workspace_id, notes="My own note.")
        turn = asked(home, workspace.workspace_id, "How did the Celtics do?")
        service.save_finding(turn, "Celtics, 2025-26")
        document = json.loads(service.export_json(workspace.workspace_id))
        assert document["workspace"]["name"] == "Exported"
        assert document["workspace"]["notes"] == "My own note."
        (exported,) = document["turns"]
        assert exported["question"] == "How did the Celtics do?"
        assert exported["answer"]["text"] == "Answer: How did the Celtics do?"
        assert exported["answer"]["results"][0]["table"]["data"] == [["2025-26", 8.3]]
        assert [f["title"] for f in document["findings"]] == ["Celtics, 2025-26"]
        markdown = service.export_markdown(workspace.workspace_id)
        for part in (
            "# Exported",
            "*Compare two teams*",
            "## Notes",
            "### How did the Celtics do?",
            "Answer: How did the Celtics do?",
            "Rests on:",
            "## Findings",
            "### Celtics, 2025-26",
            "None proposed.",
        ):
            assert part in markdown
