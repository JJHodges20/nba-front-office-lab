"""Player normalisers, tested against real responses in the fixture store."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.domain.datasets import NbaStatsDataset
from front_office.domain.schema import validate_frame
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.tables.players import (
    PLAYER_GAME_LOGS,
    PLAYER_ON_OFF,
    PLAYER_SEASONS,
    PLAYERS,
    TEAM_ROSTERS,
)
from front_office.processing.nba_stats import players, teams
from front_office.processing.nba_stats.resultsets import PayloadError
from tests.helpers import snapshot, stats_payload

D = NbaStatsDataset
REGULAR, PLAYOFFS, PLAY_IN = SeasonType.REGULAR, SeasonType.PLAYOFFS, SeasonType.PLAY_IN
S2025, S2026 = Season(2025), Season(2026)
BOS, NYK = 1610612738, 1610612752
TATUM, ANUNOBY, ABDELNABY, VUCEVIC = 1628369, 1628384, 76001, 202696


def source_rows(snap, result_set: int = 0) -> list[dict]:
    chosen = snap.payload["resultSets"][result_set]
    return [dict(zip(chosen["headers"], row, strict=True)) for row in chosen["rowSet"]]


def with_rows(snap, rows: list[list] | None = None, headers: list[str] | None = None):
    """A copy of a snapshot with its first result set's rows or headers replaced."""
    first, *rest = snap.payload["resultSets"]
    changed = {**first}
    if rows is not None:
        changed["rowSet"] = rows
    if headers is not None:
        changed["headers"] = headers
    payload = {**snap.payload, "resultSets": [changed, *rest]}
    return snapshot(snap.dataset, payload, snap.partition)


@pytest.fixture(scope="module")
def rosters(raw):
    return [
        raw(D.TEAM_ROSTER, season, team_id=team) for season in (S2025, S2026) for team in (BOS, NYK)
    ]


@pytest.fixture(scope="module")
def team_games(raw) -> pd.DataFrame:
    return teams.build_team_games(
        [raw(D.TEAM_GAME_LOGS, S2025, kind) for kind in (REGULAR, PLAYOFFS, PLAY_IN)]
    )


class TestBuildPlayers:
    def test_conforms(self, raw, rosters) -> None:
        frame = players.build_players(raw(D.PLAYER_INDEX), rosters)
        assert validate_frame(frame, PLAYERS) == []
        assert frame["player_id"].is_monotonic_increasing
        assert len(frame) == len(source_rows(raw(D.PLAYER_INDEX)))

    def test_an_active_player(self, raw, rosters) -> None:
        tatum = (
            players.build_players(raw(D.PLAYER_INDEX), rosters).set_index("player_id").loc[TATUM]
        )
        assert (tatum["full_name"], tatum["first_name"], tatum["last_name"]) == (
            "Jayson Tatum",
            "Jayson",
            "Tatum",
        )
        assert (tatum["position"], tatum["height_inches"], tatum["weight_lbs"]) == ("F-G", 80, 210)
        assert tatum["birth_date"] == pd.Timestamp("1998-03-03")
        assert (tatum["country"], tatum["college"]) == ("USA", "Duke")
        assert (tatum["draft_year"], tatum["draft_round"], tatum["draft_number"]) == (2017, 1, 3)
        assert (tatum["first_season_year"], tatum["last_season_year"]) == (2017, 2026)
        assert bool(tatum["is_active"])
        assert tatum["current_team_id"] == BOS

    def test_a_retired_player_has_no_current_team(self, raw, rosters) -> None:
        """The index lists a retired player's last team; that is not where he is now."""
        frame = players.build_players(raw(D.PLAYER_INDEX), rosters).set_index("player_id")
        retired = frame.loc[ABDELNABY]
        assert retired["full_name"] == "Alaa Abdelnaby"
        assert not bool(retired["is_active"])
        assert pd.isna(retired["current_team_id"])
        assert pd.isna(retired["birth_date"])  # he is on no ingested roster
        assert (retired["first_season_year"], retired["last_season_year"]) == (1990, 1994)

    def test_only_active_players_have_a_current_team(self, raw, rosters) -> None:
        frame = players.build_players(raw(D.PLAYER_INDEX), rosters)
        assert frame.loc[~frame["is_active"], "current_team_id"].isna().all()
        assert frame.loc[frame["is_active"], "current_team_id"].notna().all()

    def test_birth_dates_come_from_rosters(self, raw, rosters) -> None:
        without = players.build_players(raw(D.PLAYER_INDEX))
        assert without["birth_date"].isna().all()
        with_rosters = players.build_players(raw(D.PLAYER_INDEX), rosters)
        rostered = {row["PLAYER_ID"] for roster in rosters for row in source_rows(roster)}
        known = set(with_rosters.loc[with_rosters["birth_date"].notna(), "player_id"])
        assert known == rostered & set(with_rosters["player_id"])

    def test_a_single_name_player_has_no_first_name(self, raw) -> None:
        index = raw(D.PLAYER_INDEX)
        headers = index.payload["resultSets"][0]["headers"]
        row = list(index.payload["resultSets"][0]["rowSet"][0])
        row[headers.index("PLAYER_FIRST_NAME")] = ""
        row[headers.index("PLAYER_LAST_NAME")] = "Nene"
        frame = players.build_players(with_rows(index, [row]))
        assert frame.iloc[0]["full_name"] == "Nene"
        assert pd.isna(frame.iloc[0]["first_name"])

    def test_a_missing_column_is_named(self, raw) -> None:
        index = raw(D.PLAYER_INDEX)
        headers = [
            "RENAMED" if header == "ROSTER_STATUS" else header
            for header in index.payload["resultSets"][0]["headers"]
        ]
        with pytest.raises(PayloadError, match=r"missing expected columns \['ROSTER_STATUS'\]"):
            players.build_players(with_rows(index, headers=headers))


class TestBuildPlayerSeasons:
    def build(self, raw, season_type: SeasonType = REGULAR) -> pd.DataFrame:
        return players.build_player_seasons(
            base=raw(D.PLAYER_SEASON_BASE, S2025, season_type),
            advanced=raw(D.PLAYER_SEASON_ADVANCED, S2025, season_type),
            starters=raw(D.PLAYER_SEASON_STARTERS, S2025, season_type),
        )

    @pytest.mark.parametrize("season_type", [REGULAR, PLAYOFFS])
    def test_conforms(self, raw, season_type: SeasonType) -> None:
        frame = self.build(raw, season_type)
        assert validate_frame(frame, PLAYER_SEASONS) == []
        assert (frame["season"] == "2025-26").all()
        assert (frame["season_type"] == season_type.value).all()
        assert len(frame) == len(source_rows(raw(D.PLAYER_SEASON_BASE, S2025, season_type)))

    def test_a_player_line(self, raw) -> None:
        tatum = self.build(raw).set_index("player_id").loc[TATUM]
        assert (tatum["player_name"], tatum["team_id"], tatum["team_count"]) == (
            "Jayson Tatum",
            BOS,
            1,
        )
        assert (tatum["age"], tatum["games_played"], tatum["games_started"]) == (28, 16, 16)
        assert (tatum["wins"], tatum["losses"]) == (13, 3)
        assert tatum["minutes"] == pytest.approx(521.85)
        assert (tatum["fgm"], tatum["fga"], tatum["fg3m"], tatum["fg3a"]) == (118, 287, 47, 143)
        assert (tatum["pts"], tatum["reb"], tatum["ast"], tatum["tov"]) == (348, 160, 85, 39)
        assert (tatum["possessions"], tatum["off_rating"], tatum["net_rating"]) == (
            1069,
            120.7,
            10.5,
        )
        assert tatum["usage_pct"] == pytest.approx(0.29)

    def test_every_column_matches_the_raw_response(self, raw) -> None:
        """Column mapping, checked independently of the normaliser's own lookup table."""
        frame = self.build(raw).set_index("player_id")
        expected = {
            "BLKA": "blocked_attempts",
            "PFD": "fouls_drawn",
            "PLUS_MINUS": "plus_minus",
            "DD2": "double_doubles",
            "TD3": "triple_doubles",
            "STL": "stl",
            "BLK": "blk",
            "PF": "pf",
            "OREB": "oreb",
            "DREB": "dreb",
        }
        for source in source_rows(raw(D.PLAYER_SEASON_BASE, S2025, REGULAR)):
            ours = frame.loc[source["PLAYER_ID"]]
            for theirs, column in expected.items():
                assert ours[column] == source[theirs], (source["PLAYER_NAME"], column)
        advanced = {
            "USG_PCT": "usage_pct",
            "AST_PCT": "assist_pct",
            "OREB_PCT": "oreb_pct",
            "DREB_PCT": "dreb_pct",
            "REB_PCT": "reb_pct",
            "PACE": "pace",
            "PIE": "player_impact_estimate",
            "DEF_RATING": "def_rating",
        }
        for source in source_rows(raw(D.PLAYER_SEASON_ADVANCED, S2025, REGULAR)):
            ours = frame.loc[source["PLAYER_ID"]]
            for theirs, column in advanced.items():
                assert ours[column] == pytest.approx(source[theirs]), (
                    source["PLAYER_NAME"],
                    column,
                )

    def test_a_traded_player_has_one_row_for_all_his_teams(self, raw) -> None:
        frame = self.build(raw)
        vucevic = frame[frame["player_id"] == VUCEVIC]
        assert len(vucevic) == 1
        assert vucevic.iloc[0]["team_count"] == 2
        assert vucevic.iloc[0]["team_id"] == BOS  # the team he finished with
        assert vucevic.iloc[0]["player_name"] == "Nikola Vučević"

    def test_games_started_come_from_the_starters_dataset(self, raw) -> None:
        frame = self.build(raw).set_index("player_id")
        starts = {
            r["PLAYER_ID"]: r["GP"]
            for r in source_rows(raw(D.PLAYER_SEASON_STARTERS, S2025, REGULAR))
        }
        assert starts, "fixture should include starters"
        for player_id, row in frame.iterrows():
            assert row["games_started"] == starts.get(player_id, 0)
        assert (frame["games_started"] <= frame["games_played"]).all()
        assert (frame["games_started"] == 0).any()  # someone never started

    def test_without_a_starters_dataset_starts_are_unknown(self, raw) -> None:
        frame = players.build_player_seasons(
            base=raw(D.PLAYER_SEASON_BASE, S2025, REGULAR),
            advanced=raw(D.PLAYER_SEASON_ADVANCED, S2025, REGULAR),
        )
        assert frame["games_started"].isna().all()

    def test_an_unstarted_season_gives_an_empty_table(self, raw) -> None:
        base = raw(D.PLAYER_SEASON_BASE, S2025, REGULAR)
        frame = players.build_player_seasons(
            base=with_rows(base, []), advanced=raw(D.PLAYER_SEASON_ADVANCED, S2025, REGULAR)
        )
        assert len(frame) == 0
        assert tuple(frame.columns) == PLAYER_SEASONS.column_names

    def test_base_and_advanced_must_cover_the_same_players(self, raw) -> None:
        advanced = raw(D.PLAYER_SEASON_ADVANCED, S2025, REGULAR)
        fewer = with_rows(advanced, advanced.payload["resultSets"][0]["rowSet"][:-1])
        with pytest.raises(PayloadError, match="advanced dataset covers different players"):
            players.build_player_seasons(
                base=raw(D.PLAYER_SEASON_BASE, S2025, REGULAR), advanced=fewer
            )

    def test_datasets_of_different_phases_are_rejected(self, raw) -> None:
        with pytest.raises(PayloadError, match="does not match"):
            players.build_player_seasons(
                base=raw(D.PLAYER_SEASON_BASE, S2025, REGULAR),
                advanced=raw(D.PLAYER_SEASON_ADVANCED, S2025, PLAYOFFS),
            )


class TestBuildPlayerGameLogs:
    @pytest.mark.parametrize("season_type", [REGULAR, PLAYOFFS])
    def test_conforms(self, raw, team_games, season_type: SeasonType) -> None:
        logs = raw(D.PLAYER_GAME_LOGS, S2025, season_type)
        frame = players.build_player_game_logs(logs, team_games)
        assert validate_frame(frame, PLAYER_GAME_LOGS) == []
        assert len(frame) == len(source_rows(logs))
        assert (frame["season_type"] == season_type.value).all()

    def test_opponent_and_venue_come_from_the_team_table(self, raw, team_games) -> None:
        frame = players.build_player_game_logs(raw(D.PLAYER_GAME_LOGS, S2025, REGULAR), team_games)
        context = team_games.set_index(["game_id", "team_id"])
        for row in frame.sample(60, random_state=7).itertuples():
            team_row = context.loc[(row.game_id, row.team_id)]
            assert row.opponent_team_id == team_row["opponent_team_id"]
            assert row.is_home == team_row["is_home"]
            assert row.is_neutral_site == team_row["is_neutral_site"]
            assert row.won == team_row["won"]
            assert row.game_date == team_row["game_date"]

    def test_a_teams_players_account_for_all_its_points(self, raw, team_games) -> None:
        frame = players.build_player_game_logs(raw(D.PLAYER_GAME_LOGS, S2025, REGULAR), team_games)
        celtics = frame[frame["team_id"] == BOS].groupby("game_id")["pts"].sum()
        team = team_games[team_games["team_id"] == BOS].set_index("game_id")["pts"]
        assert len(celtics) == 82
        assert (celtics == team.reindex(celtics.index)).all()

    def test_season_totals_equal_the_sum_of_the_log(self, raw, team_games) -> None:
        logs = players.build_player_game_logs(raw(D.PLAYER_GAME_LOGS, S2025, REGULAR), team_games)
        seasons = players.build_player_seasons(
            base=raw(D.PLAYER_SEASON_BASE, S2025, REGULAR),
            advanced=raw(D.PLAYER_SEASON_ADVANCED, S2025, REGULAR),
        ).set_index("player_id")
        summed = logs.groupby("player_id").agg(games=("game_id", "size"), pts=("pts", "sum"))
        assert (summed["games"] == seasons["games_played"].reindex(summed.index)).all()
        assert (summed["pts"] == seasons["pts"].reindex(summed.index)).all()

    def test_a_traded_players_games_carry_each_team(self, raw, team_games) -> None:
        frame = players.build_player_game_logs(raw(D.PLAYER_GAME_LOGS, S2025, REGULAR), team_games)
        assert frame.loc[frame["player_id"] == VUCEVIC, "team_id"].nunique() == 2

    def test_player_rows_without_a_team_game_are_an_error(self, raw, team_games) -> None:
        without_first_game = team_games[team_games["game_id"] != "0022500003"]
        logs = raw(D.PLAYER_GAME_LOGS, S2025, REGULAR)
        game_ids = {row["GAME_ID"] for row in source_rows(logs)}
        missing = sorted(game_ids)[0]
        with pytest.raises(PayloadError, match="missing from the team game logs"):
            players.build_player_game_logs(
                logs, without_first_game[without_first_game["game_id"] != missing]
            )

    def test_no_logs_gives_an_empty_table(self, raw, team_games) -> None:
        logs = with_rows(raw(D.PLAYER_GAME_LOGS, S2025, REGULAR), [])
        frame = players.build_player_game_logs(logs, team_games)
        assert len(frame) == 0
        assert tuple(frame.columns) == PLAYER_GAME_LOGS.column_names


class TestBuildTeamRosters:
    def test_conforms(self, rosters) -> None:
        frame = players.build_team_rosters(rosters)
        assert validate_frame(frame, TEAM_ROSTERS) == []
        assert frame.groupby(["season", "team_id"]).size().to_dict() == {
            ("2025-26", BOS): 16,
            ("2025-26", NYK): 18,
            ("2026-27", BOS): 21,
            ("2026-27", NYK): 21,
        }

    def test_a_roster_row(self, rosters) -> None:
        frame = players.build_team_rosters(rosters)
        rows = frame[frame["player_id"] == TATUM].set_index("season")
        current = rows.loc["2025-26"]
        assert (current["player_name"], current["team_id"], current["jersey_number"]) == (
            "Jayson Tatum",
            BOS,
            "0",
        )
        assert (current["position"], current["height_inches"], current["weight_lbs"]) == (
            "F-G",
            80,
            210,
        )
        assert current["birth_date"] == pd.Timestamp("1998-03-03")
        assert current["how_acquired"] == "#3 Pick in 2017 Draft"
        assert (current["experience_years"], rows.loc["2026-27", "experience_years"]) == (8, 9)

    def test_rookies_have_zero_experience(self, rosters) -> None:
        frame = players.build_team_rosters(rosters)
        source = [row for roster in rosters for row in source_rows(roster)]
        rookies = {(row["SEASON"], row["PLAYER_ID"]) for row in source if row["EXP"] == "R"}
        assert rookies
        ours = {
            (str(Season.parse(row.season).start_year), row.player_id)
            for row in frame[frame["experience_years"] == 0].itertuples()
        }
        assert ours == rookies

    def test_new_signings_may_lack_a_listed_size(self, rosters) -> None:
        """The league lists some new arrivals before it lists their position or height."""
        frame = players.build_team_rosters(rosters)
        upcoming = frame[frame["season"] == "2026-27"]
        assert upcoming["position"].isna().any()
        assert upcoming["birth_date"].notna().all()

    def test_extra_source_columns_are_ignored(self, rosters) -> None:
        """2026-27 rosters gained a SUPPLEMENTAL_STATUS column the earlier ones lack."""
        headers = {tuple(r.payload["resultSets"][0]["headers"]) for r in rosters}
        assert len(headers) == 2
        assert len(players.build_team_rosters(rosters)) == 76

    def test_no_rosters_gives_an_empty_table(self) -> None:
        frame = players.build_team_rosters([])
        assert len(frame) == 0
        assert tuple(frame.columns) == TEAM_ROSTERS.column_names

    def test_a_roster_filed_under_the_wrong_team_is_rejected(self, raw) -> None:
        roster = raw(D.TEAM_ROSTER, S2025, team_id=BOS)
        misfiled = snapshot(
            "team_roster", roster.payload, {"season": "2025-26", "team_id": str(NYK)}
        )
        with pytest.raises(PayloadError, match="belong to another team"):
            players.build_team_rosters([misfiled])

    def test_a_roster_filed_under_the_wrong_season_is_rejected(self, raw) -> None:
        roster = raw(D.TEAM_ROSTER, S2025, team_id=BOS)
        payload = {**roster.payload, "parameters": {}}
        misfiled = snapshot("team_roster", payload, {"season": "2024-25", "team_id": str(BOS)})
        with pytest.raises(PayloadError, match="roster rows are for season"):
            players.build_team_rosters([misfiled])

    def test_unknown_experience_text_is_rejected(self, raw) -> None:
        roster = raw(D.TEAM_ROSTER, S2025, team_id=BOS)
        headers = roster.payload["resultSets"][0]["headers"]
        row = list(roster.payload["resultSets"][0]["rowSet"][0])
        row[headers.index("EXP")] = "veteran"
        with pytest.raises(PayloadError):
            players.build_team_rosters([with_rows(roster, [row])])


class TestBuildPlayerOnOff:
    def test_conforms(self, raw) -> None:
        frame = players.build_player_on_off(
            [raw(D.TEAM_ON_OFF, S2025, REGULAR, team) for team in (BOS, NYK)]
        )
        assert validate_frame(frame, PLAYER_ON_OFF) == []
        assert set(frame["team_id"]) == {BOS, NYK}
        assert (frame["season_type"] == "regular").all()

    def test_on_and_off_court_lines(self, raw) -> None:
        frame = players.build_player_on_off([raw(D.TEAM_ON_OFF, S2025, REGULAR, BOS)])
        tatum = frame.set_index("player_id").loc[TATUM]
        assert (tatum["on_court_minutes"], tatum["off_court_minutes"]) == (522.0, 3424.0)
        assert (tatum["on_court_off_rating"], tatum["on_court_def_rating"]) == (120.7, 110.2)
        assert tatum["on_court_net_rating"] == 10.5
        assert (tatum["off_court_off_rating"], tatum["off_court_net_rating"]) == (119.4, 7.8)

    def test_players_who_never_took_the_court_are_left_out(self, raw) -> None:
        snap = raw(D.TEAM_ON_OFF, S2025, REGULAR, BOS)
        on_court = {row["VS_PLAYER_ID"] for row in source_rows(snap, 1)}
        off_court = {row["VS_PLAYER_ID"] for row in source_rows(snap, 2)}
        frame = players.build_player_on_off([snap])
        assert set(frame["player_id"]) == on_court
        assert frame["on_court_minutes"].notna().all()
        assert on_court <= off_court or frame["off_court_minutes"].isna().any()

    def test_no_snapshots_gives_an_empty_table(self) -> None:
        frame = players.build_player_on_off([])
        assert len(frame) == 0
        assert tuple(frame.columns) == PLAYER_ON_OFF.column_names

    def test_rows_for_another_team_are_rejected(self, raw) -> None:
        snap = raw(D.TEAM_ON_OFF, S2025, REGULAR, BOS)
        misfiled = snapshot(
            "team_on_off",
            snap.payload,
            {"season": "2025-26", "season_type": "regular", "team_id": str(NYK)},
        )
        with pytest.raises(PayloadError, match="belong to another team"):
            players.build_player_on_off([misfiled])

    def test_a_missing_result_set_is_named(self, raw) -> None:
        payload = stats_payload(["TEAM_ID"], [], name="Overall")
        snap = snapshot(
            "team_on_off",
            payload,
            {"season": "2025-26", "season_type": "regular", "team_id": str(BOS)},
        )
        with pytest.raises(PayloadError, match="no result set"):
            players.build_player_on_off([snap])
