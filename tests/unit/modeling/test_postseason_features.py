"""What the postseason model reads about a team-season, and the games and series it is
fitted and tested on - checked against the invented league's own records."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.postseason import PostseasonSpec
from front_office.domain.stages import BRACKET_STAGE_KEYS
from front_office.domain.tables.players import PLAYER_GAME_LOGS
from front_office.modeling.postseason import (
    GAPS,
    TEAM_COLUMNS,
    head_to_head,
    keyed,
    pattern_for,
    playoff_games,
    series_table,
    team_features,
)
from front_office.modeling.postseason.features import _experience
from tests.league import make_league
from tests.postseason_reference import team_strengths
from tests.synthetic_lab import league_frames

SPEC = PostseasonSpec(formats=(), resamples=50, kept_draws=10)
SEASON = "2005-06"


@pytest.fixture(scope="module")
def frames(postseason_league) -> dict[str, pd.DataFrame]:  # type: ignore[no-untyped-def]
    return postseason_league[2]


@pytest.fixture(scope="module")
def features(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return team_features(frames, SPEC)


def small_league(*, unfinished: bool):  # type: ignore[no-untyped-def]
    """Sixteen teams over three seasons, playoffs played on the planted ratings alone and
    nobody valued; the last season left undecided if asked."""
    league = make_league(teams=16, seasons=3, seed=4)
    for year in league.years:
        league.plant_at_random(year, seed=4)
    if unfinished:
        league.unfinished = {league.years[-1]}
    for year in league.years:
        if year in league.unfinished:
            continue
        strengths = {
            team: (offense + defense, 0.0)
            for team, (offense, defense) in league.ratings[year].items()
        }
        league.plant_postseason(
            year, strengths, home_advantage=0.4, net_slope=0.1, top_slope=0.0, seed=4
        )
    return league, league_frames(league)


class TestTeamFeatures:
    def test_one_row_per_team_season_oldest_first(self, features, frames) -> None:  # type: ignore[no-untyped-def]
        assert tuple(features.columns) == TEAM_COLUMNS
        assert len(features) == len(frames["team_seasons"]) == 420
        assert features["start_year"].is_monotonic_increasing
        assert features["decided"].all()
        assert features["win_pct"].to_numpy() == pytest.approx(
            (features["wins"] / features["games_played"]).to_numpy()
        )

    def test_the_inputs_are_what_the_reference_reads(self, features, frames) -> None:  # type: ignore[no-untyped-def]
        season = keyed(features).loc[SEASON]
        for team, (net, top) in team_strengths(frames, 2005).items():
            assert season.at[team, "net_rating"] == pytest.approx(net)
            assert season.at[team, "top_players"] == pytest.approx(top)
        assert (season["best_player"] >= season["top_players"]).all()
        assert season["experience"].eq(0).all()  # the league keeps no playoff logs

    def test_the_stages_follow_the_playoffs_played_and_nest(
        self, features, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        played = postseason_league[0].postseasons[2005]
        season = keyed(features).loc[SEASON]
        counts = [int(season[key].sum()) for key in BRACKET_STAGE_KEYS]
        assert counts == [16, 8, 4, 2, 1]
        assert season.index[season["won_championship"]][0] == played.champion
        for earlier, later in zip(BRACKET_STAGE_KEYS, BRACKET_STAGE_KEYS[1:], strict=False):
            assert (season[later] <= season[earlier]).all()
        reached = season.index.map(played.round_reached)
        assert (season["round_reached"] == reached).all()
        assert (season["conference_rank"] == season.index.map(played.seeds)).all()

    def test_an_undecided_season_has_no_flags_and_unvalued_teams_no_quality(self) -> None:
        league, frames = small_league(unfinished=True)
        features = team_features(frames, SPEC)
        assert len(features) == 16 * 3 and features["top_players"].isna().all()
        last = features[features["season"] == "2002-03"]
        assert not last["decided"].any() and last["round_reached"].eq(0).all()
        assert not last[list(BRACKET_STAGE_KEYS)].any().any()
        first = features[features["season"] == "2000-01"]
        assert first["decided"].all() and int(first["made_playoffs"].sum()) == 16

    def test_an_empty_season_gives_an_empty_frame(self, frames) -> None:  # type: ignore[no-untyped-def]
        empty = {name: frame.iloc[0:0] for name, frame in frames.items()}
        features = team_features(empty, SPEC)
        assert features.empty and tuple(features.columns) == TEAM_COLUMNS


class TestExperience:
    def test_counts_playoff_games_over_previous_seasons_weighted_by_minutes(self) -> None:
        lines = pd.DataFrame(
            {
                "player_id": [1, 2],
                "season": ["2003-04", "2003-04"],
                "team_id": [101, 101],
                "minutes": [3000.0, 1000.0],
            }
        )
        logs = pd.DataFrame(
            {
                "player_id": [1, 1, 1, 2],
                "season": ["2002-03", "2002-03", "1999-00", "2001-02"],
                "season_type": ["playoffs", "playoffs", "playoffs", "regular"],
            }
        )
        out = _experience(lines, logs, PostseasonSpec(experience_seasons=3))
        # Player 1's two games the season before count; 1999-00 is four seasons back, and
        # player 2's games were regular-season ones. Five on the floor, by minutes share.
        assert out.loc[("2003-04", 101)] == pytest.approx(5 * (2 * 3000 / 4000))

    def test_no_playoff_logs_means_no_experience_not_a_crash(self) -> None:
        lines = pd.DataFrame(
            {"player_id": [1], "season": ["2003-04"], "team_id": [101], "minutes": [1000.0]}
        )
        out = _experience(lines, PLAYER_GAME_LOGS.empty_frame(), PostseasonSpec())
        assert out.loc[("2003-04", 101)] == 0.0


class TestGamesAndSeries:
    def test_head_to_head_counts_regular_season_wins_only(self) -> None:
        games = pd.DataFrame(
            {
                "season": ["2005-06"] * 4,
                "season_type": ["regular", "regular", "regular", "playoffs"],
                "team_id": [1, 1, 2, 1],
                "opponent_team_id": [2, 2, 1, 2],
                "won": [True, True, True, True],
            }
        )
        assert head_to_head(games) == {("2005-06", 1, 2): 2, ("2005-06", 2, 1): 1}

    def test_playoff_games_are_from_the_home_side_with_the_gaps(self, frames, features) -> None:  # type: ignore[no-untyped-def]
        games = playoff_games(frames, features, SPEC)
        played = frames["team_games"]
        assert len(games) == len(played[played["season_type"] == "playoffs"]) // 2 > 1000
        assert set(games["home"]) == {1.0}
        assert set(games.columns) >= {f"{measure}_diff" for measure in GAPS}
        table = keyed(features)
        first = games.iloc[0]
        mine = table.loc[(first["season"], first["team_id"])]
        theirs = table.loc[(first["season"], first["opponent_team_id"])]
        assert first["net_rating_diff"] == pytest.approx(mine["net_rating"] - theirs["net_rating"])
        assert first["top_players_diff"] == pytest.approx(
            mine["top_players"] - theirs["top_players"]
        )
        recorded = frames["team_games"].set_index(["game_id", "team_id"])
        assert first["home_won"] == float(recorded.at[(first["game_id"], first["team_id"]), "won"])
        assert games["home_won"].isin([0.0, 1.0]).all()

    def test_a_neutral_postseason_has_no_home_court(self, frames, features) -> None:  # type: ignore[no-untyped-def]
        spec = PostseasonSpec(neutral_postseasons=(SEASON,), resamples=50, kept_draws=10)
        games = playoff_games(frames, features, spec)
        assert set(games.loc[games["season"] == SEASON, "home"]) == {0.0}
        assert set(games.loc[games["season"] != SEASON, "home"]) == {1.0}
        series = series_table(frames, features, spec)
        assert series.loc[series["season"] == SEASON, "neutral"].all()
        assert not series.loc[series["season"] != SEASON, "neutral"].any()

    def test_series_are_decided_with_the_home_court_side_first(
        self, frames, features, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        series = series_table(frames, features, SPEC)
        assert len(series) == 210 and series["pattern"].eq("2-2-1-1-1").all()
        played = postseason_league[0].postseasons[2005]
        mine = series[series["season"] == SEASON]
        assert list(mine["round"]) == [1] * 8 + [2] * 4 + [3] * 2 + [4]
        for row in mine.itertuples(index=False):
            match = next(
                item
                for item in played.series
                if item.playoff_round == row.round
                and {item.team_a, item.team_b} == {row.team_a_id, row.team_b_id}
            )
            assert row.team_a_id == match.team_a and row.team_b_id == match.team_b
            assert row.a_won == float(match.winner == match.team_a)
            assert (row.team_a_wins, row.team_b_wins) == (match.a_wins, match.b_wins)
        table = keyed(features)
        gaps = mine["net_rating_diff"].to_numpy()
        expected = np.array(
            [
                table.at[(SEASON, a), "net_rating"] - table.at[(SEASON, b), "net_rating"]
                for a, b in zip(mine["team_a_id"], mine["team_b_id"], strict=True)
            ]
        )
        assert gaps == pytest.approx(expected)

    def test_the_format_follows_the_round_the_season_and_the_scheduled_length(self) -> None:
        spec = PostseasonSpec()
        assert pattern_for(spec, 1, "2001-02", 5) == "2-2-1"
        assert pattern_for(spec, 1, "2001-02", 7) == "2-2-1-1-1"
        assert pattern_for(spec, 4, "2012-13", 7) == "2-3-2"
        assert pattern_for(spec, 2, "2024-25", 5) == "2-2-1"
        assert pattern_for(spec, 2, "2024-25", 7) == "2-2-1-1-1"
