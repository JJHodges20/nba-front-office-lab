"""The read tools against the fixture build: what they show, what they say is missing,
and where they say it came from. Figures are compared with the services' own."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import HANDLERS, grid, ordinal, shown
from front_office.domain.assistant import EvidenceKind, ResultStatus
from front_office.services import Lab
from tests.helpers import BOS, BROWN, BRUNSON, NYK, TATUM

OK, EMPTY, UNAVAILABLE = ResultStatus.OK, ResultStatus.EMPTY, ResultStatus.UNAVAILABLE


def run(lab: Lab, tool: str, **arguments):  # type: ignore[no-untyped-def]
    spec = next(spec for spec in t.REGISTRY if spec.name == tool)
    return HANDLERS[tool](lab, spec.args(**arguments))


class TestFormatting:
    @pytest.mark.parametrize(
        ("n", "text"),
        [
            (1, "1st"),
            (2, "2nd"),
            (3, "3rd"),
            (4, "4th"),
            (11, "11th"),
            (12, "12th"),
            (13, "13th"),
            (21, "21st"),
            (22, "22nd"),
            (101, "101st"),
        ],
    )
    def test_ordinals(self, n: int, text: str) -> None:
        assert ordinal(n) == text

    def test_missing_is_a_dash(self) -> None:
        assert shown(None, "anything", None) == "—"
        assert shown(None, "anything", float("nan")) == "—"

    def test_a_long_table_says_what_it_left_out(self) -> None:
        text = grid(["A"], [[str(i)] for i in range(15)], limit=12)
        assert text.splitlines()[-1] == "(and 3 more rows on the page)"


class TestTeams:
    def test_a_season_with_ranks_and_the_source(self, lab: Lab) -> None:
        found = run(lab, "team_stats", team_id=BOS, season="2025-26")
        table = lab.teams.table("2025-26")
        assert found.status is OK
        assert (
            f"| Net rating | {table.metrics['net_rating'].format_value(table.teams.at[BOS, 'net_rating'])} | 4th of 30 |"
            in found.text
        )
        assert "2nd in the East" in found.text and "Lost First Round" in found.text
        (source,) = found.evidence
        assert (
            source.kind is EvidenceKind.LAB and "NBA.com" in source.label and source.build_id == 1
        )

    def test_a_span_of_games_is_marked_as_an_estimate(self, lab: Lab) -> None:
        found = run(lab, "team_stats", team_id=BOS, season="2025-26", last_games=10)
        assert "| ≈ Net rating | ≈ " in found.text
        assert "estimate" in found.kinds and found.warnings

    def test_a_season_not_held_says_what_is(self, lab: Lab) -> None:
        found = run(lab, "team_stats", team_id=BOS, season="1989-90")
        assert found.status is EMPTY
        assert (
            found.text
            == "The lab holds team statistics for 1996-97, 2012-13, 2025-26; nothing for 1989-90."
        )

    def test_history_games_form_and_rotation(self, lab: Lab) -> None:
        assert (
            run(lab, "team_stats", team_id=BOS, season="2025-26", view="history").text.count("| 2")
            >= 3
        )
        games = run(lab, "team_stats", team_id=NYK, season="2025-26", view="games")
        assert games.status is OK and len(games.table) == len(lab.teams.game_log(NYK, "2025-26"))
        form = run(lab, "team_stats", team_id=NYK, season="2025-26", view="form", last_games=5)
        assert form.status is OK and "Over the 5 games to" in form.text
        rotation = run(lab, "team_stats", team_id=NYK, season="2025-26", view="rotation")
        assert "Jalen Brunson" in rotation.text


class TestPlayers:
    def test_a_season_with_percentiles(self, lab: Lab) -> None:
        found = run(lab, "player_stats", player_id=BROWN, season="2025-26")
        assert found.status is OK
        assert "| Points per game | 28.7 | 99th percentile |" in found.text
        assert "| True shooting percentage | 57.3% |" in found.text

    def test_a_season_not_held(self, lab: Lab) -> None:
        found = run(lab, "player_stats", player_id=BROWN, season="2012-13")
        assert found.status is EMPTY and "nothing for 2012-13" in found.text

    def test_career_games_and_form(self, lab: Lab) -> None:
        assert (
            run(lab, "player_stats", player_id=BROWN, season="2025-26", view="career").status is OK
        )
        games = run(lab, "player_stats", player_id=BRUNSON, season="2025-26", view="games")
        assert games.text.startswith("74 games, newest first.")
        assert (
            run(
                lab, "player_stats", player_id=TATUM, season="2025-26", view="form", last_games=20
            ).status
            is EMPTY
        )

    def test_a_comparison(self, lab: Lab) -> None:
        found = run(
            lab,
            "compare_players",
            player_ids=[BRUNSON, BROWN],
            season="2025-26",
            metrics=["pts_per_game", "not_a_metric"],
        )
        assert "| Points per game | 26.0 (96th pct.) | 28.7 (99th pct.) |" in found.text
        assert found.warnings == ("Not metrics the lab has: not_a_metric.",)


class TestLeague:
    def test_champions(self, lab: Lab) -> None:
        found = run(lab, "league_context", view="champions")
        assert (
            "| 2025-26 | New York Knicks | San Antonio Spurs | 4-1 | 53-29 | +6.4 | 5th of 30 |"
            in found.text
        )

    def test_standings_and_ranks(self, lab: Lab) -> None:
        standings = run(lab, "league_context", view="standings", season="2025-26")
        assert "| East | 1st | Detroit Pistons | 60-22 |" in standings.text
        ranks = run(lab, "league_context", view="team_ranks", season="2025-26")
        assert len(ranks.table) == 30

    def test_benchmarks_are_frequencies(self, lab: Lab) -> None:
        found = run(lab, "historical_benchmarks", stage="won_championship", measure="wins_per_82")
        assert "| 55 to 60 | 10 | 0 | 0.0% | 0.0% to 27.8% |" in found.text
        assert "not any team's chance" in found.text and found.kinds == ("derived",)

    def test_an_unknown_era_is_refused_with_the_known_ones(self, lab: Lab) -> None:
        found = run(lab, "historical_benchmarks", stage="won_championship", era="golden_age")
        assert found.status is ResultStatus.ERROR and "the eras are all" in found.text

    def test_a_metric_by_name(self, lab: Lab) -> None:
        found = run(lab, "metric_definition", metric="true shooting")
        assert "| True shooting percentage | ts_pct |" in found.text


class TestContracts:
    def test_without_a_contract_file(self, lab: Lab) -> None:
        assert run(lab, "contract_info", view="player", player_id=TATUM).status is UNAVAILABLE

    def test_a_players_salary_by_season(self, contract_lab: Lab) -> None:
        found = run(contract_lab, "contract_info", view="player", player_id=TATUM)
        assert "| 2026-27 | $40,000,000 | 24.2% |" in found.text
        (source,) = found.evidence
        assert source.kind is EvidenceKind.CONTRACTS and "as of 2026-10-01" in source.label

    def test_a_teams_payroll(self, contract_lab: Lab) -> None:
        found = run(contract_lab, "contract_info", view="team", team_id=NYK, season="2026-27")
        assert "| Team salary | $212,000,000 |" in found.text
        assert "| Highest line exceeded | first_apron |" in found.text
        # Above a line the service's room is negative; it is said as the amount over.
        assert "| Over the first apron by | $2,985,000 |" in found.text
        assert "| Room under the second apron | $9,686,000 |" in found.text
        assert "$-" not in found.text

    def test_a_season_the_file_does_not_list(self, contract_lab: Lab) -> None:
        found = run(contract_lab, "contract_info", view="team", team_id=BOS, season="2023-24")
        assert found.status is EMPTY and "nothing for 2023-24" in found.text
        (source,) = found.evidence
        assert source.kind is EvidenceKind.CONTRACTS, "what the file lacks is said of the file"


class TestTheLab:
    def test_what_it_holds(self, lab: Lab) -> None:
        found = run(lab, "data_status")
        assert "| Data build | 1, finished 2026-10-01 12:00 UTC |" in found.text
        assert "| Player value model | revision 2," in found.text
        assert "| Current injuries (since the build) | never fetched |" in found.text

    def test_names(self, lab: Lab) -> None:
        found = run(lab, "resolve_entities", text="Brown")
        assert set(found.table["id"]) == {BROWN, 1628971}
        assert found.text.endswith("Several readings: ask the user which is meant.")
        assert isinstance(found.table, pd.DataFrame)
