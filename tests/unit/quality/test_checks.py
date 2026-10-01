"""Quality checks: each must pass on good data and fail when that data is broken.

The baseline is the normalised fixture store, which is real league data. Every test
takes a private copy, damages one thing, and asserts that the matching check - and only
a check that should care - reports it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.pipelines.normalize import NBA_STATS_TABLES
from front_office.quality import Check, Severity, all_checks, reference_checks, run_checks
from front_office.quality.checks import CHECKS, MAX_EXAMPLES

BOS, NYK = 1610612738, 1610612752

# The fixture keeps player logs only for players of two teams, so these two checks, which
# need every player of every team, cannot pass on it. They are tested on a complete
# subset below.
NEEDS_FULL_PLAYER_LOGS = {
    "player_game_logs.points_sum_to_team_points",
    "player_game_logs.logged_games_have_players",
}
# Real source glitches present in the fixture's 1996-97 season.
KNOWN_WARNINGS = {
    "team_games.points_add_up": 2,
    "team_seasons.ratings_are_consistent": 1,
}


def results(tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    return {result.check: result for result in run_checks(tables, all_checks(NBA_STATS_TABLES))}


def failures(tables: dict[str, pd.DataFrame], check: str) -> int:
    return results(tables)[check].failures


def first_index(frame: pd.DataFrame, **equals: object) -> int:
    mask = pd.Series(True, index=frame.index)
    for column, value in equals.items():
        mask &= frame[column] == value
    return frame.index[mask][0]


class TestBaseline:
    def test_real_data_passes_every_check_it_can(self, tables) -> None:
        for name, result in results(tables).items():
            if name in NEEDS_FULL_PLAYER_LOGS:
                continue
            assert result.failures == KNOWN_WARNINGS.get(name, 0), (name, result.examples)

    def test_known_source_glitches_are_warnings_not_errors(self, tables) -> None:
        found = results(tables)
        for name in KNOWN_WARNINGS:
            assert found[name].severity is Severity.WARNING
            assert not found[name].passed

    def test_every_check_examines_something(self, tables) -> None:
        for name, result in results(tables).items():
            assert result.examined > 0, name

    def test_check_names_are_unique_and_described(self) -> None:
        checks = all_checks(NBA_STATS_TABLES)
        names = [f"{check.table}.{check.name}" for check in checks]
        assert len(names) == len(set(names))
        assert all(check.description.endswith(".") for check in checks)

    def test_empty_tables_pass(self) -> None:
        empty = {contract.name: contract.empty_frame() for contract in NBA_STATS_TABLES}
        for result in run_checks(empty, all_checks(NBA_STATS_TABLES)):
            assert result.passed, result.check
            assert result.examined == 0

    def test_default_checks_are_the_cross_table_ones(self, tables) -> None:
        assert len(run_checks(tables)) == len(CHECKS)


class TestReferences:
    def test_an_unknown_player_is_reported(self, tables) -> None:
        seasons = tables["player_seasons"]
        seasons.loc[seasons.index[0], "player_id"] = 999999999
        result = results(tables)["player_seasons.player_id_exists"]
        assert result.failures == 1
        assert result.severity is Severity.ERROR
        assert "999999999" in result.examples[0]

    def test_an_unknown_team_is_reported(self, tables) -> None:
        games = tables["team_games"]
        games.loc[games.index[:3], "opponent_team_id"] = 42
        result = results(tables)["team_games.opponent_team_id_exists"]
        assert result.failures == 1  # one unknown team, however many rows use it
        assert "rows=3" in result.examples[0]

    def test_nulls_in_an_optional_reference_are_fine(self, tables) -> None:
        assert tables["players"]["current_team_id"].isna().any()
        assert failures(tables, "players.current_team_id_exists") == 0

    def test_references_outside_the_given_tables_are_skipped(self) -> None:
        lonely = TableContract(
            "lonely",
            "test",
            "A table pointing at one that is not being checked.",
            "One row.",
            (
                Field("id", DType.INTEGER, "Id.", nullable=False, provenance=Provenance.IDENTIFIER),
                Field("team_id", DType.INTEGER, "Team.", references="teams.team_id"),
            ),
            ("id",),
        )
        assert reference_checks([lonely]) == []

    def test_one_check_per_declared_reference(self) -> None:
        declared = sum(
            1 for contract in NBA_STATS_TABLES for field in contract.fields if field.references
        )
        assert len(reference_checks(NBA_STATS_TABLES)) == declared


class TestTeamGames:
    def test_a_missing_row_breaks_the_pair(self, tables) -> None:
        games = tables["team_games"]
        tables["team_games"] = games.drop(index=first_index(games, game_id="0022500001"))
        assert failures(tables, "team_games.games_are_paired") == 1

    def test_scores_must_mirror(self, tables) -> None:
        games = tables["team_games"]
        games.loc[first_index(games, game_id="0022500001"), "opp_pts"] += 1
        assert failures(tables, "team_games.games_are_paired") == 1

    def test_two_winners_is_a_contradiction(self, tables) -> None:
        games = tables["team_games"]
        rows = games.index[games["game_id"] == "0022500001"]
        games.loc[rows, "won"] = True
        assert failures(tables, "team_games.games_are_paired") == 2

    def test_two_home_teams_is_a_contradiction(self, tables) -> None:
        games = tables["team_games"]
        rows = games.index[games["game_id"] == "0022500001"]
        games.loc[rows, "is_home"] = True
        assert failures(tables, "team_games.games_are_paired") == 2

    def test_no_home_team_requires_a_neutral_site(self, tables) -> None:
        games = tables["team_games"]
        rows = games.index[games["game_id"] == "0022500001"]
        games.loc[rows, "is_home"] = False
        assert failures(tables, "team_games.games_are_paired") == 2
        games.loc[rows, "is_neutral_site"] = True
        assert failures(tables, "team_games.games_are_paired") == 0

    def test_rebounds_must_add_up(self, tables) -> None:
        games = tables["team_games"]
        games.loc[games.index[0], "reb"] += 1
        assert failures(tables, "team_games.box_scores_are_possible") == 1

    @pytest.mark.parametrize(
        ("made", "attempted"), [("fgm", "fga"), ("fg3m", "fg3a"), ("ftm", "fta")]
    )
    def test_makes_cannot_exceed_attempts(self, tables, made: str, attempted: str) -> None:
        games = tables["team_games"]
        games.loc[games.index[0], made] = games.loc[games.index[0], attempted] + 1
        assert failures(tables, "team_games.box_scores_are_possible") == 1

    def test_points_must_follow_from_shots(self, tables) -> None:
        games = tables["team_games"]
        row = first_index(games, game_id="0022500001")
        games.loc[row, "ftm"] += 1
        result = results(tables)["team_games.points_add_up"]
        assert result.failures == KNOWN_WARNINGS["team_games.points_add_up"] + 1

    def test_the_winner_must_have_scored_more(self, tables) -> None:
        games = tables["team_games"]
        rows = games.index[games["game_id"] == "0022500001"]
        games.loc[rows, "won"] = ~games.loc[rows, "won"].astype(bool)
        assert failures(tables, "team_games.results_match_scores") == 2

    def test_a_tie_is_reported(self, tables) -> None:
        games = tables["team_games"]
        rows = games.index[games["game_id"] == "0022500001"]
        games.loc[rows, ["pts", "opp_pts"]] = 100
        assert failures(tables, "team_games.results_match_scores") == 2

    @pytest.mark.parametrize("minutes", [239, 250, 0])
    def test_minutes_must_fit_a_game(self, tables, minutes: int) -> None:
        games = tables["team_games"]
        games.loc[games.index[0], "minutes"] = minutes
        assert failures(tables, "team_games.minutes_fit_game_length") == 1


class TestTeamSeasons:
    def test_a_wrong_win_total_is_caught(self, tables) -> None:
        seasons = tables["team_seasons"]
        row = first_index(seasons, season="2025-26", team_id=BOS)
        seasons.loc[row, "wins"] += 1
        seasons.loc[row, "losses"] -= 1
        result = results(tables)["team_seasons.records_match_games"]
        assert result.failures == 1
        assert f"team_id={BOS}" in result.examples[0]
        assert "wins_in_logs=56" in result.examples[0]

    def test_games_must_equal_wins_plus_losses(self, tables) -> None:
        seasons = tables["team_seasons"]
        seasons.loc[first_index(seasons, season="2025-26", team_id=BOS), "games_played"] = 80
        assert failures(tables, "team_seasons.records_match_games") == 1

    def test_a_dropped_game_is_caught(self, tables) -> None:
        games = tables["team_games"]
        tables["team_games"] = games[games["game_id"] != "0022500001"]
        assert failures(tables, "team_seasons.records_match_games") == 2

    def test_small_stat_corrections_are_tolerated(self, tables) -> None:
        seasons = tables["team_seasons"]
        seasons.loc[first_index(seasons, season="2025-26", team_id=BOS), "tov"] += 5
        assert failures(tables, "team_seasons.totals_close_to_games") == 0

    def test_a_large_gap_from_the_game_logs_is_reported(self, tables) -> None:
        seasons = tables["team_seasons"]
        seasons.loc[first_index(seasons, season="2025-26", team_id=BOS), "pts"] += 500
        result = results(tables)["team_seasons.totals_close_to_games"]
        assert result.failures == 1
        assert result.severity is Severity.WARNING
        assert "stat=pts" in result.examples[0]

    def test_wins_and_losses_must_balance_across_the_league(self, tables) -> None:
        seasons = tables["team_seasons"]
        seasons.loc[first_index(seasons, season="2025-26", team_id=BOS), "wins"] += 1
        result = results(tables)["team_seasons.league_is_balanced"]
        assert result.failures == 1
        assert "season=2025-26" in result.examples[0]

    def test_points_must_balance_across_the_league(self, tables) -> None:
        seasons = tables["team_seasons"]
        seasons.loc[first_index(seasons, season="2012-13", team_id=BOS), "opp_pts"] += 7
        assert failures(tables, "team_seasons.league_is_balanced") == 1

    def test_a_rating_that_disagrees_with_the_totals_is_reported(self, tables) -> None:
        seasons = tables["team_seasons"]
        seasons.loc[first_index(seasons, season="2025-26", team_id=BOS), "off_rating"] += 3
        expected = KNOWN_WARNINGS["team_seasons.ratings_are_consistent"] + 1
        assert failures(tables, "team_seasons.ratings_are_consistent") == expected

    def test_two_champions_is_a_contradiction(self, tables) -> None:
        seasons = tables["team_seasons"]
        seasons.loc[first_index(seasons, season="2025-26", team_id=BOS), "won_championship"] = True
        result = results(tables)["team_seasons.outcomes_form_a_postseason"]
        assert result.failures == 1
        assert "champions=2" in result.examples[0]

    def test_unfinished_seasons_are_not_judged(self, tables) -> None:
        seasons = tables["team_seasons"]
        outcome_columns = [c for c in seasons if c.startswith(("made_", "playoff_", "won_"))]
        seasons.loc[seasons["season"] == "2025-26", outcome_columns] = pd.NA
        result = results(tables)["team_seasons.outcomes_form_a_postseason"]
        assert result.passed
        assert result.examined == 2  # the two seasons that still have outcomes


class TestPlayoffs:
    def test_a_missing_series_breaks_the_bracket(self, tables) -> None:
        series = tables["playoff_results"]
        drop = series.index[(series["season"] == "2025-26") & (series["round"] == 1)][0]
        tables["playoff_results"] = series.drop(index=drop)
        result = results(tables)["playoff_results.brackets_are_complete"]
        assert result.failures == 1
        assert "round_1=7" in result.examples[0]

    def test_an_undecided_series_in_a_finished_postseason_is_reported(self, tables) -> None:
        series = tables["playoff_results"]
        row = series.index[(series["season"] == "2025-26") & (series["round"] == 2)][0]
        series.loc[row, "is_complete"] = False
        assert failures(tables, "playoff_results.brackets_are_complete") == 1

    def test_a_postseason_in_progress_is_not_judged(self, tables) -> None:
        series = tables["playoff_results"]
        tables["playoff_results"] = series[(series["season"] != "2025-26") | (series["round"] < 3)]
        result = results(tables)["playoff_results.brackets_are_complete"]
        assert result.passed
        assert result.examined == 2

    def test_a_loser_cannot_advance(self, tables) -> None:
        series = tables["playoff_results"]
        row = series.index[(series["season"] == "2025-26") & (series["round"] == 1)][0]
        winner, loser = series.loc[row, "winner_team_id"], series.loc[row, "loser_team_id"]
        series.loc[row, ["winner_team_id", "loser_team_id"]] = [loser, winner]
        result = results(tables)["playoff_results.winners_advance"]
        assert result.failures >= 1
        assert "round=2" in result.examples[0]


class TestPlayers:
    def test_games_played_must_match_the_log(self, tables) -> None:
        seasons = tables["player_seasons"]
        seasons.loc[seasons.index[0], "games_played"] += 1
        result = results(tables)["player_seasons.games_and_points_match_logs"]
        assert result.failures == 1
        assert "games_in_logs=" in result.examples[0]

    def test_points_must_match_the_log(self, tables) -> None:
        logs = tables["player_game_logs"]
        logs.loc[logs.index[0], "pts"] += 2
        assert failures(tables, "player_seasons.games_and_points_match_logs") == 1

    def test_a_missing_log_row_is_caught(self, tables) -> None:
        logs = tables["player_game_logs"]
        tables["player_game_logs"] = logs.drop(index=logs.index[0])
        assert failures(tables, "player_seasons.games_and_points_match_logs") == 1

    def test_minutes_within_rounding_pass(self, tables) -> None:
        seasons = tables["player_seasons"]
        row = seasons.index[seasons["games_played"] >= 20][0]
        seasons.loc[row, "minutes"] += 5
        assert failures(tables, "player_seasons.minutes_close_to_logs") == 0

    def test_minutes_far_from_the_log_are_reported(self, tables) -> None:
        seasons = tables["player_seasons"]
        row = seasons.index[seasons["games_played"] >= 20][0]
        seasons.loc[row, "minutes"] += 500
        result = results(tables)["player_seasons.minutes_close_to_logs"]
        assert result.failures == 1
        assert result.severity is Severity.WARNING

    def test_more_starts_than_games_is_impossible(self, tables) -> None:
        seasons = tables["player_seasons"]
        seasons.loc[seasons.index[0], "games_started"] = (
            seasons.loc[seasons.index[0], "games_played"] + 1
        )
        assert failures(tables, "player_seasons.starts_within_games") == 1

    def test_unknown_starts_are_not_judged(self, tables) -> None:
        seasons = tables["player_seasons"]
        seasons["games_started"] = pd.array([pd.NA] * len(seasons), dtype="Int64")
        result = results(tables)["player_seasons.starts_within_games"]
        assert result.passed and result.examined == 0


class TestPlayerLogsAgainstTeamGames:
    """The two checks that need complete player logs, run on the two complete teams."""

    @pytest.fixture
    def complete(self, tables) -> dict[str, pd.DataFrame]:
        logs = tables["player_game_logs"]
        games = tables["team_games"]
        tables["player_game_logs"] = logs[logs["team_id"].isin([BOS, NYK])]
        tables["team_games"] = games[
            games["team_id"].isin([BOS, NYK])
            & (games["season"] == "2025-26")
            & games["season_type"].isin(["regular", "playoffs"])
        ]
        return tables

    def test_complete_teams_pass(self, complete) -> None:
        found = results(complete)
        for name in NEEDS_FULL_PLAYER_LOGS:
            assert found[name].passed, (name, found[name].examples)
        # Boston: 82 regular-season games and a 7-game series. New York: 82 and 19.
        assert found["player_game_logs.points_sum_to_team_points"].examined == 82 + 7 + 82 + 19

    def test_player_points_must_sum_to_the_team_score(self, complete) -> None:
        logs = complete["player_game_logs"]
        logs.loc[logs.index[0], "pts"] += 1
        result = results(complete)["player_game_logs.points_sum_to_team_points"]
        assert result.failures == 1
        assert "player_pts=" in result.examples[0]

    def test_a_team_game_without_player_rows_is_reported(self, complete) -> None:
        logs = complete["player_game_logs"]
        game = logs["game_id"].iloc[0]
        team = logs["team_id"].iloc[0]
        complete["player_game_logs"] = logs[
            ~((logs["game_id"] == game) & (logs["team_id"] == team))
        ]
        assert failures(complete, "player_game_logs.logged_games_have_players") == 1

    def test_play_in_games_are_not_expected_to_have_player_rows(self, tables) -> None:
        logs, games = tables["player_game_logs"], tables["team_games"]
        tables["player_game_logs"] = logs[logs["team_id"].isin([BOS, NYK])]
        tables["team_games"] = games[
            games["team_id"].isin([BOS, NYK]) & (games["season"] == "2025-26")
        ]
        assert failures(tables, "player_game_logs.logged_games_have_players") == 0


class TestReporting:
    def test_examples_are_capped(self, tables) -> None:
        games = tables["team_games"]
        games["reb"] = games["reb"] + 1
        result = results(tables)["team_games.box_scores_are_possible"]
        assert result.failures == len(games)
        assert len(result.examples) == MAX_EXAMPLES

    def test_a_passing_check_has_no_examples(self, tables) -> None:
        result = results(tables)["team_games.games_are_paired"]
        assert result.passed and result.examples == ()

    def test_values_are_rendered_readably(self) -> None:
        def run(_: dict) -> tuple[int, pd.DataFrame]:
            frame = pd.DataFrame(
                {"day": [pd.Timestamp("2025-10-21")], "rating": [115.04999], "team": [BOS]}
            )
            return 1, frame

        check = Check("demo", "team_games", "Demo.", Severity.WARNING, run)
        result = check.evaluate({})
        assert result.check == "team_games.demo"
        assert result.examples == (f"day=2025-10-21, rating=115.05, team={BOS}",)
