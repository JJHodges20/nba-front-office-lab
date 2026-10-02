"""Scoring: a fitted model applied to the tables, checked against the slow way."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.schema import conform_frame
from front_office.domain.tables.value import PART_COLUMNS, PLAYER_VALUE_SCORES
from front_office.domain.value_model import ValueModel, ValueSpec
from front_office.modeling.value import ModelMismatch, check_terms, score_players
from front_office.modeling.value.wins import wins_per_net_point
from tests.league import GAMES, TEAM_MINUTES, SyntheticLeague
from tests.value_reference import (
    AVAILABILITY,
    DEFENSE,
    OFFENSE,
    PARTS,
    entering,
    estimate,
    planted_league,
    planted_model,
    season_impacts,
    terms,
)

REPLACEMENT = -2.0


@pytest.fixture(scope="module")
def model(spec: ValueSpec) -> ValueModel:
    return planted_model(spec, replacement_level=REPLACEMENT)


@pytest.fixture(scope="module")
def scores(exact_tables, model: ValueModel) -> pd.DataFrame:
    return score_players(exact_tables, model)


def season(scores: pd.DataFrame, year: int) -> pd.DataFrame:
    return scores[scores["season"] == f"{year}-{(year + 1) % 100:02d}"].set_index("player_id")


class TestShape:
    def test_the_rows_satisfy_the_tables_contract(self, scores: pd.DataFrame) -> None:
        assert tuple(scores.columns) == PLAYER_VALUE_SCORES.column_names
        conformed = conform_frame(scores, PLAYER_VALUE_SCORES)
        assert len(conformed) == len(scores)
        assert (scores["model_version"] == "r1").all()

    def test_every_season_played_has_a_row_and_an_impact(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague
    ) -> None:
        for year in exact_league.years:
            rows = season(scores, year)
            assert set(rows.index) == {line.player_id for line in exact_league.lines[year]}
            assert rows["impact"].notna().all()

    def test_the_season_after_the_last_is_projected_for_everyone_with_a_past(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        ahead = season(scores, 2009)
        known = entering(exact_league, 2009, spec)
        assert set(ahead.index) == set(known)
        played = ["impact", "impact_offense", "impact_defense", *PART_COLUMNS]
        assert ahead[[*played, "wins_added", "minutes_share", "reliability"]].isna().all().all()
        assert ahead[["projected_impact", "projected_share", "projected_wins"]].notna().all().all()
        assert scores["season"].max() == "2009-10"

    def test_rows_are_in_season_then_player_order(self, scores: pd.DataFrame) -> None:
        ordered = scores.sort_values(["season", "player_id"], ignore_index=True)
        pd.testing.assert_frame_equal(scores, ordered)
        assert not scores.duplicated(["player_id", "season"]).any()

    def test_no_players_no_rows(self, exact_tables, model: ValueModel) -> None:
        empty = {name: frame.iloc[0:0] for name, frame in exact_tables.items()}
        found = score_players(empty, model)
        assert found.empty and tuple(found.columns) == PLAYER_VALUE_SCORES.column_names

    def test_a_model_with_other_terms_is_refused(self, exact_tables, model: ValueModel) -> None:
        fewer = model.model_copy(update={"terms": model.terms[1:]})
        with pytest.raises(ModelMismatch, match=r"missing terms \['score_eff'\]"):
            score_players(exact_tables, fewer)
        renamed = model.terms[0].model_copy(update={"key": "hustle"})
        other = model.model_copy(update={"terms": (renamed, *model.terms[1:])})
        with pytest.raises(ModelMismatch, match=r"unknown terms \['hustle'\].*fol value fit"):
            check_terms(other)
        check_terms(model)


class TestSeasonImpact:
    def test_every_player_matches_the_definitions_worked_by_hand(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        for year in (2000, 2004, 2008):
            rows = season(scores, year)
            for player, expected in season_impacts(exact_league, year, spec).items():
                row = rows.loc[player]
                assert row["impact"] == pytest.approx(expected["impact"], abs=1e-9)
                assert row["impact_offense"] == pytest.approx(expected["offense"], abs=1e-9)
                assert row["impact_defense"] == pytest.approx(expected["defense"], abs=1e-9)
                assert row["reliability"] == pytest.approx(expected["reliability"])
                for part in (*PARTS, "baseline"):
                    found = row[f"impact_from_{part}"]
                    assert found == pytest.approx(expected[part], abs=1e-9), (player, part)

    def test_the_parts_add_up_to_the_impact_and_so_do_the_sides(self, scores) -> None:
        played = scores[scores["impact"].notna()]
        assert np.allclose(played[list(PART_COLUMNS)].sum(axis=1), played["impact"])
        assert np.allclose(played["impact_offense"] + played["impact_defense"], played["impact"])

    def test_the_average_minute_is_zero_in_every_season_on_both_sides(
        self, scores: pd.DataFrame, exact_tables
    ) -> None:
        minutes = exact_tables["player_seasons"][["player_id", "season", "minutes"]]
        joined = scores.merge(minutes, on=["player_id", "season"])
        for column in ("impact", "impact_offense", "impact_defense"):
            weighted = (joined[column] * joined["minutes"]).groupby(joined["season"]).sum()
            assert np.allclose(weighted, 0.0, atol=1e-6), column

    def test_a_player_with_nothing_counted_is_all_baseline(self, scores, exact_tables) -> None:
        seasons = exact_tables["player_seasons"]
        uncounted = seasons[seasons["possessions"].isna()][["player_id", "season"]]
        rows = scores.merge(uncounted, on=["player_id", "season"])
        assert len(rows) == 9
        assert (rows["reliability"] == 0).all()
        assert (rows[list(PART_COLUMNS[:-1])] == 0).all().all()
        assert np.allclose(rows["impact_from_baseline"], rows["impact"])
        # A minute a game is the bottom of anyone's bench, and is rated as such.
        assert (rows["impact"] < -4).all()

    def test_a_season_is_described_as_it_was_whatever_the_players_age(
        self, exact_tables, spec: ValueSpec
    ) -> None:
        young = planted_model(spec, offense={**OFFENSE, "age": -5.0})
        plain = planted_model(spec)
        columns = ["impact", "impact_offense", *PART_COLUMNS]
        pd.testing.assert_frame_equal(
            score_players(exact_tables, young)[columns], score_players(exact_tables, plain)[columns]
        )


class TestProjection:
    def test_every_player_matches_the_definitions_worked_by_hand(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        for year in (2001, 2005, 2009):
            rows = season(scores, year)
            known = entering(exact_league, year, spec)
            for player in rows.index:
                player_terms = terms(known.get(player), spec)
                row = rows.loc[player]
                assert row["projected_offense"] == pytest.approx(estimate(player_terms, OFFENSE))
                assert row["projected_defense"] == pytest.approx(estimate(player_terms, DEFENSE))
                assert row["projected_impact"] == pytest.approx(
                    row["projected_offense"] + row["projected_defense"]
                )

    def test_a_player_with_no_earlier_season_gets_the_new_player_level(
        self, scores: pd.DataFrame
    ) -> None:
        first = season(scores, 2000)
        assert (first["projection_seasons"] == 0).all()
        assert first["projection_reliability"].isna().all()
        assert np.allclose(first["projected_offense"], OFFENSE["new_player"])
        assert np.allclose(first["projected_defense"], DEFENSE["new_player"])
        later = season(scores, 2005)
        assert set(later["projection_seasons"]) == {0, 1, 2, 3}
        seen = later[later["projection_seasons"] > 0]
        assert seen["projection_reliability"].between(0, 1).all()

    def test_how_much_and_how_far_back_the_projection_reaches(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        rows = season(scores, 2006)
        for player, known in entering(exact_league, 2006, spec).items():
            if player in rows.index:
                assert rows.loc[player, "projection_seasons"] == known.seasons
                assert rows.loc[player, "projection_reliability"] == pytest.approx(
                    known.reliability(spec)
                )

    def test_age_is_published_where_played_and_carried_forward_where_not(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague
    ) -> None:
        played = season(scores, 2008)
        ages = {line.player_id: line.age for line in exact_league.lines[2008]}
        assert played["age"].to_dict() == ages
        ahead = season(scores, 2009)
        still = [player for player in ahead.index if player in ages]
        assert still and all(ahead.loc[player, "age"] == ages[player] + 1 for player in still)
        assert str(scores["age"].dtype) == "Int64"

    def test_a_season_in_progress_projects_the_players_not_yet_seen_in_it(
        self, spec: ValueSpec, model: ValueModel
    ) -> None:
        league = planted_league(spec)
        league.unfinished = {2008}
        tables = league.tables()
        last = "2008-09"
        absent = {line.player_id for line in league.lines[2007]} & {
            line.player_id for line in league.lines[2008]
        }
        gone = sorted(absent)[:5]
        for name in ("player_seasons", "player_game_logs"):
            frame = tables[name]
            tables[name] = frame[~((frame["season"] == last) & frame["player_id"].isin(gone))]
        rows = score_players(tables, model)
        waiting = rows[(rows["season"] == last) & rows["player_id"].isin(gone)]
        assert len(waiting) == 5
        assert waiting["impact"].isna().all() and waiting["projected_impact"].notna().all()
        assert waiting["projection_seasons"].min() >= 1
        # Seasons before the newest are history: nobody is projected into a season
        # missed. And the season after an unfinished one is not looked at yet.
        earlier = rows[rows["season"] < last]
        assert earlier["impact"].notna().all()
        assert rows["season"].max() == last

    def test_a_finished_season_holds_only_the_players_who_played_in_it(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague
    ) -> None:
        last = season(scores, 2008)
        assert set(last.index) == {line.player_id for line in exact_league.lines[2008]}
        assert last["impact"].notna().all()


class TestWins:
    def test_wins_added_is_impact_over_replacement_for_the_minutes_played(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague, exact_tables, spec: ValueSpec
    ) -> None:
        per_point = wins_per_net_point(exact_tables["team_seasons"], window=spec.wins_window)
        rows = season(scores, 2005)
        impacts = season_impacts(exact_league, 2005, spec)
        for player in list(rows.index)[::7]:
            share = sum(
                stint.minutes / TEAM_MINUTES
                for stint in exact_league.stints[2005]
                if stint.player_id == player
            )
            expected = (impacts[player]["impact"] - REPLACEMENT) * share * per_point["2005-06"]
            assert rows.loc[player, "minutes_share"] == pytest.approx(share)
            assert rows.loc[player, "wins_added"] == pytest.approx(expected)

    def test_a_shortened_season_is_worth_fewer_wins(
        self, exact_tables, model: ValueModel, scores: pd.DataFrame
    ) -> None:
        tables = dict(exact_tables)
        teams = tables["team_seasons"].copy()
        short = teams["season"] == "2005-06"
        # Fifty games, as after a lockout: fewer minutes for the team, so the same
        # minutes are a larger share of them, and a shorter season to win games in.
        teams.loc[short, "games_played"] = 50
        teams.loc[short, "wins"] = (teams.loc[short, "wins"] * 50 / GAMES).round().astype(int)
        teams.loc[short, "losses"] = 50 - teams.loc[short, "wins"]
        teams.loc[short, "minutes"] = 50 * 48.0
        tables["team_seasons"] = teams
        found = season(score_players(tables, model), 2005)
        full = season(scores, 2005)
        assert np.allclose(found["minutes_share"], full["minutes_share"] * GAMES / 50)
        # The share grows by 82/50 and the season shrinks by 50/82: wins per point is
        # all that moves, with the records of the shortened season.
        ratio = (found["wins_added"] / full["wins_added"]).dropna()
        assert ratio.std() < 1e-9 and ratio.iloc[0] == pytest.approx(1.0, abs=0.1)

    def test_projected_wins_are_projection_over_replacement_for_projected_minutes(
        self, scores: pd.DataFrame, exact_tables, spec: ValueSpec
    ) -> None:
        per_point = wins_per_net_point(exact_tables["team_seasons"], window=spec.wins_window)
        for label in ("2005-06", "2009-10"):
            rows = scores[scores["season"] == label]
            # A season not yet played takes the newest figure there is.
            slope = per_point.get(label, per_point.iloc[-1])
            expected = (rows["projected_impact"] - REPLACEMENT) * rows["projected_share"] * slope
            assert np.allclose(rows["projected_wins"], expected)

    def test_projected_share_follows_the_minutes_model(
        self, scores: pd.DataFrame, exact_league: SyntheticLeague
    ) -> None:
        rows = season(scores, 2006)
        shares = {
            year: {
                player: sum(
                    stint.minutes / TEAM_MINUTES
                    for stint in exact_league.stints[year]
                    if stint.player_id == player
                )
                for player in {stint.player_id for stint in exact_league.stints[year]}
            }
            for year in (2003, 2004, 2005)
        }
        for player in list(rows.index)[::5]:
            age = float(rows.loc[player, "age"])
            expected = (
                AVAILABILITY["intercept"]
                + AVAILABILITY["share_1"] * shares[2005].get(player, 0.0)
                + AVAILABILITY["share_2"] * shares[2004].get(player, 0.0)
                + AVAILABILITY["share_3"] * shares[2003].get(player, 0.0)
                + AVAILABILITY["years_over_30"] * max(age - 30, 0)
                + AVAILABILITY["years_under_25"] * max(25 - age, 0)
            )
            assert rows.loc[player, "projected_share"] == pytest.approx(min(max(expected, 0), 1))

    def test_without_team_records_there_are_no_wins_but_there_are_ratings(
        self, exact_tables, model: ValueModel
    ) -> None:
        tables = dict(exact_tables)
        tables["team_seasons"] = exact_tables["team_seasons"].assign(games_played=0)
        found = score_players(tables, model)
        assert found["wins_added"].isna().all() and found["projected_wins"].isna().all()
        assert found["impact"].notna().any()
