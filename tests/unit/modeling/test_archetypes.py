"""Archetypes: measures, groups, scores by rule, and how well a role carries over."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.archetypes import Archetype, ArchetypeSet
from front_office.modeling.archetypes import (
    ASSIGNMENT_COLUMNS,
    BIG_HEIGHT,
    GROUP_KEYS,
    GROUPS,
    LOW_USAGE_PERCENTILE,
    MEASURE_KEYS,
    MEASURES,
    THREE_POINT_PRIOR_ATTEMPTS,
    UnknownDefinition,
    assign_archetypes,
    check_definitions,
    classify,
    measured,
    percentile,
    persistence,
)


def one(key: str = "role", **settings: object) -> Archetype:
    defaults = {"name": key.title(), "description": "A role.", "measures": (A, B)}
    return Archetype(key=key, **{**defaults, **settings})


A, B, C = "usage_pct", "assist_pct", "ts_pct"
"""The measures the hand-made players below are given, as ``a``, ``b`` and ``c``."""


def rules(*archetypes: Archetype, fills_at: float = 60, min_minutes: float = 500) -> ArchetypeSet:
    return ArchetypeSet(
        version=3, min_minutes=min_minutes, fills_at=fills_at, archetypes=archetypes
    )


def players(season: str = "2025-26", **columns: list) -> pd.DataFrame:
    """Hand-made players of one season: measures ``a`` and ``b`` and group flags."""
    count = len(next(iter(columns.values())))
    frame = pd.DataFrame({"player_id": range(1, count + 1), "season": season, **columns})
    frame = frame.rename(columns={"a": A, "b": B, "c": C})
    for group in GROUP_KEYS:
        frame[f"in_{group}"] = True
    return frame


class TestCatalog:
    def test_measures_and_groups_are_named_and_explained(self) -> None:
        assert len(set(MEASURE_KEYS)) == len(MEASURES) == 10
        assert GROUP_KEYS == ("everyone", "guards", "wings", "bigs", "low_usage")
        for item in (*MEASURES, *GROUPS):
            assert item.label[0].isupper() and item.description.endswith(".")

    def test_a_rule_that_names_something_unknown_is_refused(self) -> None:
        check_definitions(rules(one(measures=("usage_pct", "ts_pct"), among="bigs")))
        with pytest.raises(UnknownDefinition, match=r"'role' uses unknown measures \['hustle'\]"):
            check_definitions(rules(one(measures=("usage_pct", "hustle"))))
        with pytest.raises(UnknownDefinition, match="open to an unknown group 'centers'"):
            check_definitions(rules(one(measures=("usage_pct",), among="centers")))


class TestPercentile:
    def test_it_is_the_share_a_value_is_ahead_of_with_ties_as_half(self) -> None:
        values = pd.Series([10.0, 20.0, 30.0, 40.0])
        season = pd.Series(["a"] * 4)
        assert percentile(values, season).tolist() == [12.5, 37.5, 62.5, 87.5]
        tied = percentile(pd.Series([1.0, 1.0, 5.0, 9.0]), season)
        assert tied.tolist() == [25.0, 25.0, 62.5, 87.5]

    def test_each_season_is_ranked_on_its_own(self) -> None:
        values = pd.Series([1.0, 2.0, 100.0, 200.0])
        season = pd.Series(["a", "a", "b", "b"])
        assert percentile(values, season).tolist() == [25.0, 75.0, 25.0, 75.0]

    def test_a_missing_value_has_no_standing_and_is_nobodys_peer(self) -> None:
        values = pd.Series([1.0, np.nan, 3.0])
        found = percentile(values, pd.Series(["a"] * 3))
        assert found.iloc[[0, 2]].tolist() == [25.0, 75.0] and np.isnan(found.iloc[1])


class TestClassify:
    def test_the_score_is_the_weakest_percentile(self) -> None:
        frame = players(a=[1.0, 2.0, 3.0, 4.0], b=[4.0, 3.0, 2.0, 1.0])
        found = classify(frame, rules(one())).set_index("player_id")
        assert tuple(found.reset_index().columns) == ASSIGNMENT_COLUMNS
        # Strong on one and weak on the other is not the role.
        assert found["score"].tolist() == [12.5, 37.5, 37.5, 12.5]
        assert not found["fills"].any() and not found["is_primary"].any()

    def test_strong_on_both_fills_the_role_from_the_cut_off_up(self) -> None:
        frame = players(a=[1.0, 2.0, 3.0, 4.0], b=[1.0, 2.0, 3.0, 4.0])
        found = classify(frame, rules(one(), fills_at=62.5)).set_index("player_id")
        assert found["score"].tolist() == [12.5, 37.5, 62.5, 87.5]
        assert found["fills"].tolist() == [False, False, True, True]
        assert found["is_primary"].tolist() == [False, False, True, True]
        assert set(found["archetype_version"]) == {"v3"} and set(found["archetype"]) == {"role"}

    def test_an_archetype_can_set_its_own_cut_off(self) -> None:
        frame = players(a=[1.0, 2.0, 3.0, 4.0], b=[1.0, 2.0, 3.0, 4.0])
        found = classify(frame, rules(one(fills_at=80), fills_at=30)).set_index("player_id")
        assert found["fills"].tolist() == [False, False, False, True]

    def test_a_tier_stops_where_the_one_above_it_begins(self) -> None:
        frame = players(a=[1.0, 2.0, 3.0, 4.0], b=[1.0, 2.0, 3.0, 4.0])
        tiers = rules(one("top", fills_at=80), one("next", fills_below=80), fills_at=30)
        found = classify(frame, tiers).set_index(["player_id", "archetype"])["fills"]
        assert found.xs("top", level="archetype").tolist() == [False, False, False, True]
        assert found.xs("next", level="archetype").tolist() == [False, True, True, False]

    def test_percentiles_are_taken_among_the_players_the_role_is_open_to(self) -> None:
        frame = players(a=[1.0, 2.0, 3.0, 4.0], b=[1.0, 2.0, 3.0, 4.0])
        frame["in_bigs"] = [True, True, False, False]
        found = classify(frame, rules(one(among="bigs"))).set_index("player_id")
        # Only the two bigs are scored, and against each other.
        assert found.index.tolist() == [1, 2]
        assert found["score"].tolist() == [25.0, 75.0]

    def test_a_player_missing_a_measure_is_not_scored(self) -> None:
        frame = players(a=[1.0, 2.0, 3.0], b=[1.0, np.nan, 3.0])
        found = classify(frame, rules(one())).set_index("player_id")
        assert found.index.tolist() == [1, 3]
        # The first measure is still ranked among all three who have it.
        assert found["score"].tolist() == [pytest.approx(100 / 6), 75.0]

    def test_the_primary_role_is_the_highest_score_among_the_roles_filled(self) -> None:
        frame = players(a=[1.0, 2.0, 3.0, 4.0], b=[1.0, 2.0, 3.0, 4.0], c=[4.0, 3.0, 2.0, 1.0])
        both = rules(one("first"), one("second", measures=(C,)), fills_at=60)
        found = classify(frame, both).set_index(["player_id", "archetype"])
        assert found.loc[(4, "first"), "is_primary"] and found.loc[(1, "second"), "is_primary"]
        assert found["is_primary"].sum() == 4  # players 3, 4 for one; 1, 2 for the other
        assert not found.loc[(4, "second"), "fills"]

    def test_level_scores_go_to_the_role_defined_first(self) -> None:
        frame = players(a=[1.0, 2.0], b=[1.0, 2.0])
        twins = rules(one("first"), one("second"), fills_at=60)
        found = classify(frame, twins).set_index(["player_id", "archetype"])["is_primary"]
        assert found.to_dict() == {
            (1, "first"): False, (1, "second"): False, (2, "first"): True, (2, "second"): False,
        }  # fmt: skip

    def test_rows_are_in_season_player_then_definition_order(self) -> None:
        frame = pd.concat(
            [players("2024-25", a=[1.0, 2.0], b=[1.0, 2.0]), players(a=[1.0, 2.0], b=[1.0, 2.0])]
        ).reset_index(drop=True)
        found = classify(frame, rules(one("zeta"), one("alpha")))
        assert found["season"].tolist() == ["2024-25"] * 4 + ["2025-26"] * 4
        assert found["archetype"].tolist()[:4] == ["zeta", "alpha", "zeta", "alpha"]

    def test_nobody_to_score_gives_no_rows(self) -> None:
        empty = players(a=[1.0], b=[1.0]).iloc[0:0]
        found = classify(empty, rules(one()))
        assert found.empty and tuple(found.columns) == ASSIGNMENT_COLUMNS


class TestMeasured:
    """The measures and groups, on a few hand-made season lines."""

    def tables(self) -> dict[str, pd.DataFrame]:
        lines = pd.DataFrame(
            [
                # player, minutes, poss, usage, assist, fg3m, fg3a, stl, blk, ast, tov, pts, fga, fta
                (1, 2000.0, 4000, 0.30, 0.35, 100, 250, 80, 20, 400, 200, 1500, 1100, 400),
                (2, 1500.0, 3000, 0.15, 0.08, 150, 360, 30, 90, 60, 60, 600, 450, 100),
                (3, 800.0, 1600, 0.20, 0.12, 0, 0, 16, 64, 80, 0, 320, 250, 80),
                (4, 499.0, 1000, 0.22, 0.20, 10, 30, 10, 5, 50, 30, 200, 160, 40),
            ],
            columns=["player_id", "minutes", "possessions", "usage_pct", "assist_pct", "fg3m",
                     "fg3a", "stl", "blk", "ast", "tov", "pts", "fga", "fta"],
        ).assign(season="2025-26", season_type="regular")  # fmt: skip
        playoffs = lines.assign(season_type="playoffs")
        known = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "position": ["G", "F-C", "F", None],
                "height_inches": [75, 82, BIG_HEIGHT, 80],
            }
        )
        valued = pd.DataFrame(
            {"season": "2025-26", "player_id": [1, 2], "impact_defense": [0.5, 2.0]}
        )
        return {
            "player_seasons": pd.concat([lines, playoffs], ignore_index=True),
            "players": known,
            "player_value_scores": valued,
        }

    def test_only_regular_seasons_with_enough_minutes_are_measured(self) -> None:
        found = measured(self.tables(), min_minutes=500)
        assert found["player_id"].tolist() == [1, 2, 3]
        everyone = measured(self.tables(), min_minutes=0)
        assert everyone["player_id"].tolist() == [1, 2, 3, 4]

    def test_rates_are_per_100_possessions_on_the_court(self) -> None:
        found = measured(self.tables(), min_minutes=500).set_index("player_id")
        first = found.loc[1]
        assert first["fg3a_per_100"] == pytest.approx(6.25)
        assert (first["stl_per_100"], first["blk_per_100"]) == (2.0, 0.5)
        assert first["stocks_per_100"] == 2.5
        assert first["ast_per_tov"] == 2.0
        assert first["ts_pct"] == pytest.approx(1500 / (2 * (1100 + 0.44 * 400)))
        assert (first["usage_pct"], first["assist_pct"]) == (0.30, 0.35)

    def test_three_point_accuracy_is_pulled_toward_the_league(self) -> None:
        found = measured(self.tables(), min_minutes=500).set_index("player_id")
        # The league is every regular-season line of the season, the short one included.
        league = (100 + 150 + 0 + 10) / (250 + 360 + 0 + 30)
        prior = THREE_POINT_PRIOR_ATTEMPTS
        assert found.at[1, "fg3_pct_regressed"] == pytest.approx(
            (100 + prior * league) / (250 + prior)
        )
        # Someone who never shoots is taken to shoot like the league.
        assert found.at[3, "fg3_pct_regressed"] == pytest.approx(league)
        assert 100 / 250 < found.at[1, "fg3_pct_regressed"] < league

    def test_the_league_a_shooter_is_pulled_toward_is_that_seasons(self) -> None:
        tables = self.tables()
        lines = tables["player_seasons"]
        regular = lines[lines["season_type"] == "regular"]
        # The season before: the same players, but the league as a whole shot far worse.
        earlier = regular.assign(season="2024-25", fg3m=regular["fg3m"] // 4)
        tables["player_seasons"] = pd.concat([regular, earlier], ignore_index=True)
        found = measured(tables, min_minutes=500).set_index(["season", "player_id"])
        this_league = (100 + 150 + 0 + 10) / (250 + 360 + 0 + 30)
        that_league = (25 + 37 + 0 + 2) / (250 + 360 + 0 + 30)
        assert found.at[("2025-26", 3), "fg3_pct_regressed"] == pytest.approx(this_league)
        assert found.at[("2024-25", 3), "fg3_pct_regressed"] == pytest.approx(that_league)

    def test_a_player_with_no_turnovers_has_no_assists_per_turnover(self) -> None:
        found = measured(self.tables(), min_minutes=500).set_index("player_id")
        assert np.isnan(found.at[3, "ast_per_tov"])

    def test_defensive_impact_is_the_value_models_where_there_is_one(self) -> None:
        found = measured(self.tables(), min_minutes=500).set_index("player_id")
        assert found["impact_defense"].iloc[:2].tolist() == [0.5, 2.0]
        assert np.isnan(found.at[3, "impact_defense"])

    def test_groups_follow_position_height_and_usage(self) -> None:
        found = measured(self.tables(), min_minutes=500).set_index("player_id")
        assert found["in_everyone"].all()
        assert found["in_guards"].tolist() == [True, False, False]
        # A forward at 6'11" is a big whatever the listing says; an F-C always is.
        assert found["in_bigs"].tolist() == [False, True, True]
        assert found["in_wings"].tolist() == [False, False, False]
        assert LOW_USAGE_PERCENTILE == 40
        # Usage percentiles among the three are 83, 17 and 50: one player is below 40.
        assert found["in_low_usage"].tolist() == [False, True, False]

    def test_a_wing_is_a_forward_or_swingman_of_wing_size(self) -> None:
        tables = self.tables()
        tables["players"] = tables["players"].assign(
            position=["G-F", "F", "F", "G"], height_inches=[78, 82, 76, 79]
        )
        found = measured(tables, min_minutes=0)
        assert found["in_wings"].tolist() == [True, True, False, False]

    def test_no_players_no_rows(self) -> None:
        tables = {name: frame.iloc[0:0] for name, frame in self.tables().items()}
        found = measured(tables, min_minutes=500)
        assert found.empty and "in_bigs" in found.columns
        assert assign_archetypes(tables, rules(one(measures=("usage_pct",)))).empty


class TestPersistence:
    def assignments(self) -> pd.DataFrame:
        rows = [
            # player, season, fills
            (1, "2023-24", True), (1, "2024-25", True), (1, "2025-26", False),
            (2, "2023-24", True), (2, "2024-25", False),
            (3, "2023-24", False), (3, "2024-25", True),
            (4, "2023-24", False), (4, "2025-26", True),
        ]  # fmt: skip
        frame = pd.DataFrame(rows, columns=["player_id", "season", "fills"])
        return frame.assign(archetype="role", score=50.0, is_primary=False, archetype_version="v3")

    def test_it_counts_who_filled_a_role_two_seasons_running(self) -> None:
        found = persistence(self.assignments(), rules(one())).iloc[0]
        # Pairs of consecutive seasons: 1 (twice), 2, 3. Player 4 skipped a season.
        assert found["pairs"] == 4
        # Filled in the first of a pair: 1 in 2023-24, 2 in 2023-24, 1 in 2024-25.
        assert found["filled"] == 3
        assert found["again"] == pytest.approx(1 / 3)
        assert found["anyone"] == pytest.approx(2 / 4)
        assert (found["archetype"], found["name"]) == ("role", "Role")

    def test_a_role_nobody_was_scored_for_has_no_rates(self) -> None:
        found = persistence(self.assignments(), rules(one(), one("other"))).set_index("archetype")
        assert found.loc["other", ["pairs", "filled"]].tolist() == [0, 0]
        assert np.isnan(found.at["other", "again"]) and np.isnan(found.at["other", "anyone"])
        assert found.index.tolist() == ["role", "other"]


class TestOnTheInventedLeague:
    def test_every_qualified_player_is_scored_for_the_roles_open_to_everyone(
        self, exact_tables, spec
    ) -> None:
        from front_office.config import load_archetypes
        from tests.conftest import REPO_ROOT
        from tests.synthetic_lab import league_frames
        from tests.value_reference import planted_league, planted_model

        shipped = load_archetypes(REPO_ROOT / "configs")
        frames = league_frames(planted_league(spec), planted_model(spec))
        found = assign_archetypes(frames, shipped)
        lines = frames["player_seasons"]
        qualified = lines[(lines["minutes"] >= shipped.min_minutes) & lines["possessions"].notna()]
        creators = found[found["archetype"] == "primary_creator"]
        assert len(creators) == len(qualified)
        assert set(found["archetype"]) == set(shipped.keys)
        assert found["score"].between(0, 100).all()
        # At most one primary role a player a season, and only among roles filled.
        primary = found[found["is_primary"]]
        assert not primary.duplicated(["player_id", "season"]).any() and primary["fills"].all()
        both = found[found["archetype"].isin(["primary_creator", "secondary_creator"])]
        tiers = both.pivot(index=["player_id", "season"], columns="archetype", values="fills")
        assert not (tiers["primary_creator"] & tiers["secondary_creator"]).any()
