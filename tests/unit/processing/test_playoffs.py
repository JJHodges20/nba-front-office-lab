"""Playoff bracket derivation, tested against real postseasons and hand-built ones."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.domain.datasets import NbaStatsDataset
from front_office.domain.schema import conform_frame, validate_frame
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.tables.teams import PLAYOFF_RESULTS, TEAM_GAMES
from front_office.processing.nba_stats import playoffs, teams

D = NbaStatsDataset
REGULAR, PLAYOFFS = SeasonType.REGULAR, SeasonType.PLAYOFFS
S1996, S2012, S2025 = Season(1996), Season(2012), Season(2025)

BULLS, JAZZ, HEAT, SPURS, KNICKS, HAWKS = (
    1610612741,
    1610612762,
    1610612748,
    1610612759,
    1610612752,
    1610612737,
)


def real_series(raw, season: Season) -> pd.DataFrame:
    games = teams.build_team_games([raw(D.TEAM_GAME_LOGS, season, PLAYOFFS)])
    return playoffs.build_playoff_results(season, games)


class TestBestOf:
    @pytest.mark.parametrize(
        ("season", "playoff_round", "length"),
        [
            (1996, 1, 5),
            (2001, 1, 5),  # the last best-of-five first round
            (2002, 1, 7),
            (2025, 1, 7),
            (1996, 2, 7),
            (2001, 4, 7),
        ],
    )
    def test_series_length(self, season: int, playoff_round: int, length: int) -> None:
        assert playoffs.best_of(Season(season), playoff_round) == length


class TestRealBrackets:
    @pytest.mark.parametrize("season", [S1996, S2012, S2025])
    def test_a_full_bracket_has_fifteen_decided_series(self, raw, season: Season) -> None:
        series = real_series(raw, season)
        assert validate_frame(series, PLAYOFF_RESULTS) == []
        assert series.groupby("round").size().to_dict() == {1: 8, 2: 4, 3: 2, 4: 1}
        assert series["is_complete"].all()
        assert series["series_id"].is_unique

    def test_1997_finals(self, raw) -> None:
        finals = real_series(raw, S1996).query("round == 4").iloc[0]
        assert finals["round_name"] == "NBA Finals"
        assert (finals["winner_team_id"], finals["loser_team_id"]) == (BULLS, JAZZ)
        assert sorted([finals["team_a_wins"], finals["team_b_wins"]]) == [2, 4]
        assert finals["games_played"] == 6
        assert finals["team_a_id"] == BULLS  # Chicago hosted game 1

    def test_2013_finals_went_seven_games(self, raw) -> None:
        finals = real_series(raw, S2012).query("round == 4").iloc[0]
        assert (finals["winner_team_id"], finals["loser_team_id"]) == (HEAT, SPURS)
        assert (finals["team_a_wins"], finals["team_b_wins"], finals["games_played"]) == (4, 3, 7)

    def test_first_rounds_were_best_of_five_in_1997(self, raw) -> None:
        series = real_series(raw, S1996)
        first_round = series[series["round"] == 1]
        assert (first_round["best_of"] == 5).all()
        assert (first_round[["team_a_wins", "team_b_wins"]].max(axis=1) == 3).all()
        assert (series.loc[series["round"] > 1, "best_of"] == 7).all()

    def test_series_ids_and_dates(self, raw) -> None:
        series = real_series(raw, S2025)
        first = series[series["series_id"] == f"2025-26-R1-{HAWKS}-{KNICKS}"].iloc[0]
        assert first["team_a_id"] == KNICKS  # New York hosted game 1
        assert (first["team_a_wins"], first["team_b_wins"]) == (4, 2)
        assert first["start_date"] == pd.Timestamp("2026-04-18")
        assert first["end_date"] == pd.Timestamp("2026-04-30")
        assert (series["start_date"] <= series["end_date"]).all()

    def test_rounds_agree_with_the_round_encoded_in_modern_game_ids(self, raw) -> None:
        """Since 2001-02 the eighth digit of a playoff game id is its round."""
        for season in (S2012, S2025):
            games = teams.build_team_games([raw(D.TEAM_GAME_LOGS, season, PLAYOFFS)])
            series = playoffs.build_playoff_results(season, games)
            round_of = {}
            for row in series.itertuples():
                round_of[frozenset((row.team_a_id, row.team_b_id))] = row.round
            for game in games.itertuples():
                derived = round_of[frozenset((game.team_id, game.opponent_team_id))]
                assert derived == int(game.game_id[7]), game.game_id

    def test_winners_advance(self, raw) -> None:
        series = real_series(raw, S2025)
        for playoff_round in (2, 3, 4):
            entrants = set(series.loc[series["round"] == playoff_round, "team_a_id"]) | set(
                series.loc[series["round"] == playoff_round, "team_b_id"]
            )
            winners = set(series.loc[series["round"] == playoff_round - 1, "winner_team_id"])
            assert entrants == winners


class TestOutcomes:
    def test_champion_and_finalist(self, raw) -> None:
        series = real_series(raw, S2025)
        regular = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2025, REGULAR)])
        outcomes = playoffs.postseason_outcomes(series, regular["team_id"].unique())
        assert outcomes is not None
        assert len(outcomes) == 30
        by_team = outcomes.set_index("team_id")
        knicks, spurs, hawks = by_team.loc[KNICKS], by_team.loc[SPURS], by_team.loc[HAWKS]
        assert bool(knicks["won_championship"])
        assert (knicks["playoff_round_reached"], knicks["playoff_series_won"]) == (4, 4)
        assert (knicks["playoff_wins"], knicks["playoff_losses"]) == (16, 3)
        assert bool(spurs["made_finals"]) and not bool(spurs["won_championship"])
        assert spurs["playoff_series_won"] == 3
        assert (hawks["playoff_round_reached"], hawks["playoff_wins"], hawks["playoff_losses"]) == (
            1,
            2,
            4,
        )
        assert not bool(hawks["made_conference_finals"])

    def test_totals_across_the_league(self, raw) -> None:
        series = real_series(raw, S2025)
        regular = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2025, REGULAR)])
        outcomes = playoffs.postseason_outcomes(series, regular["team_id"].unique())
        assert int(outcomes["made_playoffs"].sum()) == 16
        assert int(outcomes["made_conference_finals"].sum()) == 4
        assert int(outcomes["made_finals"].sum()) == 2
        assert int(outcomes["won_championship"].sum()) == 1
        assert outcomes["playoff_wins"].sum() == outcomes["playoff_losses"].sum()
        missed = outcomes[~outcomes["made_playoffs"]]
        assert (missed["playoff_round_reached"] == 0).all()
        assert (missed[["playoff_wins", "playoff_losses", "playoff_series_won"]] == 0).all().all()

    def test_play_in_teams_are_flagged(self, raw) -> None:
        series = real_series(raw, S2025)
        outcomes = playoffs.postseason_outcomes(series, [KNICKS, HAWKS, 1610612748], [1610612748])
        flags = outcomes.set_index("team_id")["made_play_in"]
        assert bool(flags[1610612748])
        assert not bool(flags[KNICKS])


def games(*results: tuple[str, str, int, int, bool | None]) -> pd.DataFrame:
    """Hand-built playoff games: (game_id, date, home team, away team, home team won)."""
    rows = []
    for game_id, day, home, away, home_won in results:
        for team, opponent, is_home in ((home, away, True), (away, home, False)):
            won = None if home_won is None else (home_won if is_home else not home_won)
            row = {
                "game_id": game_id,
                "team_id": team,
                "season": "2025-26",
                "season_type": "playoffs",
                "game_date": day,
                "opponent_team_id": opponent,
                "is_home": is_home,
                "is_neutral_site": False,
                "won": won,
                "minutes": 240,
                "opp_pts": 100,
            }
            row.update({column: 0 for column in TEAM_GAMES.column_names if column not in row})
            row["pts"] = 101 if won else 99
            rows.append(row)
    frame = pd.DataFrame(rows, columns=list(TEAM_GAMES.column_names))
    frame["won"] = frame["won"].astype("boolean")
    return conform_frame(frame, TEAM_GAMES)


def sweep(prefix: str, start_day: int, home: int, away: int, wins: int = 4) -> list[tuple]:
    return [
        (f"{prefix}{number}", f"2026-05-{start_day + number:02d}", home, away, True)
        for number in range(1, wins + 1)
    ]


class TestBracketLogic:
    def test_no_playoff_games_gives_an_empty_table(self) -> None:
        empty = TEAM_GAMES.empty_frame()
        series = playoffs.build_playoff_results(S2025, empty)
        assert len(series) == 0
        assert tuple(series.columns) == PLAYOFF_RESULTS.column_names
        assert playoffs.postseason_outcomes(series, [1, 2]) is None

    def test_other_seasons_and_phases_are_ignored(self, raw) -> None:
        regular = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2025, REGULAR)])
        assert len(playoffs.build_playoff_results(S2025, regular)) == 0
        playoff_games = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2012, PLAYOFFS)])
        assert len(playoffs.build_playoff_results(S2025, playoff_games)) == 0

    def test_an_unfinished_series_has_no_winner(self) -> None:
        series = playoffs.build_playoff_results(S2025, games(*sweep("A", 1, 1, 2, wins=3)))
        row = series.iloc[0]
        assert not bool(row["is_complete"])
        assert pd.isna(row["winner_team_id"]) and pd.isna(row["loser_team_id"])
        assert (row["team_a_wins"], row["team_b_wins"], row["games_played"]) == (3, 0, 3)

    def test_a_game_in_progress_counts_as_played_but_not_won(self) -> None:
        results = [*sweep("A", 1, 1, 2, wins=2), ("A9", "2026-05-09", 2, 1, None)]
        row = playoffs.build_playoff_results(S2025, games(*results)).iloc[0]
        assert (row["team_a_wins"], row["team_b_wins"], row["games_played"]) == (2, 0, 3)
        assert row["end_date"] == pd.Timestamp("2026-05-09")

    def test_road_wins_are_credited_to_the_right_team(self) -> None:
        results = [
            ("A1", "2026-05-01", 1, 2, False),  # team 2 wins on the road
            ("A2", "2026-05-02", 1, 2, True),
            ("A3", "2026-05-03", 2, 1, True),  # team 2 wins at home
            ("A4", "2026-05-04", 2, 1, False),  # team 1 wins on the road
        ]
        row = playoffs.build_playoff_results(S2025, games(*results)).iloc[0]
        assert (row["team_a_id"], row["team_b_id"]) == (1, 2)
        assert (row["team_a_wins"], row["team_b_wins"]) == (2, 2)

    def test_outcomes_are_withheld_until_the_finals_are_decided(self) -> None:
        first_round = games(*sweep("A", 1, 1, 2), *sweep("B", 1, 3, 4))
        series = playoffs.build_playoff_results(S2025, first_round)
        assert series["is_complete"].all()
        assert not playoffs.postseason_is_complete(series)
        assert playoffs.postseason_outcomes(series, [1, 2, 3, 4]) is None

    def test_a_team_cannot_be_in_two_rounds_at_once(self) -> None:
        # Team 1 finishes a series, then meets team 3, who has not played a first round.
        results = [*sweep("A", 1, 1, 2), *sweep("B", 10, 1, 3)]
        with pytest.raises(playoffs.BracketError, match="inconsistent rounds"):
            playoffs.build_playoff_results(S2025, games(*results))

    def test_more_wins_than_a_series_allows_is_an_error(self) -> None:
        with pytest.raises(playoffs.BracketError, match="5 wins for one team in a best-of-7"):
            playoffs.build_playoff_results(S2025, games(*sweep("A", 1, 1, 2, wins=5)))

    def test_a_neutral_site_game_still_belongs_to_its_series(self) -> None:
        frame = games(*sweep("A", 1, 1, 2))
        frame.loc[frame["game_id"] == "A2", ["is_home", "is_neutral_site"]] = [False, True]
        row = playoffs.build_playoff_results(S2025, frame).iloc[0]
        assert (row["team_a_wins"], row["games_played"], bool(row["is_complete"])) == (4, 4, True)
