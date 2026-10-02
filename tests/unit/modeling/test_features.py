"""Features: who played for whom, and what each season looks like to the model."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.modeling.value.features import (
    COMPONENT_KEYS,
    COMPONENTS,
    FEATURE_KEYS,
    FEATURES,
    RIVAL_KEYS,
    STINT_COLUMNS,
    component,
    features_of,
    season_features,
    start_years,
    stints,
)
from tests.league import LEAGUE_RATING, TEAM_MINUTES, SyntheticLeague
from tests.value_reference import season_known


@pytest.fixture(scope="module")
def played(exact_tables) -> pd.DataFrame:
    return stints(
        exact_tables["player_seasons"],
        exact_tables["player_game_logs"],
        exact_tables["team_seasons"],
    )


@pytest.fixture(scope="module")
def features(exact_tables, played) -> pd.DataFrame:
    return season_features(exact_tables["player_seasons"], exact_tables["team_seasons"], played)


class TestTheCatalog:
    def test_every_feature_belongs_to_a_component_and_is_explained(self) -> None:
        assert len(set(FEATURE_KEYS)) == len(FEATURE_KEYS) == 15
        for feature in FEATURES:
            assert feature.component in COMPONENT_KEYS
            assert feature.description.endswith(".") and feature.label[0].isupper()

    def test_every_component_has_features_and_together_they_cover_them_all(self) -> None:
        covered = [key for part in COMPONENT_KEYS for key in features_of(part)]
        assert sorted(covered) == sorted(FEATURE_KEYS)
        for part in COMPONENTS:
            assert features_of(part.key), part.key
            assert part.description.endswith(".")
            assert component(part.key) is part

    def test_an_unknown_component_is_an_error(self) -> None:
        with pytest.raises(KeyError, match="no component named 'luck'"):
            component("luck")

    def test_start_years(self) -> None:
        labels = pd.Series(["1999-00", "2025-26"])
        assert start_years(labels).tolist() == [1999, 2025]


class TestStints:
    def test_one_row_for_each_player_and_team_as_the_league_was_drawn(
        self, played: pd.DataFrame, exact_league: SyntheticLeague
    ) -> None:
        assert tuple(played.columns) == STINT_COLUMNS
        expected = {
            (year, stint.team_id, stint.player_id): stint.minutes
            for year in exact_league.years
            for stint in exact_league.stints[year]
        }
        found = {
            (row.start, row.team_id, row.player_id): row.minutes for row in played.itertuples()
        }
        assert found.keys() == expected.keys()
        for key, minutes in expected.items():
            assert found[key] == pytest.approx(minutes, abs=1e-9), key

    def test_share_is_minutes_over_the_teams_game_minutes(self, played: pd.DataFrame) -> None:
        assert np.allclose(played["share"], played["minutes"] / TEAM_MINUTES)
        assert (played["team_games"] == 82).all()
        assert 0 < played["share"].max() <= 1

    def test_a_teams_shares_add_up_to_five(self, played: pd.DataFrame) -> None:
        totals = played.groupby(["season", "team_id"])["share"].sum()
        assert len(totals) == 90
        assert np.allclose(totals, 5.0, atol=1e-3)

    def test_a_team_season_that_is_not_on_record_has_no_share(self, exact_tables) -> None:
        teams = exact_tables["team_seasons"]
        gone = (teams["season"] == "2003-04") & (teams["team_id"] == 101)
        found = stints(
            exact_tables["player_seasons"], exact_tables["player_game_logs"], teams[~gone]
        )
        missing = found[(found["season"] == "2003-04") & (found["team_id"] == 101)]
        assert len(missing) >= 11 and missing["share"].isna().all()
        assert found.loc[found["team_id"] != 101, "share"].notna().all()

    def test_only_the_regular_season_counts(self, exact_tables, played: pd.DataFrame) -> None:
        seasons = exact_tables["player_seasons"]
        playoffs = seasons.head(20).assign(season_type="playoffs")
        logs = exact_tables["player_game_logs"]
        playoff_logs = logs.head(30).assign(
            season_type="playoffs", game_id=lambda rows: "P" + rows["game_id"]
        )
        found = stints(
            pd.concat([seasons, playoffs]),
            pd.concat([logs, playoff_logs]),
            exact_tables["team_seasons"],
        )
        pd.testing.assert_frame_equal(found, played)


class TestSeasonFeatures:
    def test_one_row_per_player_per_regular_season(self, features, exact_league) -> None:
        lines = sum(len(exact_league.lines[year]) for year in exact_league.years)
        assert len(features) == lines
        assert not features.duplicated(["season", "player_id"]).any()
        assert features[[*FEATURE_KEYS, *RIVAL_KEYS]].notna().all().all()

    def test_every_feature_matches_the_definitions_worked_by_hand(
        self, features: pd.DataFrame, exact_league: SyntheticLeague
    ) -> None:
        by_key = features.set_index(["start", "player_id"])
        for year in exact_league.years:
            for player, known in season_known(exact_league, year).items():
                row = by_key.loc[(year, player)]
                for name, value in known.features.items():
                    assert row[name] == pytest.approx(value, abs=1e-9), (year, player, name)
                assert row["mpg_centred"] == pytest.approx(known.mpg_centred, abs=1e-9)
                assert row["evidence_minutes"] == pytest.approx(known.evidence)
                assert row["minutes"] == pytest.approx(known.minutes)
                assert row["age"] == known.age

    def test_the_league_average_of_every_box_feature_is_zero(
        self, features: pd.DataFrame, exact_tables
    ) -> None:
        # Weighted by possessions on the court, which is how the league rate is pooled.
        seasons = exact_tables["player_seasons"].set_index(["season", "player_id"])
        possessions = seasons["possessions"].astype("float64").fillna(0.0)
        weight = possessions.reindex(
            pd.MultiIndex.from_frame(features[["season", "player_id"]])
        ).to_numpy()
        box = [
            key
            for key in FEATURE_KEYS
            if key not in features_of("on_court") + features_of("team_context")
        ]
        assert len(box) == 11
        for key in box:
            totals = (features[key] * weight).groupby(features["season"]).sum()
            assert np.allclose(totals / weight.sum(), 0.0, atol=1e-9), key

    def test_minutes_per_game_is_centred_on_the_seasons_minutes_weighted_mean(
        self, features: pd.DataFrame
    ) -> None:
        weighted = (features["mpg_centred"] * features["minutes"]).groupby(features["season"]).sum()
        assert np.allclose(weighted, 0.0, atol=1e-6)
        assert features["minutes_per_game"].between(1, 48).all()

    def test_a_traded_player_carries_both_teams_results_by_minutes(
        self, features: pd.DataFrame, exact_league: SyntheticLeague
    ) -> None:
        year = exact_league.years[2]
        counts: dict[int, list] = {}
        for stint in exact_league.stints[year]:
            counts.setdefault(stint.player_id, []).append(stint)
        player, both = next((p, s) for p, s in counts.items() if len(s) == 2)
        minutes = sum(stint.minutes for stint in both)
        expected = (
            sum(stint.minutes * exact_league.ratings[year][stint.team_id][0] for stint in both)
            / minutes
        )
        row = features[(features["start"] == year) & (features["player_id"] == player)].iloc[0]
        assert row["team_off"] == pytest.approx(expected)
        ratings = [exact_league.ratings[year][stint.team_id][0] for stint in both]
        assert min(ratings) < row["team_off"] < max(ratings)

    def test_on_court_results_are_measured_against_the_players_own_teams(
        self, features: pd.DataFrame, exact_tables
    ) -> None:
        seasons = exact_tables["player_seasons"].set_index(["season", "player_id"])
        key = pd.MultiIndex.from_frame(features[["season", "player_id"]])
        on_court = seasons["off_rating"].reindex(key).to_numpy() - LEAGUE_RATING
        counted = ~np.isnan(on_court)
        assert np.allclose((features["rel_off"] + features["team_off"])[counted], on_court[counted])

    def test_a_player_with_nothing_counted_is_all_zeros_and_no_evidence(
        self, features: pd.DataFrame, exact_tables
    ) -> None:
        seasons = exact_tables["player_seasons"]
        uncounted = seasons[seasons["possessions"].isna()]
        assert len(uncounted) == 9  # one a season
        rows = features.merge(uncounted[["season", "player_id"]], on=["season", "player_id"])
        assert (rows[[*FEATURE_KEYS, *RIVAL_KEYS]] == 0).all().all()
        assert (rows["evidence_minutes"] == 0).all() and (rows["minutes"] == 1.0).all()
        counted = features[features["evidence_minutes"] > 0]
        assert (counted["evidence_minutes"] == counted["minutes"]).all()

    def test_zero_possessions_is_as_good_as_none(self, exact_tables, played, features) -> None:
        seasons = exact_tables["player_seasons"].copy()
        seasons["possessions"] = seasons["possessions"].fillna(0)
        again = season_features(seasons, exact_tables["team_seasons"], played)
        pd.testing.assert_frame_equal(again, features)

    def test_what_the_model_has_to_beat_is_taken_as_published(
        self, features: pd.DataFrame, exact_tables
    ) -> None:
        seasons = exact_tables["player_seasons"].set_index(["season", "player_id"])
        key = pd.MultiIndex.from_frame(features[["season", "player_id"]])
        counted = seasons["possessions"].reindex(key).notna().to_numpy()
        published = seasons.reindex(key)
        assert np.allclose(features["on_court_net"][counted], published["net_rating"][counted])
        assert np.allclose(
            features["pie"][counted], published["player_impact_estimate"][counted] - 0.1
        )
        per_100 = (
            100 * published["plus_minus"].astype(float) / published["possessions"].astype(float)
        )
        assert np.allclose(features["plus_minus_100"][counted], per_100[counted])

    def test_no_players_gives_no_rows(self, exact_tables) -> None:
        empty = exact_tables["player_seasons"].iloc[0:0]
        none = stints(
            empty, exact_tables["player_game_logs"].iloc[0:0], exact_tables["team_seasons"]
        )
        assert none.empty and tuple(none.columns) == STINT_COLUMNS
        assert season_features(empty, exact_tables["team_seasons"], none).empty
