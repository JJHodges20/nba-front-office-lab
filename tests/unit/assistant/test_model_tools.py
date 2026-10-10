"""The model tools against the fixture build: what each view shows, the error it goes out
with, and the files it read. Figures are compared with the services' own."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.assistant import tools as t
from front_office.assistant.executor import Executor
from front_office.assistant.model_tools import (
    FIELD_NOT_MODELLED,
    NO_FIT_SCORE,
    ROLES_ARE_RULES,
)
from front_office.assistant.routing import Call
from front_office.assistant.toolbox import LAB_HANDLERS
from front_office.config import Settings
from front_office.domain.assistant import EvidenceKind, ResultStatus
from front_office.domain.scenario import Adjustment, Scenario, SubjectKind
from front_office.services import METRIC_CATALOGS, Lab, PostseasonService, SimulatorService
from tests.helpers import BOS, BROWN, HART, NYK, WHITE

OK, EMPTY, UNAVAILABLE, ERROR = (
    ResultStatus.OK,
    ResultStatus.EMPTY,
    ResultStatus.UNAVAILABLE,
    ResultStatus.ERROR,
)
CHANCE = METRIC_CATALOGS["Postseason model"]["p_won_championship"].format_value


def run(lab: Lab, tool: str, **arguments):  # type: ignore[no-untyped-def]
    return LAB_HANDLERS[tool](lab, t.BY_NAME[tool].args(**arguments))


def versions(found) -> set[str]:  # type: ignore[no-untyped-def]
    return {item.version for item in found.evidence if item.kind is EvidenceKind.MODEL}


def built(found) -> bool:  # type: ignore[no-untyped-def]
    return any(item.kind is EvidenceKind.LAB and item.build_id for item in found.evidence)


class TestPlayerValue:
    def test_season_leaders_are_ranked_among_everyone_valued(self, lab: Lab) -> None:
        found = run(lab, "player_value", view="season_leaders", season="2025-26")
        frame = lab.value.season("2025-26")
        top = frame.iloc[0]
        impact = lab.value.metrics["impact"].format_value(top["impact"])
        assert found.status is OK and built(found)
        assert f"| 1 | {top['player_name']} | {top['team']} |" in found.text
        assert f"| {impact} |" in found.text.splitlines()[3]
        assert f"among the {len(frame)} players it rated" in found.text
        assert versions(found) == {lab.value.model().version}
        assert "modeled" in found.kinds and found.charts[0].kind == "bars"

    def test_a_projection_goes_out_with_how_far_projections_have_missed(self, lab: Lab) -> None:
        found = run(lab, "player_value", view="projections", player_id=WHITE)
        row = lab.value.projections().loc[WHITE]
        band = lab.simulator.projection_miss(WHITE)
        tested = lab.value.model().validation
        shown = lab.value.metrics["projected_impact"].format_value(row["projected_impact"])
        assert band == lab.simulator.model().band(float(row["projection_reliability"]))
        assert found.status is OK
        assert f"Derrick White going into {lab.value.status().upcoming}" in found.text
        assert f"projected impact {shown}" in found.text
        assert "there is no tested range for one player" in found.text
        assert f"typically off by about {band.spread:.2f} points of impact" in found.text
        assert f"{band.players:,} past player-seasons" in found.text
        assert f"({band.mean_miss:+.2f})" in found.text, "the signed miss, for the checker"
        assert f"off by about {tested.projected.rmse:.2f} points" in found.text

    def test_a_players_seasons_end_with_the_projection(self, lab: Lab) -> None:
        found = run(lab, "player_value", view="player", player_id=WHITE)
        assert found.status is OK
        assert "| 2025-26 | BOS |" in found.text
        assert found.text.index("| 2025-26 |") < found.text.index("going into")

    def test_the_season_ahead_is_projections_not_a_valued_season(self, lab: Lab) -> None:
        upcoming = lab.value.status().upcoming
        found = run(lab, "player_value", view="season_leaders", season=upcoming)
        assert found.status is EMPTY and "projections" in found.text
        assert run(lab, "player_value", view="season_leaders", season="1990-91").status is EMPTY

    @pytest.mark.parametrize("view", ["player", "breakdown"])
    def test_a_players_view_needs_the_player(self, lab: Lab, view: str) -> None:
        found = run(lab, "player_value", view=view)
        assert found.status is ERROR and "player_id" in found.text

    def test_the_breakdown_adds_up_from_its_parts(self, lab: Lab) -> None:
        found = run(lab, "player_value", view="breakdown", player_id=WHITE, season="2025-26")
        parts = lab.value.parts(WHITE, "2025-26")
        assert found.status is OK
        assert all(f"| {label} |" in found.text for label in parts["label"])
        assert found.charts[0].kind == "bars" and len(found.charts[0].frame) == len(parts)

    def test_roles_are_shown_beside_how_often_they_carry_over(self, lab: Lab) -> None:
        found = run(lab, "player_value", view="roles", season="2025-26")
        summary = lab.value.role_summary("2025-26")
        assert found.status is OK and ROLES_ARE_RULES in found.warnings
        assert all(f"| {name} |" in found.text for name in summary["name"])

    def test_value_for_money_needs_the_users_contract_file(self, lab: Lab) -> None:
        found = run(lab, "player_value", view="value_for_money")
        assert found.status is UNAVAILABLE and "contract file" in found.text

    def test_value_for_money_reads_the_contract_file(self, contract_lab: Lab) -> None:
        found = run(contract_lab, "player_value", view="value_for_money")
        upcoming = contract_lab.value.status().upcoming
        money = contract_lab.value.for_money(upcoming)
        assert found.status is OK and money.basis == "projected"
        assert any(
            item.kind is EvidenceKind.CONTRACTS and item.effective_at for item in found.evidence
        )
        assert "not a market price" in found.text or money.market is None
        assert found.table is not None and len(found.table) == len(money.players)

    def test_the_model_card_gives_both_tests_and_the_simpler_methods(self, lab: Lab) -> None:
        found = run(lab, "player_value", view="model_evidence")
        card = lab.value.card()
        tested = card.model.validation
        assert found.status is OK
        assert f"typically off by {tested.net.rmse:.2f} points of net rating" in found.text
        assert "when the minutes are forecast too, as in a real forecast, by " in found.text
        assert f"{tested.projected.rmse:.2f}" in found.text
        assert all(f"| {label} |" in found.text for label in card.baselines["label"])
        (chart,) = found.charts
        assert (chart.kind, chart.reference) == ("intervals", 0.0)


class TestRosterFit:
    def test_a_profile_is_description_and_gives_no_score(self, lab: Lab) -> None:
        found = run(lab, "roster_fit", team_id=BOS)
        status = lab.fit.status()
        report = lab.fit.team(BOS, status.seasons[0])
        assert found.status is OK and not status.usable
        assert found.limits == (NO_FIT_SCORE,)
        assert "there is no fit score" in found.text and report.parts.correction is None
        assert all(f"| {name} |" in found.text for name in report.placed["name"])
        assert versions(found) >= {lab.fit.evidence().version, lab.value.model().version}
        assert found.charts[0].kind == "percentiles"
        assert found.charts[0].y_title == f"Percentile among the teams of {report.season}"

    def test_a_season_without_profiles_is_missing(self, lab: Lab) -> None:
        found = run(lab, "roster_fit", team_id=BOS, season="1990-91")
        assert found.status is EMPTY

    def test_a_profile_needs_a_team_or_a_roster(self, lab: Lab) -> None:
        assert run(lab, "roster_fit").status is ERROR

    def test_the_evidence_says_whether_anything_is_applied(self, lab: Lab) -> None:
        found = run(lab, "roster_fit", view="evidence")
        evidence = lab.fit.evidence()
        assert found.status is OK
        assert f"{evidence.team_seasons} team-seasons" in found.text
        assert "the lab adds nothing and gives no fit score" in found.text
        assert found.table is not None and len(found.table) == len(evidence.measures)

    def test_champions_are_history_not_a_requirement(self, lab: Lab) -> None:
        found = run(lab, "roster_fit", view="champions")
        assert found.status in (OK, EMPTY)
        if found.status is OK:
            assert "This is history, not a requirement." in found.text


class TestPostseason:
    def test_a_team_is_read_as_a_team_of_its_strength(self, lab: Lab) -> None:
        found = run(lab, "postseason_outlook", view="team", team_id=BOS, season="2025-26")
        subject = lab.postseason.team(BOS, "2025-26")
        title = subject.outlook.stages.set_index("key").loc["won_championship"]
        assert found.status is OK and built(found)
        assert (
            f"| Won the championship | {CHANCE(title['probability'])} | "
            f"{CHANCE(title['low'])} to {CHANCE(title['high'])} |"
        ) in found.text
        assert "What happened in 2025-26: Lost First Round." in found.text
        assert (
            "| Stage | Teams that got there | Model's score | Same chance for all |" in found.text
        )
        assert f"the average impact of its {len(subject.top_names)} best players" in found.text
        assert FIELD_NOT_MODELLED in found.warnings
        assert versions(found) == {lab.postseason.model().version}
        assert found.charts[0].kind == "intervals" and found.charts[0].y_range == (0.0, 1.0)
        shown = found.table.set_index("Stage")
        assert shown.at["Won the championship", "Chance"] == CHANCE(title["probability"])
        assert found.charts[0].frame["probability"].tolist() == (
            subject.outlook.stages["probability"].tolist()
        ), "the figures behind the page's percentages are in the chart"

    def test_a_strength_is_a_net_rating(self, lab: Lab) -> None:
        refused = run(lab, "postseason_outlook", view="strength")
        assert refused.status is ERROR and "net_rating" in refused.text
        assert "historical_benchmarks with measure wins_per_82" in refused.text
        found = run(lab, "postseason_outlook", view="strength", net_rating=5.0)
        outlook = lab.postseason.outlook(5.0)
        playoffs = outlook.stages.set_index("key").loc["made_playoffs", "probability"]
        assert found.status is OK and f"| Made the playoffs | {CHANCE(playoffs)} |" in found.text
        assert "the usual level for teams with that rating" in found.text

    def test_a_rating_with_no_team_is_a_team_of_that_strength(self, lab: Lab) -> None:
        """A4: a model asked the team view about "a team with a +5.0 net rating"."""
        asked = run(lab, "postseason_outlook", view="team", net_rating=5.0)
        strength = run(lab, "postseason_outlook", view="strength", net_rating=5.0)
        assert asked.status is OK and asked.text == strength.text
        refused = run(lab, "postseason_outlook", view="team")
        assert refused.status is ERROR and "strength view" in refused.text

    def test_the_season_ahead_is_drawn_by_the_simulator(self, lab: Lab) -> None:
        """A4: a model asked this view about 2026-27 and then only offered to simulate."""
        upcoming = lab.simulator.status().upcoming
        found = run(lab, "postseason_outlook", view="team", team_id=BOS, season=upcoming)
        drawn = run(lab, "simulate_scenario", subject="team", subject_id=BOS)
        assert found.status is OK
        assert found.text.startswith(f"{upcoming} has not been played yet, so these chances")
        assert found.text.endswith(drawn.text) and found.evidence == drawn.evidence
        later = run(lab, "postseason_outlook", view="team", team_id=BOS, season="2030-31")
        assert later.status is EMPTY and "simulate_scenario" in later.text
        played = run(lab, "postseason_outlook", view="team", team_id=BOS, season="1990-91")
        assert played.status is EMPTY and "simulate_scenario" not in played.text

    def test_a_season_whose_bracket_cannot_be_read_says_why(self, lab: Lab) -> None:
        found = run(lab, "postseason_outlook", view="bracket", season="2025-26")
        report = lab.postseason.bracket("2025-26")
        if report.is_empty:
            assert found.status is EMPTY and found.text == report.note
        else:
            assert found.status is OK and report.favourite in found.text

    def test_every_team_of_a_season_with_what_happened(self, lab: Lab) -> None:
        found = run(lab, "postseason_outlook", view="season_odds", season="2025-26")
        odds = lab.postseason.season_odds("2025-26")
        first = odds.iloc[0]
        assert found.status is OK
        assert found.text.splitlines()[3].startswith(f"| {first['team_name']} |")
        assert FIELD_NOT_MODELLED in found.warnings
        assert len(found.table) == len(odds), "the page has every team, the model the first rows"
        (chart,) = found.charts
        known = odds["p_won_championship"].notna().sum()
        assert chart.kind == "intervals" and len(chart.frame) == known

    def test_the_record_reads_the_model_both_ways(self, lab: Lab) -> None:
        found = run(lab, "postseason_outlook", view="model_record")
        evaluation = lab.postseason.model().evaluation
        assert found.status is OK
        assert f"Series: {evaluation.series.series} from" in found.text
        assert "'Pre-season' scores the model using only the rating forecast" in found.text
        clearly = [item for item in evaluation.season.comparisons if item.is_clearly_better]
        assert ("Left out on purpose, although they scored better" in found.text) == bool(clearly)

    def test_without_a_fitted_model_there_are_no_chances(
        self, lab: Lab, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(PostseasonService, "model", lambda self: None)
        found = run(lab, "postseason_outlook", view="strength", net_rating=3.0)
        assert found.status is UNAVAILABLE and "fol playoffs fit --write" in found.text


class TestScenario:
    def test_a_player_missing_games_is_drawn_before_and_after(self, lab: Lab) -> None:
        found = run(
            lab,
            "simulate_scenario",
            subject="team",
            subject_id=BOS,
            player_assumptions=[{"player_id": WHITE, "games_missed": 30}],
        )
        scenario = Scenario(
            subject=SubjectKind.TEAM,
            key=BOS,
            adjustments={WHITE: Adjustment(games_missed=30)},
            simulations=lab.simulator.default_scenario(SubjectKind.TEAM, BOS).simulations,
        )
        report = lab.simulator.run(scenario)
        level = f"{lab.simulator.model().spec.wins_interval:.0%}"
        assert found.status is OK
        assert "Derrick White misses 30 games" in found.text and not found.limits
        assert "| Figure | Before | After | Change |" in found.text
        assert f"{report.after.wins:.1f} ({level} interval {report.after.wins_low:.0f} to " in (
            found.text
        )
        assert f"the real win total fell inside the {level} interval" in found.text
        assert set(found.kinds) == {"modeled", "assumption"}
        assert versions(found) >= {lab.simulator.model().version, lab.value.model().version}
        assert FIELD_NOT_MODELLED in found.warnings
        (chart,) = found.charts
        assert (chart.kind, chart.y_range, set(chart.frame["side"])) == (
            "comparison",
            (0.0, 1.0),
            {"Before", "After"},
        )

    def test_a_team_as_it_stands_has_one_column(self, lab: Lab) -> None:
        found = run(lab, "simulate_scenario", subject="team", subject_id=NYK)
        assert found.status is OK and "| Figure | As it stands |" in found.text
        assert found.kinds == ("modeled",), "nothing is assumed of a team as it stands"

    def test_a_change_is_the_services_not_the_models_arithmetic(self, lab: Lab) -> None:
        """A4: a model worked out a change itself (+0.29) and had it cut."""
        found = run(
            lab,
            "simulate_scenario",
            subject="team",
            subject_id=NYK,
            add_player_ids=[WHITE],
            remove_player_ids=[HART],
        )
        scenario = Scenario(
            subject=SubjectKind.TEAM,
            key=NYK,
            added=(WHITE,),
            removed=(HART,),
            simulations=lab.simulator.default_scenario(SubjectKind.TEAM, NYK).simulations,
        )
        change = lab.simulator.run(scenario).comparison.set_index("key")["change"]
        assert "| Figure | Before | After | Change |" in found.text
        assert f"| {change['top_players']:+.2f} |" in found.text
        assert f"| {change['p_made_playoffs'] * 100:+.1f} points |" in found.text

    def test_a_change_to_a_player_not_on_the_roster_is_not_run(self, lab: Lab) -> None:
        """S01 asks about Jaylen Brown missing games for Boston; the fixture's 2026-27 rosters
        have him traded to Philadelphia. The user decided (2026-10-10) that a scenario for the
        season ahead takes each player's current team, so it is an error: nothing is run."""
        upcoming = lab.simulator.status().upcoming
        philadelphia = int(lab.simulator.pool().at[BROWN, "team_id"])
        found = run(
            lab,
            "simulate_scenario",
            subject="team",
            subject_id=BOS,
            player_assumptions=[{"player_id": BROWN, "games_missed": 30}],
        )
        assert found.status is EMPTY and found.text.startswith("Nothing was simulated.")
        assert f"Jaylen Brown is not on the Boston Celtics roster for {upcoming}." in found.text
        assert f"They are with the Philadelphia 76ers (team_id {philadelphia})." in found.text
        assert built(found) and not found.charts
        removed = run(
            lab, "simulate_scenario", subject="team", subject_id=NYK, remove_player_ids=[WHITE]
        )
        assert removed.status is EMPTY
        assert "Derrick White is not on the New York Knicks roster" in removed.text

    def test_an_inconsistent_scenario_is_refused(self, lab: Lab) -> None:
        both = run(
            lab,
            "simulate_scenario",
            subject="team",
            subject_id=NYK,
            add_player_ids=[HART],
            remove_player_ids=[HART],
        )
        assert both.status is ERROR and "does not hold together" in both.text
        twice = run(
            lab,
            "simulate_scenario",
            subject="team",
            subject_id=NYK,
            player_assumptions=[{"player_id": HART, "games_missed": 5}, {"player_id": HART}],
        )
        assert twice.status is ERROR

    def test_without_the_simulators_parameters_nothing_runs(
        self, lab: Lab, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(SimulatorService, "model", lambda self: None)
        found = run(lab, "simulate_scenario", subject="team", subject_id=BOS)
        assert found.status is UNAVAILABLE and "fol simulate fit --write" in found.text


class TestTheExecutor:
    def test_a_roster_the_lab_does_not_hold_is_refused(self, lab: Lab) -> None:
        executor = Executor(lab)
        for tool, arguments in (
            ("simulate_scenario", {"subject": "roster", "subject_id": 4321}),
            ("postseason_outlook", {"view": "roster", "roster_id": 4321}),
            ("roster_fit", {"roster_id": 4321}),
        ):
            result = executor.run(Call(tool, arguments, None))
            assert result.status is ERROR and "no saved roster with id 4321" in result.text

    def test_a_player_assumed_about_must_be_one_the_lab_holds(self, lab: Lab) -> None:
        result = Executor(lab).run(
            Call(
                "simulate_scenario",
                {
                    "subject": "team",
                    "subject_id": BOS,
                    "player_assumptions": [{"player_id": 99, "games_missed": 10}],
                },
                None,
            )
        )
        assert result.status is ERROR and "no player with id 99" in result.text


class TestDocuments:
    @pytest.fixture
    def documented(self, settings: Settings, project: Path) -> Lab:
        folder = project / "docs" / "decisions"
        folder.mkdir(parents=True)
        (folder / "0014-postseason-model.md").write_text(
            "# 0014 - The postseason model\n\n## What else was tried\n\nWinning percentage "
            "predicts better on seasons already played and is left out on purpose: the model "
            "is read for a roster before its season.\n",
            encoding="utf-8",
        )
        return Lab(settings)

    def test_a_section_is_quoted_and_cited_by_file_and_heading(self, documented: Lab) -> None:
        with documented as lab:
            found = run(lab, "research_docs", query="Why is winning percentage left out?")
        location = "docs/decisions/0014-postseason-model.md#what-else-was-tried"
        assert found.status is OK
        assert f"From {location}" in found.text and "left out on purpose" in found.text
        assert [(item.kind, item.location) for item in found.evidence] == [
            (EvidenceKind.DOCS, location)
        ]

    def test_nothing_matching_is_said_with_what_was_searched(self, documented: Lab) -> None:
        with documented as lab:
            found = run(lab, "research_docs", query="quokka zebra")
        assert found.status is EMPTY and "quokka, zebra" in found.text
        assert [item.location for item in found.evidence] == ["docs/"]

    def test_without_the_documents_there_is_nothing_to_search(self, settings: Settings) -> None:
        with Lab(settings) as lab:
            found = run(lab, "research_docs", query="anything at all")
        assert found.status is UNAVAILABLE
