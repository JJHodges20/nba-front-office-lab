"""Team normalisers, tested against real responses in the fixture store."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.domain.datasets import NbaStatsDataset
from front_office.domain.schema import validate_frame
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.tables.teams import TEAM_GAMES, TEAM_SEASONS, TEAMS
from front_office.processing.nba_stats import teams
from front_office.processing.nba_stats.resultsets import PayloadError
from tests.helpers import snapshot, stats_payload

D = NbaStatsDataset
REGULAR, PLAYOFFS, PLAY_IN = SeasonType.REGULAR, SeasonType.PLAYOFFS, SeasonType.PLAY_IN
S1996, S2012, S2025, S2026 = Season(1996), Season(2012), Season(2025), Season(2026)

BOS, NYK, ATL, OKC, HOU, SAC, IND = (
    1610612738,
    1610612752,
    1610612737,
    1610612760,
    1610612745,
    1610612758,
    1610612754,
)


class TestBuildTeams:
    def test_thirty_current_franchises(self, raw) -> None:
        frame = teams.build_teams(raw(D.TEAM_YEARS), raw(D.STANDINGS, S2025))
        assert len(frame) == 30
        assert validate_frame(frame, TEAMS) == []
        assert frame["team_id"].is_monotonic_increasing
        assert set(frame["conference"]) == {"East", "West"}
        assert frame.groupby("conference").size().tolist() == [15, 15]
        assert frame["division"].nunique() == 6

    def test_identity_fields(self, raw) -> None:
        frame = teams.build_teams(raw(D.TEAM_YEARS), raw(D.STANDINGS, S2025)).set_index("team_id")
        boston = frame.loc[BOS]
        assert (boston["abbreviation"], boston["city"], boston["nickname"]) == (
            "BOS",
            "Boston",
            "Celtics",
        )
        assert boston["full_name"] == "Boston Celtics"
        assert (boston["conference"], boston["division"]) == ("East", "Atlantic")
        assert boston["first_season_year"] == 1946
        assert frame.loc[1610612746, "full_name"] == "LA Clippers"

    def test_a_relocated_franchise_keeps_its_id(self, raw) -> None:
        frame = teams.build_teams(raw(D.TEAM_YEARS), raw(D.STANDINGS, S2025)).set_index("team_id")
        # Seattle's franchise is today's Thunder; its history starts in 1967.
        assert frame.loc[OKC, "full_name"] == "Oklahoma City Thunder"
        assert frame.loc[OKC, "first_season_year"] == 1967


def game_log(rows: list[list], season: str = "2025-26", season_type: str = "regular"):
    headers = [
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "GAME_ID",
        "GAME_DATE",
        "MATCHUP",
        "WL",
        "MIN",
        "FGM",
        "FGA",
        "FG3M",
        "FG3A",
        "FTM",
        "FTA",
        "OREB",
        "DREB",
        "REB",
        "AST",
        "STL",
        "BLK",
        "TOV",
        "PF",
        "PTS",
    ]
    return snapshot(
        "team_game_logs",
        stats_payload(headers, rows),
        {"season": season, "season_type": season_type},
    )


def game_row(team_id: int, abbreviation: str, matchup: str, result, pts: int, minutes: int = 240):
    return [
        team_id, abbreviation, "0022500999", "2025-12-25", matchup, result, minutes,
        40, 85, 10, 30, 10, 12, 8, 32, 40, 22, 7, 5, 12, 20, pts,
    ]  # fmt: skip


class TestBuildTeamGames:
    def test_real_season_conforms_and_has_two_rows_per_game(self, raw) -> None:
        frame = teams.build_team_games(
            [
                raw(D.TEAM_GAME_LOGS, S2025, REGULAR),
                raw(D.TEAM_GAME_LOGS, S2025, PLAYOFFS),
                raw(D.TEAM_GAME_LOGS, S2025, PLAY_IN),
            ]
        )
        assert validate_frame(frame, TEAM_GAMES) == []
        assert frame.groupby("season_type").size().to_dict() == {
            "playin": 12,
            "playoffs": 170,
            "regular": 2460,
        }
        assert (frame.groupby("game_id").size() == 2).all()

    def test_opening_night_game(self, raw) -> None:
        """OKC beat Houston 125-124 at home in double overtime to open 2025-26."""
        frame = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2025, REGULAR)])
        game = frame[frame["game_id"] == "0022500001"].set_index("team_id")
        thunder, rockets = game.loc[OKC], game.loc[HOU]
        assert thunder["game_date"] == pd.Timestamp("2025-10-21")
        assert (thunder["pts"], thunder["opp_pts"]) == (125, 124)
        assert (rockets["pts"], rockets["opp_pts"]) == (124, 125)
        assert thunder["opponent_team_id"] == HOU and rockets["opponent_team_id"] == OKC
        assert bool(thunder["is_home"]) and not bool(rockets["is_home"])
        assert bool(thunder["won"]) and not bool(rockets["won"])
        assert thunder["minutes"] == 290  # 240 + two overtimes
        assert (thunder["season"], thunder["season_type"]) == ("2025-26", "regular")

    def test_rows_are_ordered_by_date_then_game(self, raw) -> None:
        frame = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2025, REGULAR)])
        assert frame["game_date"].is_monotonic_increasing
        assert frame.iloc[0]["game_id"] == "0022500001"

    def test_neutral_site_games_have_no_home_team(self, raw) -> None:
        frame = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2025, REGULAR)])
        neutral = frame[frame["is_neutral_site"]]
        assert sorted(neutral["game_id"].unique()) == [
            "0022500147",
            "0022500578",
            "0022500602",
            "0022501229",
            "0022501230",
        ]
        assert not neutral["is_home"].any()
        ordinary = frame[~frame["is_neutral_site"]]
        assert (ordinary.groupby("game_id")["is_home"].sum() == 1).all()

    def test_a_game_never_played_is_left_out_and_noted(self, raw) -> None:
        """Boston-Indiana on 2013-04-16 was cancelled after the Marathon bombing."""
        notes: list[str] = []
        frame = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2012, REGULAR)], notes)
        assert "0021201214" not in set(frame["game_id"])
        assert len(frame) == 2458
        assert frame["won"].notna().all()
        assert notes == ["1 scheduled game(s) never played and left out: 0021201214"]

    def test_no_note_when_every_game_was_played(self, raw) -> None:
        notes: list[str] = []
        teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2025, REGULAR)], notes)
        assert notes == []

    def test_an_unstarted_season_gives_an_empty_table(self, raw) -> None:
        frame = teams.build_team_games([raw(D.TEAM_GAME_LOGS, S2026, REGULAR)])
        assert len(frame) == 0
        assert tuple(frame.columns) == TEAM_GAMES.column_names

    def test_a_game_in_progress_keeps_a_null_result(self) -> None:
        log = game_log(
            [
                game_row(BOS, "BOS", "BOS vs. NYK", None, 60, minutes=120),
                game_row(NYK, "NYK", "NYK @ BOS", None, 58, minutes=120),
            ]
        )
        frame = teams.build_team_games([log])
        assert len(frame) == 2
        assert frame["won"].isna().all()

    def test_a_game_with_one_row_is_an_error(self) -> None:
        log = game_log([game_row(BOS, "BOS", "BOS vs. NYK", "W", 110)])
        with pytest.raises(PayloadError, match="without exactly two team rows"):
            teams.build_team_games([log])

    def test_two_home_teams_is_an_error(self) -> None:
        log = game_log(
            [
                game_row(BOS, "BOS", "BOS vs. NYK", "W", 110),
                game_row(NYK, "NYK", "NYK vs. BOS", "L", 100),
            ]
        )
        with pytest.raises(PayloadError, match="both teams are listed as the home team"):
            teams.build_team_games([log])

    def test_the_same_team_twice_is_an_error(self) -> None:
        log = game_log(
            [
                game_row(BOS, "BOS", "BOS vs. NYK", "W", 110),
                game_row(BOS, "BOS", "BOS @ NYK", "L", 100),
            ]
        )
        with pytest.raises(PayloadError, match="same team twice"):
            teams.build_team_games([log])

    @pytest.mark.parametrize("matchup", ["BOS NYK", "BOS vs NYK", None])
    def test_unrecognised_matchup_text_is_an_error(self, matchup) -> None:
        log = game_log(
            [
                game_row(BOS, "BOS", matchup, "W", 110),
                game_row(NYK, "NYK", "NYK @ BOS", "L", 100),
            ]
        )
        with pytest.raises(PayloadError, match="unrecognised matchup"):
            teams.build_team_games([log])

    def test_a_mislabelled_snapshot_is_an_error(self) -> None:
        payload = stats_payload(["TEAM_ID"], [], parameters={"Season": "2024-25"})
        log = snapshot("team_game_logs", payload, {"season": "2025-26", "season_type": "regular"})
        with pytest.raises(PayloadError, match="filed under 2025-26"):
            teams.build_team_games([log])


def season_inputs(raw, season: Season) -> dict:
    return {
        "base": raw(D.TEAM_SEASON_BASE, season, REGULAR),
        "advanced": raw(D.TEAM_SEASON_ADVANCED, season, REGULAR),
        "opponent": raw(D.TEAM_SEASON_OPPONENT, season, REGULAR),
        "standings": raw(D.STANDINGS, season),
        "regular_season_logs": raw(D.TEAM_GAME_LOGS, season, REGULAR),
    }


class TestBuildTeamSeasons:
    def test_real_season_conforms(self, raw) -> None:
        frame = teams.build_team_seasons(**season_inputs(raw, S2025))
        assert validate_frame(frame, TEAM_SEASONS) == []
        assert len(frame) == 30
        assert (frame["season"] == "2025-26").all()

    def test_published_figures_are_carried_over(self, raw) -> None:
        """Atlanta's 2025-26 line, as published by the league."""
        frame = teams.build_team_seasons(**season_inputs(raw, S2025)).set_index("team_id")
        hawks = frame.loc[ATL]
        assert hawks["team_name"] == "Atlanta Hawks"
        assert hawks["team_abbreviation"] == "ATL"
        assert (hawks["conference"], hawks["division"], hawks["conference_rank"]) == (
            "East",
            "Southeast",
            6,
        )
        assert (hawks["games_played"], hawks["wins"], hawks["losses"]) == (82, 46, 36)
        assert hawks["minutes"] == 3951.0
        assert (hawks["fgm"], hawks["fga"], hawks["fg3m"], hawks["fg3a"]) == (
            3575,
            7541,
            1201,
            3237,
        )
        assert (hawks["pts"], hawks["opp_pts"]) == (9714, 9516)
        assert (hawks["opp_fgm"], hawks["opp_tov"]) == (3473, 1317)
        assert hawks["possessions"] == 8444
        assert (hawks["pace"], hawks["off_rating"], hawks["def_rating"], hawks["net_rating"]) == (
            102.5,
            115.0,
            112.9,
            2.2,
        )

    def test_values_match_the_raw_response_for_every_team(self, raw) -> None:
        """Column mapping, checked independently of the normaliser's own lookup table."""
        frame = teams.build_team_seasons(**season_inputs(raw, S2025)).set_index("team_id")
        base = raw(D.TEAM_SEASON_BASE, S2025, REGULAR).payload["resultSets"][0]
        opponent = raw(D.TEAM_SEASON_OPPONENT, S2025, REGULAR).payload["resultSets"][0]
        for row in base["rowSet"]:
            source = dict(zip(base["headers"], row, strict=True))
            ours = frame.loc[source["TEAM_ID"]]
            assert (ours["tov"], ours["stl"], ours["blk"], ours["pf"]) == (
                source["TOV"],
                source["STL"],
                source["BLK"],
                source["PF"],
            )
            assert (ours["oreb"], ours["dreb"], ours["reb"], ours["ast"]) == (
                source["OREB"],
                source["DREB"],
                source["REB"],
                source["AST"],
            )
        for row in opponent["rowSet"]:
            source = dict(zip(opponent["headers"], row, strict=True))
            ours = frame.loc[source["TEAM_ID"]]
            assert (ours["opp_fga"], ours["opp_reb"], ours["opp_pts"]) == (
                source["OPP_FGA"],
                source["OPP_REB"],
                source["OPP_PTS"],
            )

    def test_outcomes_are_null_when_none_are_supplied(self, raw) -> None:
        frame = teams.build_team_seasons(**season_inputs(raw, S2025))
        outcome_columns = [c for c in frame.columns if c.startswith(("made_", "playoff_", "won_"))]
        assert len(outcome_columns) == 9
        assert frame[outcome_columns].isna().all().all()

    def test_supplied_outcomes_are_attached(self, raw) -> None:
        inputs = season_inputs(raw, S2025)
        team_ids = teams.build_team_seasons(**inputs)["team_id"]
        outcomes = pd.DataFrame(
            {
                "team_id": team_ids,
                "made_play_in": False,
                "made_playoffs": team_ids == NYK,
                "playoff_round_reached": (team_ids == NYK) * 4,
                "playoff_series_won": (team_ids == NYK) * 4,
                "playoff_wins": (team_ids == NYK) * 16,
                "playoff_losses": (team_ids == NYK) * 3,
                "made_conference_finals": team_ids == NYK,
                "made_finals": team_ids == NYK,
                "won_championship": team_ids == NYK,
            }
        )
        frame = teams.build_team_seasons(**inputs, outcomes=outcomes).set_index("team_id")
        assert bool(frame.loc[NYK, "won_championship"])
        assert frame.loc[NYK, "playoff_wins"] == 16
        assert not bool(frame.loc[ATL, "won_championship"])
        assert int(frame["won_championship"].sum()) == 1

    def test_outcomes_for_the_wrong_teams_are_rejected(self, raw) -> None:
        outcomes = pd.DataFrame({"team_id": [1, 2, 3]})
        with pytest.raises(PayloadError, match="postseason outcomes cover different teams"):
            teams.build_team_seasons(**season_inputs(raw, S2025), outcomes=outcomes)

    def test_historical_names_and_abbreviations(self, raw) -> None:
        frame = teams.build_team_seasons(**season_inputs(raw, S1996)).set_index("team_id")
        assert len(frame) == 29
        assert frame.loc[1610612763, "team_name"] == "Vancouver Grizzlies"
        assert frame.loc[1610612763, "team_abbreviation"] == "VAN"
        assert frame.loc[OKC, "team_name"] == "Seattle SuperSonics"
        assert frame.loc[OKC, "team_abbreviation"] == "SEA"
        assert frame.loc[1610612741, ["wins", "losses"]].tolist() == [69, 13]

    def test_fractional_published_totals_are_rounded_and_noted(self, raw) -> None:
        """Sacramento's 1996-97 opponent totals are published as 1253.8, 1255.4 and 426.8."""
        notes: list[str] = []
        frame = teams.build_team_seasons(**season_inputs(raw, S1996), notes=notes)
        kings = frame.set_index("team_id").loc[SAC]
        assert (kings["opp_fg3a"], kings["opp_tov"], kings["opp_blk"]) == (1254, 1255, 427)
        assert notes == [
            "published totals that were not whole numbers were rounded: "
            "OPP_FG3A (1), OPP_TOV (1), OPP_BLK (1)"
        ]

    def test_a_clean_season_produces_no_notes(self, raw) -> None:
        notes: list[str] = []
        teams.build_team_seasons(**season_inputs(raw, S2025), notes=notes)
        assert notes == []

    def test_the_cancelled_game_leaves_two_teams_with_81_games(self, raw) -> None:
        frame = teams.build_team_seasons(**season_inputs(raw, S2012)).set_index("team_id")
        assert frame.loc[BOS, ["games_played", "wins", "losses"]].tolist() == [81, 41, 40]
        assert frame.loc[IND, ["games_played", "wins", "losses"]].tolist() == [81, 49, 32]
        assert (frame.drop(index=[BOS, IND])["games_played"] == 82).all()

    def test_an_unstarted_season_gives_an_empty_table(self, raw) -> None:
        frame = teams.build_team_seasons(**season_inputs(raw, S2026))
        assert len(frame) == 0
        assert tuple(frame.columns) == TEAM_SEASONS.column_names

    def test_datasets_from_different_seasons_are_rejected(self, raw) -> None:
        inputs = season_inputs(raw, S2025)
        inputs["advanced"] = raw(D.TEAM_SEASON_ADVANCED, S2012, REGULAR)
        with pytest.raises(PayloadError, match="does not belong to season 2025-26"):
            teams.build_team_seasons(**inputs)

    def test_datasets_covering_different_teams_are_rejected(self, raw) -> None:
        inputs = season_inputs(raw, S2025)
        advanced = inputs["advanced"]
        result_set = advanced.payload["resultSets"][0]
        trimmed = {
            **advanced.payload,
            "resultSets": [{**result_set, "rowSet": result_set["rowSet"][:-1]}],
        }
        inputs["advanced"] = snapshot("team_season_advanced", trimmed, advanced.partition)
        with pytest.raises(PayloadError, match="advanced dataset covers different teams"):
            teams.build_team_seasons(**inputs)


class TestSeasonAbbreviations:
    def test_one_abbreviation_per_team(self, raw) -> None:
        abbreviations = teams.season_abbreviations(raw(D.TEAM_GAME_LOGS, S2025, REGULAR))
        assert len(abbreviations) == 30
        assert abbreviations[BOS] == "BOS"

    def test_abbreviations_are_those_of_the_season(self, raw) -> None:
        abbreviations = teams.season_abbreviations(raw(D.TEAM_GAME_LOGS, S1996, REGULAR))
        assert abbreviations[1610612751] == "NJN"
        assert abbreviations[1610612766] == "CHH"

    def test_no_games_no_abbreviations(self, raw) -> None:
        assert teams.season_abbreviations(raw(D.TEAM_GAME_LOGS, S2026, REGULAR)) == {}
