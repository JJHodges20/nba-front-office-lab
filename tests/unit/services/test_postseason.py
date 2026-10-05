"""The postseason service: a season's bracket and series, every team, and a team of any
strength - all read off the model on file, nothing fitted.

``played`` is the invented league with its playoffs and a model fitted on it; ``lab`` the
fixture store (two valued teams of one season) with the model the lab ships;
``scratch_lab`` a copy with contracts that a test may add a roster to.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from front_office.analytics.teams import POSTSEASON_RESULTS
from front_office.config import load_settings, postseason_model_path
from front_office.domain.stages import BRACKET_STAGE_KEYS, ROUND_STAGE_KEYS
from front_office.modeling.postseason import (
    bracket_from_series,
    keyed,
    series_table,
    series_win_probability,
    team_features,
)
from front_office.services import Lab, probability_key
from front_office.services.postseason import (
    BRACKET_COLUMNS,
    CURVE_RATINGS,
    ODDS_COLUMNS,
    SERIES_COLUMNS,
    STAGE_COLUMNS,
    PostseasonError,
)
from tests.postseason_reference import team_strengths
from tests.unit.services.conftest import ABDELNABY, BOS, BROWN, NYK, PRITCHARD, TATUM, WHITE

SEASON = "2005-06"
TITLE = probability_key("won_championship")
PLAYOFFS = probability_key("made_playoffs")


@pytest.fixture(scope="module")
def played(postseason_home: Path) -> Iterator[Lab]:
    with Lab(load_settings(postseason_home)) as opened:
        yield opened


class TestStatus:
    def test_the_model_on_file_and_the_seasons_it_can_read(self, played: Lab) -> None:
        status = played.postseason.status()
        assert status.is_fitted and status.revision == 1 and status.is_current
        assert (status.value_model_version, status.applied_value_version) == ("r1", "r1")
        assert len(status.seasons) == 14
        assert (status.seasons[0], status.seasons[-1]) == ("2013-14", "2000-01")
        assert status.latest == "2013-14" and status.fitted_at is not None
        assert played.postseason.metrics.keys[0] == "top_players"
        assert played.postseason.model().revision == 1

    def test_on_the_fixture_store_with_the_shipped_model(self, lab: Lab) -> None:
        status = lab.postseason.status()
        assert status.is_fitted and status.is_current and status.revision == 1
        assert status.seasons == ("2025-26", "2012-13", "1996-97") and status.latest == "2025-26"

    def test_without_a_model_the_service_says_how_to_fit_one(
        self, postseason_home: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "copy"
        shutil.copytree(postseason_home, target)
        postseason_model_path(target / "configs").unlink()
        with Lab(load_settings(target)) as opened:
            status = opened.postseason.status()
            assert not status.is_fitted and not status.is_current and status.revision is None
            assert opened.postseason.model() is None
            with pytest.raises(PostseasonError, match="fol playoffs fit --write"):
                opened.postseason.outlook(3.0)
            with pytest.raises(PostseasonError):
                opened.postseason.bracket(SEASON)


@pytest.fixture(scope="module")
def report(played: Lab):  # type: ignore[no-untyped-def]
    return played.postseason.bracket(SEASON)


class TestABracket:
    def test_sixteen_teams_whose_chances_add_up(self, report) -> None:  # type: ignore[no-untyped-def]
        teams = report.teams
        assert not report.is_empty and report.missing == () and report.note == ""
        assert tuple(teams.columns) == BRACKET_COLUMNS and teams.index.name == "team_id"
        assert len(teams) == 16
        for key, total in zip(ROUND_STAGE_KEYS, (8, 4, 2, 1), strict=True):
            column = probability_key(key)
            assert teams[column].sum() == pytest.approx(total)
            assert (teams[f"{column}_low"] <= teams[column]).all()
            assert (teams[column] <= teams[f"{column}_high"]).all()
        assert set(teams["result"]) <= set(POSTSEASON_RESULTS)
        assert (teams["round_reached"] >= 1).all()
        assert sorted(teams["seed"]) == sorted(list(range(1, 9)) * 2)
        assert teams["abbreviation"].str.startswith("T").all()

    def test_the_favourite_and_the_champion(self, report, postseason_league) -> None:  # type: ignore[no-untyped-def]
        teams = report.teams
        assert report.favourite == teams.loc[teams[TITLE].idxmax(), "team_name"]
        assert report.favourite_probability == teams[TITLE].max()
        champion = postseason_league[0].postseasons[2005].champion
        assert report.champion == teams.at[champion, "team_name"]
        assert report.champion_probability == teams.at[champion, TITLE]
        assert teams.at[champion, "result"] == "Champion"

    def test_the_first_round_is_the_series_model_on_each_pair(self, report, played: Lab) -> None:  # type: ignore[no-untyped-def]
        model = played.postseason.model()
        tables = played.postseason._season_tables(SEASON)
        features = team_features(tables, model.spec)
        series = series_table(tables, features, model.spec)
        bracket = bracket_from_series(series)
        strengths = keyed(features).loc[SEASON]
        game = model.game
        column = probability_key("won_a_round")
        for pairs in bracket.conferences:
            for pair in pairs:
                expected = series_win_probability(
                    game.home_advantage,
                    game.net_rating,
                    game.top_players,
                    float(strengths.at[pair.a, "net_rating"] - strengths.at[pair.b, "net_rating"]),
                    float(
                        strengths.at[pair.a, "top_players"] - strengths.at[pair.b, "top_players"]
                    ),
                    pattern="2-2-1-1-1",
                    neutral=False,
                )
                assert report.teams.at[pair.a, column] == pytest.approx(expected)
                assert report.teams.at[pair.b, column] == pytest.approx(1 - expected)

    def test_a_season_without_a_bracket_says_why(self, played: Lab, lab: Lab) -> None:
        nothing = played.postseason.bracket("1999-00")
        assert nothing.is_empty and nothing.favourite is None
        assert "No playoff series are on record for 1999-00" in nothing.note
        assert tuple(nothing.teams.columns) == BRACKET_COLUMNS
        # The fixture store: almost every entrant lacks a player the value model scored.
        fixture = lab.postseason.bracket("2025-26")
        assert fixture.is_empty and len(fixture.missing) >= 14
        assert "New York Knicks" not in fixture.missing
        assert (
            f"{len(fixture.missing)} of the sixteen have no players the value model scored"
            in fixture.note
        )


class TestSeries:
    def test_every_decided_series_with_the_home_court_side_first(
        self, played: Lab, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        table = played.postseason.series(SEASON)
        assert tuple(table.columns) == SERIES_COLUMNS and len(table) == 15
        assert list(table["round"]) == [1] * 8 + [2] * 4 + [3] * 2 + [4]
        assert table["probability"].between(0, 1).all()
        assert (table["low"] <= table["probability"]).all()
        assert (table["probability"] <= table["high"]).all()
        names = played.team_labels()["full_name"]
        short = played.team_labels()["abbreviation"]
        for row in table.itertuples(index=False):
            match = next(
                item
                for item in postseason_league[0].postseasons[2005].series
                if item.playoff_round == row.round and names[item.team_a] == row.home_team
            )
            assert row.visitor == names[match.team_b] and row.winner == names[match.winner]
            assert (row.home_abbreviation, row.visitor_abbreviation) == (
                short[match.team_a],
                short[match.team_b],
            )
            assert row.result == f"{match.a_wins}-{match.b_wins}" and row.games == len(match.games)
            assert row.favourite == (row.home_team if row.probability >= 0.5 else row.visitor)
            assert bool(row.favourite_won) == (row.favourite == row.winner)
        assert table["round_name"].iloc[-1] == "NBA Finals" and pd.isna(
            table["conference"].iloc[-1]
        )
        assert table["conference"].iloc[:14].notna().all()

    def test_on_the_fixture_store_most_series_lack_an_input(self, lab: Lab) -> None:
        table = lab.postseason.series("2025-26")
        assert len(table) == 15 and table["probability"].isna().sum() >= 13
        unknown = table[table["probability"].isna()]
        assert unknown["favourite"].isna().all() and unknown["favourite_won"].isna().all()
        assert unknown["winner"].notna().all()

    def test_nothing_on_record_is_an_empty_table(self, played: Lab) -> None:
        table = played.postseason.series("1999-00")
        assert table.empty and tuple(table.columns) == SERIES_COLUMNS


class TestEveryTeam:
    def test_thirty_teams_best_first(self, played: Lab) -> None:
        odds = played.postseason.season_odds(SEASON)
        assert tuple(odds.columns) == ODDS_COLUMNS and len(odds) == 30
        assert odds.index.name == "team_id" and odds["decided"].all()
        assert odds[TITLE].is_monotonic_decreasing
        chances = odds[[probability_key(key) for key in BRACKET_STAGE_KEYS]].to_numpy()
        assert np.all((chances > 0) & (chances < 1))
        assert np.all(np.diff(chances, axis=1) <= 1e-12)
        first = odds.iloc[0]
        outlook = played.postseason.outlook(
            float(first["net_rating"]), float(first["top_players"])
        ).stages.set_index("key")
        for key in BRACKET_STAGE_KEYS:
            assert first[probability_key(key)] == pytest.approx(outlook.at[key, "probability"])
            assert first[f"{probability_key(key)}_low"] == pytest.approx(outlook.at[key, "low"])
        assert set(odds["result"]) <= set(POSTSEASON_RESULTS)

    def test_teams_without_a_valued_player_have_no_chances(self, lab: Lab) -> None:
        odds = lab.postseason.season_odds("2025-26")
        assert len(odds) == 30
        # Boston and New York have player detail; a few others have a player who left them.
        known = set(odds.index[odds[TITLE].notna()])
        assert {BOS, NYK} <= known and len(known) <= 8
        assert odds[PLAYOFFS].isna().sum() >= 22
        assert odds["decided"].all() and odds["result"].notna().all()


class TestAnyTeam:
    def test_an_outlook_nests_with_intervals(self, played: Lab) -> None:
        outlook = played.postseason.outlook(5.0, 2.0)
        stages = outlook.stages
        assert tuple(stages.columns) == STAGE_COLUMNS
        assert list(stages["key"]) == list(BRACKET_STAGE_KEYS)
        assert (outlook.net_rating, outlook.top_players, outlook.error) == (5.0, 2.0, None)
        assert stages["probability"].is_monotonic_decreasing
        assert (stages["low"] <= stages["probability"]).all()
        assert (stages["probability"] <= stages["high"]).all()
        assert stages["label"].iloc[0] == "Made the playoffs"

    def test_without_top_player_quality_the_typical_is_taken(self, played: Lab) -> None:
        outlook = played.postseason.outlook(5.0)
        typical = played.postseason.typical_top(5.0)
        assert outlook.top_players == pytest.approx(typical)
        assert typical == pytest.approx(played.postseason.model().typical_top.at(5.0))

    def test_an_error_on_the_rating_is_averaged_over(self, played: Lab) -> None:
        sure = played.postseason.outlook(8.0, 2.0)
        unsure = played.postseason.outlook(8.0, 2.0, error=3.0)
        assert unsure.error == 3.0
        assert unsure.stages["probability"].iloc[0] < sure.stages["probability"].iloc[0]

    def test_the_curve_runs_over_the_ratings_drawn(self, played: Lab) -> None:
        curve = played.postseason.curve()
        assert list(curve["net_rating"]) == list(CURVE_RATINGS) and len(curve) == 45
        column = probability_key("made_playoffs")
        assert {column, f"{column}_low", f"{column}_high"} <= set(curve.columns)
        assert curve[column].is_monotonic_increasing
        held = played.postseason.curve(top_players=1.0)
        assert (held["top_players"] == 1.0).all()
        assert held.at[0, column] == pytest.approx(
            played.postseason.outlook(CURVE_RATINGS[0], 1.0).stages["probability"].iloc[0]
        )


class TestASubject:
    def test_a_real_team_is_read_as_a_team_of_its_strength(
        self, played: Lab, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        read = played.postseason.team(101, SEASON)
        assert not read.is_empty and (read.kind, read.key, read.season) == ("team", 101, SEASON)
        assert read.name == played.team_labels().at[101, "full_name"] and read.error is None
        net, top = team_strengths(postseason_league[2], 2005)[101]
        assert read.net_rating == pytest.approx(net) and read.top_players == pytest.approx(top)
        assert len(read.top_names) == 3 and all(
            name.startswith("Player ") for name in read.top_names
        )
        expected = played.postseason.outlook(read.net_rating, read.top_players).stages
        pd.testing.assert_frame_equal(read.outlook.stages, expected)
        assert "net rating" in read.note

    def test_a_team_without_valued_players_or_statistics_says_so(self, lab: Lab) -> None:
        early = lab.postseason.team(BOS, "1996-97")
        assert early.is_empty and early.net_rating is not None and early.top_players is None
        assert "has been valued" in early.note
        nobody = lab.postseason.team(999, "2025-26")
        assert nobody.is_empty and "no statistics" in nobody.note
        boston = lab.postseason.team(BOS, "2025-26")
        assert not boston.is_empty and len(boston.top_names) == 3

    def test_a_built_roster_is_the_sum_of_its_parts_with_the_models_error(
        self, scratch_lab: Lab
    ) -> None:
        roster = scratch_lab.builder.create("Outlook roster")
        for player in (TATUM, BROWN, PRITCHARD, WHITE):
            scratch_lab.builder.add_player(roster, player)
        read = scratch_lab.postseason.roster(roster)
        fit = scratch_lab.fit.roster(roster)
        assert not read.is_empty
        assert (read.kind, read.key, read.name, read.season) == (
            "roster",
            roster,
            "Outlook roster",
            "2025-26",
        )
        assert read.net_rating == pytest.approx(fit.parts.impact) and read.error == fit.parts.error
        best = fit.members["impact"].dropna().nlargest(3)
        assert read.top_players == pytest.approx(best.mean())
        assert read.top_names == tuple(fit.members.loc[best.index, "player_name"])
        assert read.outlook.error == read.error and "added up" in read.note

    def test_a_roster_with_nobody_valued_says_so(self, scratch_lab: Lab) -> None:
        roster = scratch_lab.builder.create("Retired")
        scratch_lab.builder.add_player(roster, ABDELNABY)
        read = scratch_lab.postseason.roster(roster)
        assert read.is_empty and "no strength to read" in read.note
