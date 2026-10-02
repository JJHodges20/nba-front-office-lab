"""Benchmark research on the fixture lab: the 1996-97, 2012-13 and 2025-26 seasons."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from front_office.analytics.benchmarks import EVERY_TEAM, STAGE_KEYS, STAGES
from front_office.domain.eras import Era
from front_office.services import MEASURES, Lab, floor
from front_office.services.benchmarks import (
    DATASET_COLUMNS,
    PROFILE_KEYS,
    SEPARATION_KEYS,
    VALUE_KEYS,
)

FIXTURE_SEASONS = ("1996-97", "2012-13", "2025-26")
NINETIES = Era.between("1990-91", "1995-96")


@pytest.fixture(scope="module")
def everything(lab: Lab) -> Era:
    return lab.benchmarks.era("all")


class TestEras:
    def test_the_configured_eras_are_offered_in_order(self, lab: Lab) -> None:
        assert [era.key for era in lab.benchmarks.eras] == [
            "all",
            "last_10",
            "last_5",
            "modern",
            "play_in",
        ]
        assert lab.benchmarks.era("modern").first_season == "2015-16"
        with pytest.raises(KeyError, match="no era named 'ancient'"):
            lab.benchmarks.era("ancient")

    def test_research_uses_the_completed_seasons(self, lab: Lab) -> None:
        assert lab.benchmarks.seasons() == FIXTURE_SEASONS

    def test_an_era_as_it_falls_on_the_seasons_on_record(self, lab: Lab, everything: Era) -> None:
        view = lab.benchmarks.view(everything)
        assert view.seasons == FIXTURE_SEASONS and view.teams == 89
        assert view.span == "1996-97 to 2025-26"
        assert view.reached == dict(zip(STAGE_KEYS, [52, 48, 24, 12, 6, 3], strict=True))

    def test_an_era_never_reaches_past_the_data(self, lab: Lab) -> None:
        last_ten = lab.benchmarks.view(lab.benchmarks.era("last_10"))
        assert last_ten.seasons == FIXTURE_SEASONS
        modern = lab.benchmarks.view(lab.benchmarks.era("modern"))
        assert modern.seasons == ("2025-26",) and modern.span == "2025-26"
        assert (modern.teams, modern.reached["won_championship"]) == (30, 1)
        assert modern.reached["reached_postseason"] == 20

    def test_a_span_chosen_on_the_spot(self, lab: Lab) -> None:
        view = lab.benchmarks.view(Era.between("1996-97", "2012-13"))
        assert view.seasons == ("1996-97", "2012-13") and view.teams == 59

    def test_an_era_with_no_seasons_is_empty_not_an_error(self, lab: Lab) -> None:
        view = lab.benchmarks.view(NINETIES)
        assert view.seasons == () and view.teams == 0 and view.span == "no completed seasons"
        assert set(view.reached.values()) == {0}

    def test_stages_and_metrics_are_the_analytics_own(self, lab: Lab) -> None:
        assert lab.benchmarks.stages == STAGES
        assert "wins_per_82" in lab.benchmarks.metrics and "net_rating" in lab.benchmarks.metrics


class TestDataset:
    def test_every_team_season_newest_first_best_record_first(
        self, lab: Lab, everything: Era
    ) -> None:
        dataset = lab.benchmarks.dataset(everything)
        assert list(dataset.columns) == list(DATASET_COLUMNS)
        assert len(dataset) == 89
        assert dataset["season"].iloc[0] == "2025-26" and dataset["season"].iloc[-1] == "1996-97"
        for _, teams in dataset.groupby("season"):
            assert teams["wins_per_82"].is_monotonic_decreasing

    def test_each_row_says_how_the_season_ended(self, lab: Lab, everything: Era) -> None:
        dataset = lab.benchmarks.dataset(everything)
        champions = dataset[dataset["won_championship"]]
        assert champions["team_name"].tolist() == [
            "New York Knicks",
            "Miami Heat",
            "Chicago Bulls",
        ]
        assert set(champions["postseason_result"]) == {"Champion"}
        assert champions["wins_per_82"].tolist() == [53, 66, 69]
        assert champions["conference_rank"].tolist() == [3, 1, 1]
        assert dataset["postseason_result"].notna().all()

    def test_narrowed_to_the_era(self, lab: Lab) -> None:
        dataset = lab.benchmarks.dataset(lab.benchmarks.era("play_in"))
        assert set(dataset["season"]) == {"2025-26"} and len(dataset) == 30
        assert len(lab.benchmarks.dataset(NINETIES)) == 0


class TestRates:
    def test_bands_of_five_wins_cover_every_team(self, lab: Lab, everything: Era) -> None:
        rates = lab.benchmarks.rates(everything, "wins_per_82")
        assert rates.columns[0] == "band"
        bands = rates.drop_duplicates("band")
        assert bands["teams"].sum() == 89
        assert (bands["upper"] - bands["lower"] == 5).all()
        assert bands["band"].iloc[0] == f"{bands['lower'].iloc[0]:g} to {bands['upper'].iloc[0]:g}"
        assert len(rates) == len(bands) * len(STAGES)

    def test_no_fixture_champion_won_fewer_than_fifty(self, lab: Lab, everything: Era) -> None:
        rates = lab.benchmarks.rates(everything, "wins_per_82")
        champions = rates[rates["stage"] == "won_championship"]
        assert champions.loc[champions["lower"] < 50, "reached"].sum() == 0
        assert champions["reached"].sum() == 3
        assert champions.set_index("band").at["65 to 70", "reached"] == 2

    def test_the_width_of_a_band_can_be_chosen(self, lab: Lab, everything: Era) -> None:
        wide = lab.benchmarks.rates(everything, "wins_per_82", width=10)
        usual = lab.benchmarks.rates(everything, "wins_per_82")
        assert wide["band"].nunique() < usual["band"].nunique()
        assert (
            (wide.drop_duplicates("band")["upper"] - wide.drop_duplicates("band")["lower"])
            .eq(10)
            .all()
        )

    def test_a_signed_measure_writes_its_bands_with_signs(self, lab: Lab, everything: Era) -> None:
        bands = lab.benchmarks.rates(everything, "net_rating")["band"].unique().tolist()
        assert "-2 to 0" in bands and "0 to +2" in bands and "+2 to +4" in bands

    def test_every_seed_is_a_band_of_its_own(self, lab: Lab, everything: Era) -> None:
        rates = lab.benchmarks.rates(everything, "conference_rank")
        seeds = rates.drop_duplicates("band").set_index("band")["teams"]
        assert seeds.index.tolist() == [str(seed) for seed in range(1, 16)]
        # Two conferences in three seasons make six teams a seed - except where the
        # 1996-97 standings left equal records on one place (two 2nds and no 3rd, two
        # 5ths, two 6ths and no 7th), and where a conference had fourteen teams.
        assert seeds.sum() == 89
        uneven = {seed: count for seed, count in seeds.items() if count != 6}
        assert uneven == {"2": 7, "3": 5, "5": 7, "7": 5, "15": 5}
        first = rates[(rates["band"] == "1") & (rates["stage"] == "won_championship")].iloc[0]
        assert (first["reached"], first["teams"]) == (2, 6)
        assert first["rate"] == pytest.approx(1 / 3)
        assert first["low"] < first["rate"] < first["high"]

    def test_shares_among_the_teams_that_reached_an_earlier_stage(
        self, lab: Lab, everything: Era
    ) -> None:
        league = lab.benchmarks.rates(everything, "wins_per_82")
        playoffs = lab.benchmarks.rates(everything, "wins_per_82", among="made_playoffs")
        assert playoffs.drop_duplicates("band")["teams"].sum() == 48
        made = playoffs[playoffs["stage"] == "made_playoffs"]
        assert (made["rate"] == 1.0).all() and (made["reached"] == made["teams"]).all()
        # The same teams won a round either way; only the field they are a share of changes.
        won = "won_a_round"
        assert (
            playoffs.loc[playoffs["stage"] == won, "reached"].sum()
            == league.loc[league["stage"] == won, "reached"].sum()
            == 24
        )
        band = "45 to 50"
        among = playoffs[(playoffs["band"] == band) & (playoffs["stage"] == won)].iloc[0]
        overall = league[(league["band"] == band) & (league["stage"] == won)].iloc[0]
        assert among["teams"] <= overall["teams"] and among["rate"] >= overall["rate"]
        with pytest.raises(KeyError, match="no stage named"):
            lab.benchmarks.rates(everything, "wins_per_82", among="won_the_lottery")

    def test_only_some_measures_are_offered(self, lab: Lab, everything: Era) -> None:
        assert [measure.key for measure in MEASURES] == [
            "wins_per_82",
            "net_rating",
            "point_diff_per_game",
            "rel_off_rating",
            "rel_def_rating",
            "conference_rank",
        ]
        for measure in MEASURES:
            assert len(lab.benchmarks.rates(everything, measure.key)) > 0
            assert measure.width is None or measure.width in measure.widths
        with pytest.raises(KeyError, match="not offered by 'pace'"):
            lab.benchmarks.rates(everything, "pace")

    def test_an_empty_era_has_no_rates(self, lab: Lab) -> None:
        for measure in ("wins_per_82", "conference_rank"):
            rates = lab.benchmarks.rates(NINETIES, measure)
            assert len(rates) == 0 and "band" in rates.columns


class TestProfiles:
    def test_values_for_era_safe_measures_and_ranks_for_the_rest(
        self, lab: Lab, everything: Era
    ) -> None:
        profiles = lab.benchmarks.profiles(everything)
        values = profiles[profiles["kind"] == "value"]
        ranks = profiles[profiles["kind"] == "rank"]
        assert set(values["metric"]) == set(VALUE_KEYS)
        assert set(ranks["metric"]) == set(PROFILE_KEYS)
        assert len(profiles) == (len(VALUE_KEYS) + len(PROFILE_KEYS)) * (len(STAGES) + 1)
        assert profiles["group_label"].iloc[0] == "Every team"
        assert set(profiles["group"]) == {EVERY_TEAM, *STAGE_KEYS}

    def test_the_ends_of_a_spread_are_named_teams(self, lab: Lab, everything: Era) -> None:
        profiles = lab.benchmarks.profiles(everything)
        champions = profiles[
            (profiles["group"] == "won_championship") & (profiles["kind"] == "value")
        ].set_index("metric")
        wins = champions.loc["wins_per_82"]
        assert (wins["teams"], wins["lowest"], wins["highest"]) == (3, 53, 69)
        assert wins["lowest_team"] == "2025-26 New York Knicks"
        assert wins["highest_team"] == "1996-97 Chicago Bulls"
        assert wins["group_label"] == "Won the championship"
        assert champions.at["conference_rank", "highest"] == 3
        # Chicago and Miami were both first seeds: an extreme that is shared names nobody.
        assert champions.at["conference_rank", "lowest_team"] == "2 teams"
        assert champions.at["conference_rank", "highest_team"] == "2025-26 New York Knicks"

    def test_league_ranks_of_the_champions(self, lab: Lab, everything: Era) -> None:
        profiles = lab.benchmarks.profiles(everything)
        ranks = profiles[
            (profiles["group"] == "won_championship") & (profiles["kind"] == "rank")
        ].set_index("metric")
        net = ranks.loc["net_rating"]
        assert (net["lowest"], net["highest"]) == (1, 5)
        assert net["lowest_team"] == "1996-97 Chicago Bulls"
        assert net["highest_team"] == "2025-26 New York Knicks"

    def test_an_empty_era_profiles_nobody(self, lab: Lab) -> None:
        profiles = lab.benchmarks.profiles(NINETIES)
        assert (profiles["teams"] == 0).all()
        assert (profiles["lowest_team"] == "").all()


class TestRankCounts:
    def test_how_many_champions_were_near_the_top(self, lab: Lab, everything: Era) -> None:
        counts = lab.benchmarks.rank_counts(everything)
        assert counts["basis"].unique().tolist() == [
            "Net rating",
            "Offensive rating",
            "Defensive rating",
            "Both ends",
        ]
        champions = counts[counts["group"] == "won_championship"].set_index(["basis", "cutoff"])
        assert champions.loc["Net rating", "inside"].to_dict() == {1: 1, 3: 2, 5: 3, 10: 3}
        assert champions.loc[("Both ends", 10), ["teams", "inside"]].tolist() == [3, 3]
        assert champions.loc["Both ends"].index.tolist() == [5, 10]

    def test_the_whole_field_is_there_for_comparison(self, lab: Lab, everything: Era) -> None:
        counts = lab.benchmarks.rank_counts(everything)
        field = counts[(counts["group"] == EVERY_TEAM) & (counts["basis"] == "Net rating")]
        assert field["group_label"].unique().tolist() == ["Every team"]
        # Three seasons: three league leaders, and thirty teams in a top ten.
        assert field.set_index("cutoff")["inside"].to_dict() == {1: 3, 3: 9, 5: 15, 10: 30}


class TestSeparation:
    def test_every_team_metric_highest_concordance_first(self, lab: Lab, everything: Era) -> None:
        table = lab.benchmarks.separation(everything, "made_conference_finals")
        assert set(table["metric"]) == set(SEPARATION_KEYS)
        assert table["concordance"].is_monotonic_decreasing
        assert list(table.columns[:4]) == ["metric", "label", "name", "category"]
        left_out = {"games_played", "wins", "losses", "conference_rank", "rel_off_rating"}
        assert not left_out & set(table["metric"])

    def test_overall_strength_leads_and_pace_trails(self, lab: Lab, everything: Era) -> None:
        table = lab.benchmarks.separation(everything, "made_conference_finals").set_index("metric")
        assert set(table.index[:3]) == {"net_rating", "point_diff_per_game", "win_pct"}
        assert table.at["net_rating", "concordance"] > 0.9
        assert abs(table.at["pace", "concordance"] - 0.5) < 0.2
        assert (table["reached"] == 12).all() and (table["others"] == 77).all()
        assert (table["seasons"] == 3).all()
        assert (
            (table["low"] <= table["concordance"]) & (table["concordance"] <= table["high"])
        ).all()

    def test_the_field_can_be_the_teams_of_an_earlier_stage(
        self, lab: Lab, everything: Era
    ) -> None:
        league = lab.benchmarks.separation(everything, "won_a_round").set_index("metric")
        playoffs = lab.benchmarks.separation(
            everything, "won_a_round", among="made_playoffs"
        ).set_index("metric")
        # Twenty-four teams won a round; the field shrinks from every other team to the
        # twenty-four playoff teams that did not.
        assert (league["reached"] == 24).all() and (league["others"] == 65).all()
        assert (playoffs["reached"] == 24).all() and (playoffs["others"] == 24).all()
        assert playoffs.at["net_rating", "pairs"] == 3 * 8 * 8
        # Beating the whole league on net rating is easier than beating the playoff field.
        assert playoffs.at["net_rating", "concordance"] < league.at["net_rating", "concordance"]
        assert playoffs.at["net_rating", "concordance"] > 0.6

    def test_the_field_must_be_an_earlier_stage(self, lab: Lab, everything: Era) -> None:
        for among in ("made_finals", "won_championship"):
            with pytest.raises(ValueError, match="an earlier stage"):
                lab.benchmarks.separation(everything, "made_finals", among=among)

    def test_the_same_question_gives_the_same_answer(self, lab: Lab, everything: Era) -> None:
        first = lab.benchmarks.separation(everything, "won_championship")
        again = lab.benchmarks.separation(everything, "won_championship")
        pd.testing.assert_frame_equal(first, again)

    def test_an_empty_era_has_nothing_to_compare(self, lab: Lab) -> None:
        table = lab.benchmarks.separation(NINETIES, "made_playoffs")
        assert len(table) == len(SEPARATION_KEYS)
        assert all(math.isnan(value) for value in table["concordance"])
        assert (table["pairs"] == 0).all()

    def test_an_unknown_stage_is_refused(self, lab: Lab, everything: Era) -> None:
        with pytest.raises(KeyError, match="no stage named"):
            lab.benchmarks.separation(everything, "won_the_lottery")


class TestSummary:
    def test_the_champions_in_a_few_figures(self, lab: Lab, everything: Era) -> None:
        summary = lab.benchmarks.summary(everything, "won_championship")
        assert summary.stage.short == "Champion"
        assert (summary.teams, summary.field, summary.seasons) == (3, 89, 3)
        assert (summary.fewest_wins, summary.fewest_wins_by) == (53, "2025-26 NYK")
        assert summary.median_wins == 66
        assert summary.median_net_rank == 2 and summary.worst_seed == 3
        assert (summary.top_five_net, summary.top_ten_both_ends) == (3, 3)

    def test_a_wider_stage_has_more_teams_and_a_lower_floor(
        self, lab: Lab, everything: Era
    ) -> None:
        playoffs = lab.benchmarks.summary(everything, "made_playoffs")
        champions = lab.benchmarks.summary(everything, "won_championship")
        assert playoffs.teams == 48 and playoffs.fewest_wins < champions.fewest_wins
        # Three seasons have fifteen top-five teams; all of them made the playoffs.
        assert playoffs.top_five_net == 15
        assert playoffs.top_ten_both_ends == 17
        assert playoffs.median_net_rating < champions.median_net_rating
        assert playoffs.worst_seed == 8
        # The play-in reaches down to the tenth place.
        assert lab.benchmarks.summary(everything, "reached_postseason").worst_seed == 10

    def test_a_shared_floor_says_how_many_share_it(self, lab: Lab, everything: Era) -> None:
        field = lab.benchmarks.dataset(everything)
        playoffs = field[field["made_playoffs"]]
        fewest = playoffs["wins_per_82"].min()
        sharing = int((playoffs["wins_per_82"] == fewest).sum())
        summary = lab.benchmarks.summary(everything, "made_playoffs")
        assert summary.fewest_wins == fewest
        expected = f"{sharing} teams" if sharing > 1 else summary.fewest_wins_by
        assert summary.fewest_wins_by == expected

    def test_an_empty_era_has_no_figures(self, lab: Lab) -> None:
        summary = lab.benchmarks.summary(NINETIES, "won_championship")
        assert (summary.teams, summary.field, summary.seasons) == (0, 0, 0)
        assert math.isnan(summary.fewest_wins) and summary.fewest_wins_by == ""
        assert (summary.top_five_net, summary.top_ten_both_ends) == (0, 0)

    def test_an_unknown_stage_is_refused(self, lab: Lab, everything: Era) -> None:
        with pytest.raises(KeyError, match="no stage named"):
            lab.benchmarks.summary(everything, "won_the_lottery")


class TestFloor:
    def test_the_lowest_band_a_champion_came_from(self, lab: Lab, everything: Era) -> None:
        rates = lab.benchmarks.rates(everything, "wins_per_82")
        found = floor(rates, "won_championship")
        assert found is not None and found.band == "50 to 55"
        below = rates[(rates["stage"] == "won_championship") & (rates["lower"] < 50)]
        assert found.teams_below == below["teams"].sum() > 50
        # None of that many still leaves room for a small long-run rate.
        assert 0 < found.ceiling < 0.08

    def test_an_earlier_stage_starts_lower(self, lab: Lab, everything: Era) -> None:
        rates = lab.benchmarks.rates(everything, "wins_per_82")
        playoffs, champions = floor(rates, "made_playoffs"), floor(rates, "won_championship")
        assert playoffs is not None and champions is not None
        assert playoffs.teams_below < champions.teams_below

    def test_nobody_reached_it(self, lab: Lab) -> None:
        assert floor(lab.benchmarks.rates(NINETIES, "wins_per_82"), "won_championship") is None

    def test_no_band_beneath_has_no_ceiling(self, lab: Lab, everything: Era) -> None:
        rates = lab.benchmarks.rates(everything, "wins_per_82")
        top_only = rates[rates["lower"] >= 65]
        found = floor(top_only, "won_championship")
        assert found is not None and found.teams_below == 0 and math.isnan(found.ceiling)


class TestHighlights:
    def test_two_metrics_for_every_team_season_with_what_they_reached(
        self, lab: Lab, everything: Era
    ) -> None:
        points = lab.benchmarks.highlights(everything, "rel_off_rating", "rel_def_rating")
        assert len(points) == 89
        assert {"season", "team_name", "rel_off_rating", "rel_def_rating", *STAGE_KEYS} <= set(
            points.columns
        )
        assert points["won_championship"].sum() == 3
        assert points["postseason_result"].notna().all()

    def test_the_same_metric_twice_is_one_column(self, lab: Lab, everything: Era) -> None:
        points = lab.benchmarks.highlights(everything, "net_rating", "net_rating")
        assert points.columns.tolist().count("net_rating") == 1
