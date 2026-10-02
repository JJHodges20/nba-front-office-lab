"""Benchmark research: on small hand-built histories, and on the fixture seasons."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from front_office.analytics.benchmarks import (
    BENCHMARK_METRICS,
    EVERY_TEAM,
    PROFILE_COLUMNS,
    QUANTILES,
    RANK_COUNT_COLUMNS,
    RANKED_KEYS,
    RATE_COLUMNS,
    RESEARCH_METRICS,
    SEPARATION_COLUMNS,
    STAGE_KEYS,
    STAGES,
    bands,
    rank_counts,
    research_frame,
    separation,
    stage,
    stage_counts,
    stage_profiles,
    stage_rates,
    wilson_interval,
)
from front_office.analytics.teams import TEAM_METRICS, team_season_metrics
from front_office.domain.schema import Provenance

BOS, CHI = 1610612738, 1610612741


def history(rows: list[dict]) -> pd.DataFrame:
    """A hand-built research frame: stage flags default to not reached."""
    frame = pd.DataFrame(rows)
    for key in STAGE_KEYS:
        if key not in frame:
            frame[key] = False
        frame[key] = frame[key].fillna(False).astype(bool)
    return frame


def interval(successes: int, trials: int, **options: float) -> tuple[float, float]:
    low, high = wilson_interval(pd.Series([successes]), pd.Series([trials]), **options)
    return float(low.iloc[0]), float(high.iloc[0])


@pytest.fixture(scope="module")
def frame(normalized) -> pd.DataFrame:
    """The three fixture seasons - 1996-97, 2012-13 and 2025-26 - as a research frame."""
    return research_frame(team_season_metrics(normalized["team_seasons"]))


class TestCatalog:
    def test_stages_run_from_the_postseason_to_the_title(self) -> None:
        assert STAGE_KEYS == (
            "reached_postseason",
            "made_playoffs",
            "won_a_round",
            "made_conference_finals",
            "made_finals",
            "won_championship",
        )
        assert [candidate.short for candidate in STAGES][-1] == "Champion"
        assert len({candidate.label for candidate in STAGES}) == len(STAGES)
        for candidate in STAGES:
            assert candidate.description.endswith(".")

    def test_a_stage_is_found_by_its_key(self) -> None:
        assert stage("made_finals").label == "Reached the NBA Finals"
        with pytest.raises(KeyError, match="no stage named 'won_it_all'"):
            stage("won_it_all")

    def test_research_adds_two_measures_to_the_team_metrics(self) -> None:
        assert RESEARCH_METRICS.keys == ("wins_per_82", "conference_rank")
        assert BENCHMARK_METRICS.keys == ("wins_per_82", "conference_rank", *TEAM_METRICS.keys)
        assert RESEARCH_METRICS["conference_rank"].higher_is_better is False
        assert RESEARCH_METRICS["conference_rank"].provenance is Provenance.MEASURED
        assert RESEARCH_METRICS["wins_per_82"].provenance is Provenance.DERIVED
        assert "conference_rank" not in RANKED_KEYS and "wins_per_82" in RANKED_KEYS


class TestResearchFrame:
    def test_one_row_per_decided_team_season(self, frame) -> None:
        assert len(frame) == 89
        assert frame.groupby("season").size().to_dict() == {
            "1996-97": 29,
            "2012-13": 30,
            "2025-26": 30,
        }
        assert not frame.duplicated(["season", "team_id"]).any()

    def test_every_season_has_one_champion_and_a_full_bracket(self, frame) -> None:
        reached = frame.groupby("season")[list(STAGE_KEYS)].sum()
        for season in reached.index:
            assert reached.loc[season, "made_playoffs":].tolist() == [16, 8, 4, 2, 1], season
        # Twenty teams reach the postseason once there is a play-in; sixteen before it.
        assert reached["reached_postseason"].to_dict() == {
            "1996-97": 16,
            "2012-13": 16,
            "2025-26": 20,
        }
        assert stage_counts(frame).to_dict() == dict(
            zip(STAGE_KEYS, [52, 48, 24, 12, 6, 3], strict=True)
        )

    def test_each_stage_contains_the_next(self, frame) -> None:
        for earlier, later in zip(STAGE_KEYS, STAGE_KEYS[1:], strict=False):
            assert not (frame[later] & ~frame[earlier]).any(), (earlier, later)
        for key in STAGE_KEYS:
            assert str(frame[key].dtype) == "bool", key

    def test_a_record_is_put_on_the_scale_of_a_full_season(self, frame) -> None:
        full = frame[frame["games_played"] == 82]
        assert (full["wins_per_82"] - full["wins"]).abs().max() < 1e-9
        short = frame[frame["games_played"] != 82]
        assert len(short) == 2  # the two teams whose 2012-13 game was never played
        assert (short["wins_per_82"] > short["wins"]).all()
        assert math.isclose(
            short["wins_per_82"].iloc[0], short["wins"].iloc[0] / 81 * 82, rel_tol=1e-12
        )

    def test_ranks_are_within_the_season_with_one_the_best(self, frame) -> None:
        for season, teams in frame.groupby("season"):
            best = teams.loc[teams["net_rating"].idxmax()]
            assert best["net_rating_rank"] == 1, season
            stingiest = teams.loc[teams["def_rating"].idxmin()]
            assert stingiest["def_rating_rank"] == 1, season
            assert teams["net_rating_rank"].max() <= len(teams)
            assert (teams["league_teams"] == len(teams)).all()
        for key in RANKED_KEYS:
            assert f"{key}_rank" in frame.columns, key
        assert (frame["wins_per_82_rank"] == frame["win_pct_rank"]).all()

    def test_the_bulls_of_1997_led_the_league_and_won(self, frame) -> None:
        bulls = frame[(frame["season"] == "1996-97") & (frame["team_id"] == CHI)].iloc[0]
        assert bulls["wins_per_82"] == 69 and bulls["won_championship"]
        assert bulls["net_rating_rank"] == 1 and bulls["conference_rank"] == 1

    def test_a_season_still_being_played_is_left_out(self, normalized) -> None:
        seasons = normalized["team_seasons"].copy()
        open_season = seasons["season"] == "2025-26"
        for column in ("made_play_in", "made_playoffs", "playoff_round_reached",
                       "made_conference_finals", "made_finals", "won_championship"):  # fmt: skip
            seasons[column] = seasons[column].where(~open_season)
        decided = research_frame(team_season_metrics(seasons))
        assert set(decided["season"]) == {"1996-97", "2012-13"} and len(decided) == 59

    def test_the_input_is_not_modified(self, normalized) -> None:
        metrics = team_season_metrics(normalized["team_seasons"])
        before = metrics.copy(deep=True)
        research_frame(metrics)
        pd.testing.assert_frame_equal(metrics, before)


class TestWilsonInterval:
    def test_half_of_ten(self) -> None:
        low, high = interval(5, 10)
        assert low == pytest.approx(0.2366, abs=1e-4) and high == pytest.approx(0.7634, abs=1e-4)

    def test_none_of_ten_is_not_certainly_never(self) -> None:
        low, high = interval(0, 10)
        assert low == 0.0
        assert high == pytest.approx(0.2775, abs=1e-4)

    def test_all_of_ten_is_not_certainly_always(self) -> None:
        low, high = interval(10, 10)
        assert high == 1.0
        assert low == pytest.approx(0.7225, abs=1e-4)

    def test_the_ends_are_exact_whatever_the_number_of_cases(self) -> None:
        # Left to floating point, "all of 13" would end at 0.9999999999999999.
        trials = pd.Series(range(1, 201))
        low, high = wilson_interval(trials, trials)
        assert (high == 1.0).all() and (low < 1.0).all()
        low, high = wilson_interval(trials * 0, trials)
        assert (low == 0.0).all() and (high > 0.0).all()

    def test_more_cases_narrow_it_around_the_same_share(self) -> None:
        few, many = interval(3, 10), interval(300, 1000)
        assert few[0] < many[0] < 0.3 < many[1] < few[1]
        assert many[1] - many[0] < 0.06

    def test_a_higher_confidence_is_wider(self) -> None:
        usual, strict = interval(5, 20), interval(5, 20, confidence=0.99)
        assert strict[0] < usual[0] and strict[1] > usual[1]

    def test_no_trials_has_no_interval(self) -> None:
        low, high = interval(0, 0)
        assert math.isnan(low) and math.isnan(high)

    def test_the_interval_always_holds_the_share_and_stays_in_bounds(self) -> None:
        trials = pd.Series([n for n in range(1, 40) for _ in range(n + 1)])
        successes = pd.Series([k for n in range(1, 40) for k in range(n + 1)])
        low, high = wilson_interval(successes, trials)
        share = successes / trials
        assert ((low <= share + 1e-12) & (share <= high + 1e-12)).all()
        assert (low >= 0).all() and (high <= 1).all()

    def test_confidence_is_a_share(self) -> None:
        for confidence in (0, 1, 95):
            with pytest.raises(ValueError, match="between 0 and 1"):
                interval(1, 2, confidence=confidence)


class TestBands:
    def test_bands_sit_on_multiples_of_the_width_and_cover_every_value(self) -> None:
        assert bands(pd.Series([37.2, 51.0, 68.9]), 5) == [35, 40, 45, 50, 55, 60, 65, 70]
        assert bands(pd.Series([-7.3, 11.8]), 2) == [-8, -6, -4, -2, 0, 2, 4, 6, 8, 10, 12]

    def test_a_value_on_an_edge_starts_the_band_above_it(self) -> None:
        assert bands(pd.Series([60.0, 70.0]), 5) == [60, 65, 70, 75]

    def test_fractional_widths_do_not_drift(self) -> None:
        assert bands(pd.Series([-0.31, 0.44]), 0.1) == [
            -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5,
        ]  # fmt: skip

    def test_no_values_no_bands(self) -> None:
        assert bands(pd.Series([None, float("nan")], dtype="float64"), 5) == []

    def test_the_width_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive width"):
            bands(pd.Series([1.0]), 0)


class TestStageRates:
    @pytest.fixture
    def teams(self) -> pd.DataFrame:
        return history(
            [
                {"wins": 30, "seed": 12},
                {"wins": 41, "seed": 9},
                {"wins": 44, "seed": 8, "reached_postseason": True, "made_playoffs": True},
                {"wins": 48, "seed": 6, "reached_postseason": True, "made_playoffs": True},
                {"wins": 55, "seed": 2, "reached_postseason": True, "made_playoffs": True,
                 "won_a_round": True},
                {"wins": 62, "seed": 1, "reached_postseason": True, "made_playoffs": True,
                 "won_a_round": True, "made_conference_finals": True, "made_finals": True,
                 "won_championship": True},
                {"wins": None, "seed": 1, "reached_postseason": True, "made_playoffs": True},
                {"wins": 99, "seed": 2},
            ]
        )  # fmt: skip

    def test_one_row_per_band_per_stage_lowest_band_first(self, teams) -> None:
        rates = stage_rates(teams, "wins", edges=[20, 40, 50, 70])
        assert list(rates.columns) == list(RATE_COLUMNS)
        assert len(rates) == 3 * len(STAGES)
        assert rates["lower"].drop_duplicates().tolist() == [20, 40, 50]
        assert rates["stage"].head(len(STAGES)).tolist() == list(STAGE_KEYS)

    def test_counts_and_shares(self, teams) -> None:
        rates = stage_rates(teams, "wins", edges=[20, 40, 50, 70]).set_index(["lower", "stage"])
        assert rates.loc[(20, "made_playoffs"), ["teams", "reached", "rate"]].tolist() == [1, 0, 0]
        middle = rates.loc[(40, "made_playoffs")]
        assert (middle["teams"], middle["reached"]) == (3, 2)
        assert middle["rate"] == pytest.approx(2 / 3)
        top = rates.loc[(50, "won_championship")]
        assert (top["teams"], top["reached"], top["rate"]) == (2, 1, 0.5)
        assert rates.loc[(50, "won_a_round"), "rate"] == 1.0

    def test_every_rate_carries_its_interval(self, teams) -> None:
        rates = stage_rates(teams, "wins", edges=[20, 40, 50, 70])
        assert ((rates["low"] <= rates["rate"]) & (rates["rate"] <= rates["high"])).all()
        nobody = rates[(rates["lower"] == 20) & (rates["stage"] == "made_playoffs")].iloc[0]
        # One team, and it missed: that is no evidence that such teams always miss.
        assert nobody["low"] == 0 and nobody["high"] > 0.75

    def test_a_band_holds_its_lower_edge_and_not_its_upper(self) -> None:
        teams = history([{"wins": 40}, {"wins": 50}, {"wins": 49.999}])
        rates = stage_rates(teams, "wins", edges=[40, 50, 60])
        counted = rates.drop_duplicates("lower").set_index("lower")["teams"]
        assert counted.to_dict() == {40: 2, 50: 1}

    def test_teams_outside_every_band_or_without_a_value_are_left_out(self, teams) -> None:
        rates = stage_rates(teams, "wins", edges=[20, 40, 50, 70])
        assert rates.drop_duplicates("lower")["teams"].sum() == 6

    def test_an_empty_band_is_left_out(self, teams) -> None:
        rates = stage_rates(teams, "wins", edges=[0, 10, 20, 40])
        assert rates["lower"].unique().tolist() == [20]

    def test_without_edges_every_value_is_its_own_band(self, teams) -> None:
        rates = stage_rates(teams, "seed")
        firsts = rates[rates["lower"] == 1]
        assert (firsts["lower"] == firsts["upper"]).all()
        assert firsts.set_index("stage").loc["made_playoffs", ["teams", "reached"]].tolist() == [
            2,
            2,
        ]
        assert rates["lower"].drop_duplicates().tolist() == [1, 2, 6, 8, 9, 12]

    def test_edges_must_ascend(self, teams) -> None:
        for edges in ([50], [50, 40], [40, 40, 50]):
            with pytest.raises(ValueError, match="ascending"):
                stage_rates(teams, "wins", edges=edges)

    def test_no_teams_no_rows(self, teams) -> None:
        rates = stage_rates(teams.iloc[0:0], "wins", edges=[0, 50, 100])
        assert len(rates) == 0 and list(rates.columns) == list(RATE_COLUMNS)

    def test_on_the_fixture_seasons_wins_order_the_playoff_teams(self, frame) -> None:
        rates = stage_rates(frame, "wins_per_82", edges=bands(frame["wins_per_82"], 10))
        playoffs = rates[rates["stage"] == "made_playoffs"].set_index("lower")["rate"]
        assert playoffs.is_monotonic_increasing
        assert playoffs.iloc[0] == 0 and playoffs.iloc[-1] == 1
        assert rates.drop_duplicates("lower")["teams"].sum() == len(frame)


class TestProfiles:
    @pytest.fixture
    def teams(self) -> pd.DataFrame:
        champions = [{"net": float(value), "won_championship": True, "made_finals": True}
                     for value in (1, 2, 3, 4, 5)]  # fmt: skip
        others = [{"net": -3.0}, {"net": None}]
        return history(champions + others)

    def test_the_whole_field_then_each_stage(self, teams) -> None:
        profiles = stage_profiles(teams, ["net"])
        assert list(profiles.columns) == list(PROFILE_COLUMNS)
        assert profiles["group"].tolist() == [EVERY_TEAM, *STAGE_KEYS]

    def test_quantiles_of_the_teams_that_reached_a_stage(self, teams) -> None:
        champions = stage_profiles(teams, ["net"]).set_index("group").loc["won_championship"]
        assert champions["teams"] == 5
        assert champions[list(QUANTILES)].tolist() == [1.0, 1.4, 2.0, 3.0, 4.0, 4.6, 5.0]

    def test_a_missing_value_is_not_counted(self, teams) -> None:
        field = stage_profiles(teams, ["net"]).set_index("group").loc[EVERY_TEAM]
        assert field["teams"] == 6 and field["lowest"] == -3.0

    def test_a_stage_nobody_reached_has_no_spread(self, teams) -> None:
        nobody = stage_profiles(teams, ["net"]).set_index("group").loc["made_playoffs"]
        assert nobody["teams"] == 0
        assert all(math.isnan(nobody[name]) for name in QUANTILES)

    def test_ranks_profile_like_any_column(self, frame) -> None:
        profiles = stage_profiles(frame, ["net_rating_rank", "wins_per_82"])
        champions = profiles[profiles["group"] == "won_championship"].set_index("metric")
        assert champions.at["net_rating_rank", "teams"] == 3
        assert champions.at["net_rating_rank", "lowest"] == 1
        assert champions.at["wins_per_82", "lowest"] == 53  # the 2025-26 champions
        assert champions.at["wins_per_82", "highest"] == 69  # the 1996-97 Bulls


class TestRankCounts:
    @pytest.fixture
    def teams(self) -> pd.DataFrame:
        rows = [
            {"off_rank": 1, "def_rank": 1, "won_championship": True},
            {"off_rank": 1, "def_rank": 12, "won_championship": True},
            {"off_rank": 3, "def_rank": 4, "won_championship": True},
            {"off_rank": 8, "def_rank": 9, "won_championship": True},
            {"off_rank": 2, "def_rank": 2},
            {"off_rank": 20, "def_rank": 20},
        ]
        return history(rows)

    def test_how_many_of_a_group_ranked_inside_each_cutoff(self, teams) -> None:
        counts = rank_counts(teams, ["off"])
        assert list(counts.columns) == list(RANK_COUNT_COLUMNS)
        champions = counts[counts["group"] == "won_championship"].set_index("cutoff")
        assert champions["inside"].to_dict() == {1: 2, 3: 3, 5: 3, 10: 4}
        assert (champions["teams"] == 4).all()
        assert champions.at[1, "share"] == 0.5
        assert champions.at[10, "high"] == 1.0 and champions.at[10, "low"] < 0.6

    def test_several_keys_must_all_be_inside(self, teams) -> None:
        both = rank_counts(teams, ["off", "def"], cutoffs=(5, 10))
        champions = both[both["group"] == "won_championship"].set_index("cutoff")
        assert champions["inside"].to_dict() == {5: 2, 10: 3}
        field = both[both["group"] == EVERY_TEAM].set_index("cutoff")
        assert field["inside"].to_dict() == {5: 3, 10: 4} and (field["teams"] == 6).all()

    def test_a_group_with_nobody_in_it_has_no_share(self, teams) -> None:
        nobody = rank_counts(teams, ["off"]).set_index(["group", "cutoff"]).loc[("made_finals", 1)]
        assert nobody["teams"] == 0 and math.isnan(nobody["share"])

    def test_it_needs_a_metric(self, teams) -> None:
        with pytest.raises(ValueError, match="at least one metric"):
            rank_counts(teams, [])

    def test_fixture_champions_were_near_the_top_at_both_ends(self, frame) -> None:
        both = rank_counts(frame, ["off_rating", "def_rating"], cutoffs=(10,))
        champions = both[both["group"] == "won_championship"].iloc[0]
        assert (champions["teams"], champions["inside"]) == (3, 3)


class TestSeparation:
    @staticmethod
    def seasons(*seasons: tuple[str, list[float | None], list[bool]], key: str) -> pd.DataFrame:
        rows = []
        for season, values, flags in seasons:
            for value, flag in zip(values, flags, strict=True):
                rows.append({"season": season, key: value, "made_playoffs": flag})
        frame = history(rows)
        better_low = BENCHMARK_METRICS[key].higher_is_better is False
        frame[f"{key}_rank"] = (
            frame.groupby("season")[key].rank(method="min", ascending=better_low).astype("Int64")
        )
        return frame

    def test_the_share_of_same_season_pairs_the_better_value_wins(self) -> None:
        frame = self.seasons(
            ("A", [10, 8, 6, 4], [True, True, False, False]),  # 4 pairs, all 4 the right way
            ("B", [5, 9, 7, 1], [True, False, False, False]),  # 3 pairs, 1 the right way
            key="net_rating",
        )
        table = separation(frame, "made_playoffs", ["net_rating"])
        assert list(table.columns) == list(SEPARATION_COLUMNS)
        row = table.iloc[0]
        assert row["concordance"] == pytest.approx(5 / 7)
        assert (row["pairs"], row["seasons"], row["reached"], row["others"]) == (7, 2, 3, 5)

    def test_a_tie_counts_as_half(self) -> None:
        frame = self.seasons(("A", [5, 5], [True, False]), key="net_rating")
        assert separation(frame, "made_playoffs", ["net_rating"]).at[0, "concordance"] == 0.5

    def test_lower_is_better_for_a_defensive_rating(self) -> None:
        frame = self.seasons(("A", [100, 104, 108], [True, False, False]), key="def_rating")
        assert separation(frame, "made_playoffs", ["def_rating"]).at[0, "concordance"] == 1.0
        frame = self.seasons(("A", [108, 104, 100], [True, False, False]), key="def_rating")
        assert separation(frame, "made_playoffs", ["def_rating"]).at[0, "concordance"] == 0.0

    def test_a_metric_with_no_better_direction_reads_as_higher(self) -> None:
        frame = self.seasons(("A", [101, 95, 93], [True, False, False]), key="pace")
        assert separation(frame, "made_playoffs", ["pace"]).at[0, "concordance"] == 1.0

    def test_teams_are_only_compared_within_their_own_season(self) -> None:
        # A high-scoring era and a low-scoring one. Pooled, the old playoff team (95)
        # would lose to the modern team that missed (108); within seasons it never does.
        frame = self.seasons(
            ("2025-26", [110, 108], [True, False]),
            ("1998-99", [95, 93], [True, False]),
            key="pts_per_game",
        )
        row = separation(frame, "made_playoffs", ["pts_per_game"]).iloc[0]
        assert row["concordance"] == 1.0 and row["pairs"] == 2

    def test_a_season_with_no_pairs_adds_nothing(self) -> None:
        frame = self.seasons(
            ("A", [10, 8], [True, False]),
            ("B", [9, 7], [True, True]),  # everybody reached it: nothing to compare
            ("C", [6, 5], [False, False]),  # nobody did
            key="net_rating",
        )
        row = separation(frame, "made_playoffs", ["net_rating"]).iloc[0]
        assert (row["pairs"], row["seasons"], row["concordance"]) == (1, 1, 1.0)

    def test_missing_values_are_left_out(self) -> None:
        frame = self.seasons(("A", [10, None, 6, 4], [True, True, False, False]), key="net_rating")
        row = separation(frame, "made_playoffs", ["net_rating"]).iloc[0]
        assert (row["reached"], row["others"], row["pairs"]) == (1, 2, 2)

    def test_nothing_to_compare_gives_no_figure(self) -> None:
        frame = self.seasons(("A", [10, 8], [True, True]), key="net_rating")
        row = separation(frame, "made_playoffs", ["net_rating"]).iloc[0]
        assert math.isnan(row["concordance"]) and math.isnan(row["low"]) and row["pairs"] == 0

    def test_one_season_has_an_interval_of_no_width(self) -> None:
        frame = self.seasons(("A", [10, 8, 6, 4], [True, False, True, False]), key="net_rating")
        row = separation(frame, "made_playoffs", ["net_rating"]).iloc[0]
        assert row["low"] == row["high"] == row["concordance"] == 0.75

    def test_the_interval_holds_the_figure_and_narrows_with_more_seasons(self) -> None:
        pattern = [
            ([10, 8, 6, 4], [True, True, False, False]),
            ([10, 8, 6, 4], [True, False, True, False]),
            ([10, 8, 6, 4], [False, True, True, False]),
        ]
        few = self.seasons(*[(f"S{n}", *pattern[n % 3]) for n in range(3)], key="net_rating")
        many = self.seasons(*[(f"S{n:02d}", *pattern[n % 3]) for n in range(30)], key="net_rating")
        narrow = separation(many, "made_playoffs", ["net_rating"]).iloc[0]
        wide = separation(few, "made_playoffs", ["net_rating"]).iloc[0]
        for row in (narrow, wide):
            assert row["low"] <= row["concordance"] <= row["high"]
        assert narrow["concordance"] == pytest.approx(wide["concordance"]) == pytest.approx(0.75)
        assert narrow["high"] - narrow["low"] < wide["high"] - wide["low"]

    def test_the_interval_is_as_wide_as_the_confidence_asked_for(self) -> None:
        # Three seasons of one pair each: two went the right way, one the wrong way.
        # Drawing three seasons again gives a share of 1 about 30% of the time, 2/3
        # about 44%, 1/3 about 22% and 0 about 4%.
        frame = self.seasons(
            ("A", [10, 8], [True, False]),
            ("B", [10, 8], [True, False]),
            ("C", [8, 10], [True, False]),
            key="net_rating",
        )
        usual = separation(frame, "made_playoffs", ["net_rating"]).iloc[0]
        assert usual["concordance"] == pytest.approx(2 / 3)
        assert (usual["low"], usual["high"]) == (0.0, 1.0)
        loose = separation(frame, "made_playoffs", ["net_rating"], confidence=0.6).iloc[0]
        assert loose["low"] == pytest.approx(1 / 3) and loose["high"] == 1.0

    def test_the_same_seed_gives_the_same_interval(self) -> None:
        frame = self.seasons(
            *[(f"S{n}", [10, 8, 6, 4], [n % 2 == 0, True, n % 3 == 0, False]) for n in range(8)],
            key="net_rating",
        )
        first = separation(frame, "made_playoffs", ["net_rating"], seed=7)
        again = separation(frame, "made_playoffs", ["net_rating"], seed=7)
        pd.testing.assert_frame_equal(first, again)

    def test_median_league_ranks_of_the_two_groups(self) -> None:
        frame = self.seasons(("A", [10, 8, 6, 4, 2], [True, True, False, False, False]),
                             key="net_rating")  # fmt: skip
        row = separation(frame, "made_playoffs", ["net_rating"]).iloc[0]
        assert (row["reached_median_rank"], row["others_median_rank"]) == (1.5, 4.0)

    def test_metrics_come_back_in_the_order_asked(self, frame) -> None:
        keys = ["pace", "net_rating", "def_rating", "wins_per_82"]
        table = separation(frame, "made_conference_finals", keys, resamples=200)
        assert table["metric"].tolist() == keys

    def test_on_the_fixture_seasons_strength_separates_and_pace_does_not(self, frame) -> None:
        table = separation(
            frame, "made_playoffs", ["net_rating", "wins_per_82", "pace"], resamples=200
        ).set_index("metric")
        assert table.at["net_rating", "concordance"] > 0.9
        assert table.at["wins_per_82", "concordance"] > 0.9
        assert 0.3 < table.at["pace", "concordance"] < 0.7
        assert table.at["net_rating", "seasons"] == 3
        assert table.at["net_rating", "reached"] == 48 and table.at["net_rating", "others"] == 41

    def test_a_seed_is_its_own_rank(self, frame) -> None:
        row = separation(frame, "won_a_round", ["conference_rank"], resamples=200).iloc[0]
        assert row["concordance"] > 0.8  # a better seed is a lower number
        assert row["reached_median_rank"] < row["others_median_rank"]
        assert row["reached_median_rank"] <= 3

    def test_bad_arguments(self, frame) -> None:
        with pytest.raises(KeyError, match="no stage named"):
            separation(frame, "won_the_lottery", ["net_rating"])
        with pytest.raises(ValueError, match="at least 1"):
            separation(frame, "made_playoffs", ["net_rating"], resamples=0)
