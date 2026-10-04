"""Roster fit profiles: each measure worked by hand, then the invented league as a whole."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from front_office.config import load_archetypes
from front_office.domain.fit import MEASURE_KEYS, MEASURES, ROTATION_SIZE, STARTERS, Area, Method
from front_office.modeling.fit import (
    PROFILE_COLUMNS,
    TEAM_COLUMNS,
    fills_column,
    player_profiles,
    rotation_profile,
    team_profiles,
)
from front_office.modeling.value.features import stints
from tests.conftest import REPO_ROOT
from tests.synthetic_lab import league_frames
from tests.value_reference import planted_league, planted_model

ROLES = (
    "primary_creator",
    "secondary_creator",
    "floor_spacer",
    "perimeter_defender",
    "switchable_wing",
    "rim_protector",
    "stretch_big",
    "connector",
)
DEFAULTS = {
    "usage_pct": 0.2,
    "assist_pct": 0.1,
    "fg3a_per_100": 5.0,
    "fg3_pct_regressed": 0.36,
    "stl_per_100": 1.5,
    "blk_per_100": 0.5,
    "free_throw_rate": 0.25,
    "turnover_pct": 0.12,
    "reb_pct": 0.1,
    "height_inches": 78.0,
    "two_positions": False,
    "in_guards": False,
    "in_wings": False,
    "in_bigs": False,
    "impact": 0.0,
    "impact_offense": 0.0,
    "impact_defense": 0.0,
    "wins_added": 0.0,
    "projected_impact": 0.0,
}
TEAM_MINUTES = 5 * 48 * 82


def member(player_id: int, minutes: float, **values: object) -> dict:
    """One player with a profile; ``roles`` names the archetypes filled."""
    roles = values.pop("roles", ())
    row = {"player_id": player_id, "minutes": minutes, **DEFAULTS, **values}
    row.update({fills_column(role): role in roles for role in ROLES})
    return row


def unprofiled(player_id: int, minutes: float) -> dict:
    """A player with minutes and no statistics at all."""
    row = {"player_id": player_id, "minutes": minutes}
    row.update(dict.fromkeys(DEFAULTS, np.nan))
    row.update(dict.fromkeys((fills_column(role) for role in ROLES), np.nan))
    return row


def profile(*rows: dict, team_minutes: float = TEAM_MINUTES) -> pd.Series:
    return rotation_profile(pd.DataFrame(list(rows)), team_minutes=team_minutes)


def twelve(overrides: dict[int, dict] | None = None) -> list[dict]:
    """Twelve players, the first with the most minutes; ``overrides`` adjust one by rank."""
    rows = []
    for rank in range(12):
        values = (overrides or {}).get(rank, {})
        rows.append(member(100 + rank, 2400 - 180 * rank, **values))
    return rows


class TestTheMeasures:
    def test_every_key_comes_back_as_a_number_or_missing(self) -> None:
        found = profile(*twelve())
        assert list(found.index) == list(MEASURE_KEYS)
        assert found.dtype == "float64"

    def test_averages_weigh_each_player_by_minutes(self) -> None:
        found = profile(
            member(1, 300, fg3a_per_100=10.0, height_inches=84.0, reb_pct=0.2),
            member(2, 100, fg3a_per_100=2.0, height_inches=72.0, reb_pct=0.0),
        )
        assert found["three_point_rate"] == pytest.approx(8.0)
        assert found["height"] == pytest.approx(81.0)
        assert found["rebound_rate"] == pytest.approx(0.15)
        assert found["free_throw_rate"] == pytest.approx(0.25)

    def test_a_lineup_sum_is_five_times_the_average(self) -> None:
        found = profile(member(1, 300, impact=4.0, impact_offense=3.0), member(2, 100, impact=0.0))
        assert found["impact_sum"] == pytest.approx(15.0)
        assert found["offense_sum"] == pytest.approx(5 * 0.75 * 3.0)
        assert found["defense_sum"] == pytest.approx(0.0)
        assert found["usage_sum"] == pytest.approx(1.0)
        even = profile(member(1, 200, impact=2.0), member(2, 200, impact=-2.0))
        assert even["impact_sum"] == pytest.approx(0.0)

    def test_roles_are_counted_in_the_rotation_only(self) -> None:
        rows = twelve(
            {
                0: {"roles": ("primary_creator",)},
                4: {"roles": ("secondary_creator", "floor_spacer")},
                9: {"roles": ("secondary_creator",)},
                10: {"roles": ("primary_creator", "floor_spacer")},
                11: {"roles": ("rim_protector",)},
            }
        )
        found = profile(*rows)
        assert found["primary_creators"] == 1  # the eleventh player is not in the rotation
        assert found["creators"] == 3
        assert found["spacers"] == 1
        assert found["rim_protectors"] == 0
        assert found["perimeter_defenders"] == 0

    def test_the_bench_is_the_sixth_to_tenth_player(self) -> None:
        rows = twelve(
            {
                4: {"roles": ("primary_creator",), "in_bigs": True, "impact": 9.0},
                5: {"roles": ("secondary_creator",), "impact": 1.0},
                7: {"in_bigs": True, "roles": ("rim_protector",), "impact": -1.0},
                9: {"roles": ("perimeter_defender",), "impact": 2.0},
                10: {"in_bigs": True, "roles": ("primary_creator",), "impact": 9.0},
            }
        )
        found = profile(*rows)
        assert (found["bench_creators"], found["bench_bigs"], found["bench_defenders"]) == (1, 1, 2)
        minutes = [2400 - 180 * rank for rank in range(STARTERS, ROTATION_SIZE)]
        impacts = [1.0, 0.0, -1.0, 0.0, 2.0]
        assert found["bench_impact"] == pytest.approx(
            sum(m * i for m, i in zip(minutes, impacts, strict=True)) / sum(minutes)
        )

    def test_the_rotation_is_by_minutes_not_by_order_given(self) -> None:
        few = member(1, 10, roles=("rim_protector",))
        many = [member(2 + n, 1000 - n, roles=("floor_spacer",)) for n in range(ROTATION_SIZE)]
        found = profile(few, *many)
        assert found["rim_protectors"] == 0 and found["spacers"] == ROTATION_SIZE

    def test_minutes_shares_are_of_the_profiled_minutes(self) -> None:
        found = profile(
            member(1, 300, in_guards=True, two_positions=True),
            member(2, 100, in_bigs=True),
            member(3, 100, in_guards=True, in_wings=True),
            unprofiled(4, 500),
        )
        assert found["guard_minutes"] == pytest.approx(0.8)
        assert found["wing_minutes"] == pytest.approx(0.2)
        assert found["big_minutes"] == pytest.approx(0.2)
        assert found["multi_position"] == pytest.approx(0.6)
        assert found["unprofiled_share"] == pytest.approx(0.5)

    def test_a_player_without_a_profile_counts_toward_nothing_else(self) -> None:
        with_ = profile(member(1, 300, impact=2.0, fg3a_per_100=8.0), unprofiled(2, 300))
        without = profile(member(1, 300, impact=2.0, fg3a_per_100=8.0))
        for key in MEASURE_KEYS:
            if key in ("unprofiled_share", "minutes_covered"):
                continue
            assert with_[key] == pytest.approx(without[key], nan_ok=True), key
        assert with_["unprofiled_share"] == 0.5 and without["unprofiled_share"] == 0.0
        assert with_["minutes_covered"] == pytest.approx(600 / TEAM_MINUTES)

    def test_a_missing_value_leaves_the_others_weight(self) -> None:
        found = profile(member(1, 300, impact=np.nan, fg3a_per_100=6.0), member(2, 100, impact=1.0))
        assert found["impact_sum"] == pytest.approx(5.0)
        assert found["three_point_rate"] == pytest.approx(0.75 * 6.0 + 0.25 * 5.0)

    def test_usage_of_the_top_three_and_reliance_on_one_player(self) -> None:
        rows = twelve(
            {
                0: {"usage_pct": 0.31, "wins_added": 6.0},
                1: {"usage_pct": 0.27, "wins_added": 3.0},
                2: {"usage_pct": 0.22, "wins_added": 1.0},
                3: {"usage_pct": 0.18, "wins_added": -2.0},
                11: {"usage_pct": 0.40, "wins_added": 12.0},  # not in the rotation
            }
        )
        found = profile(*rows)
        assert found["usage_top"] == pytest.approx(0.31 + 0.27 + 0.22)
        assert found["star_share"] == pytest.approx(6 / 10)
        nobody = profile(member(1, 100, wins_added=-1.0), member(2, 100, wins_added=0.0))
        assert math.isnan(nobody["star_share"])

    def test_minutes_covered_is_against_the_teams_season(self) -> None:
        found = profile(member(1, 1000), member(2, 500), team_minutes=3000)
        assert found["minutes_covered"] == pytest.approx(0.5)
        assert math.isnan(profile(member(1, 10), team_minutes=0)["minutes_covered"])

    def test_nobody_playing_is_nothing_but_no_minutes(self) -> None:
        found = profile(member(1, 0), member(2, 0, roles=("floor_spacer",)))
        assert found["minutes_covered"] == 0.0
        assert found.drop("minutes_covered").isna().all()

    def test_a_count_the_rules_do_not_define_is_zero(self) -> None:
        rows = [member(1, 100, roles=("floor_spacer",))]
        frame = pd.DataFrame(rows).drop(columns=[fills_column("primary_creator")])
        found = rotation_profile(frame, team_minutes=TEAM_MINUTES)
        assert (found["primary_creators"], found["creators"], found["spacers"]) == (0, 0, 1)


class TestTheDefinitions:
    def test_every_measure_has_what_its_method_needs(self) -> None:
        for item in MEASURES:
            if item.method is Method.COUNT:
                assert item.roles or item.group, item.key
            elif item.method in (Method.COVERED, Method.UNPROFILED):
                assert item.source is None, item.key
            else:
                assert item.source in PROFILE_COLUMNS, item.key
            assert item.description.endswith("."), item.key
        assert len(set(MEASURE_KEYS)) == len(MEASURES) == 32
        for area in Area:
            assert sum(item.area is area for item in MEASURES) >= 2, area

    def test_the_roles_the_counts_name_are_the_shipped_archetypes(self) -> None:
        from front_office.domain.fit import COVERAGE_ROLES

        shipped = load_archetypes(REPO_ROOT / "configs")
        assert set(COVERAGE_ROLES) <= set(shipped.keys)


@pytest.fixture(scope="module")
def frames():  # type: ignore[no-untyped-def]
    from tests.conftest import VALUE_SPEC

    archetypes = load_archetypes(REPO_ROOT / "configs")
    league = planted_league(VALUE_SPEC)
    return league, archetypes, league_frames(league, planted_model(VALUE_SPEC), archetypes)


class TestPlayerProfiles:
    def test_one_row_per_regular_player_season_with_every_column(self, frames) -> None:
        league, archetypes, tables = frames
        profiles = player_profiles(tables, archetypes)
        lines = tables["player_seasons"]
        # A player with minutes but no possessions on the court has no rates to profile.
        regular = lines[(lines["season_type"] == "regular") & (lines["possessions"] > 0)]
        assert len(profiles) == len(regular) < len(lines)
        assert list(profiles.columns) == [
            *PROFILE_COLUMNS,
            *(fills_column(key) for key in archetypes.keys),
        ]
        assert not profiles.duplicated(["season", "player_id"]).any()

    def test_the_columns_are_the_lines_the_listing_and_the_models(self, frames) -> None:
        league, archetypes, tables = frames
        profiles = player_profiles(tables, archetypes).set_index(["season", "player_id"])
        lines = tables["player_seasons"].set_index(["season", "player_id"])
        key = profiles.index[7]
        line = lines.loc[key]
        row = profiles.loc[key]
        assert row["season_minutes"] == line["minutes"]
        assert row["free_throw_rate"] == pytest.approx(line["fta"] / line["fga"])
        assert row["turnover_pct"] == pytest.approx(
            line["tov"] / (line["fga"] + 0.44 * line["fta"] + line["tov"])
        )
        assert row["reb_pct"] == line["reb_pct"]
        players = tables["players"].set_index("player_id")
        assert row["height_inches"] == players.at[key[1], "height_inches"]
        assert row["two_positions"] == ("-" in players.at[key[1], "position"])
        scores = tables["player_value_scores"].set_index(["season", "player_id"])
        for column in ("impact", "impact_offense", "impact_defense", "wins_added"):
            assert row[column] == scores.at[key, column]
        roles = tables["player_archetypes"]
        mine = roles[(roles["season"] == key[0]) & (roles["player_id"] == key[1])]
        filled = set(mine.loc[mine["fills"], "archetype"])
        for archetype in archetypes.keys:
            assert row[fills_column(archetype)] == (archetype in filled)

    def test_two_positions_means_a_listing_with_two(self, frames) -> None:
        league, archetypes, tables = frames
        profiles = player_profiles(tables, archetypes)
        listed = tables["players"].set_index("player_id")["position"]
        expected = profiles["player_id"].map(listed).str.contains("-")
        assert profiles["two_positions"].tolist() == expected.tolist()
        assert 0 < profiles["two_positions"].mean() < 1

    def test_a_player_never_scored_for_a_role_does_not_fill_it(self, frames) -> None:
        league, archetypes, tables = frames
        profiles = player_profiles(tables, archetypes)
        short = profiles[profiles["season_minutes"] < archetypes.min_minutes]
        assert len(short) > 0
        assert not short[[fills_column(key) for key in archetypes.keys]].any().any()


class TestTeamProfiles:
    def test_one_row_per_team_season_weighted_by_the_minutes_played_there(self, frames) -> None:
        league, archetypes, tables = frames
        found = team_profiles(tables, archetypes)
        assert list(found.columns) == list(TEAM_COLUMNS)
        teams = tables["team_seasons"]
        assert len(found) == len(teams) == len(league.team_ids) * len(league.years)
        # The invented league's players account for every minute of every team, give or
        # take the rounding of logged minutes; its one player a season with minutes but no
        # possessions has no profile.
        assert found["minutes_covered"].to_numpy() == pytest.approx(1.0, abs=1e-3)
        assert (found["unprofiled_share"] < 0.01).all()
        played = stints(tables["player_seasons"], tables["player_game_logs"], teams)
        counted = played[played["minutes"] > 0].groupby(["season", "team_id"]).size()
        assert found.set_index(["season", "team_id"])["players"].to_dict() == counted.to_dict()

    def test_a_team_is_the_profile_of_its_players_for_their_minutes_there(self, frames) -> None:
        league, archetypes, tables = frames
        found = team_profiles(tables, archetypes).set_index(["season", "team_id"])
        season, team = found.index[len(found) // 2]
        played = stints(
            tables["player_seasons"], tables["player_game_logs"], tables["team_seasons"]
        )
        mine = played[(played["season"] == season) & (played["team_id"] == team)]
        profiles = player_profiles(tables, archetypes).set_index(["season", "player_id"])
        members = profiles.reindex(
            pd.MultiIndex.from_arrays([[season] * len(mine), mine["player_id"]])
        ).reset_index(drop=True)
        members["minutes"] = mine["minutes"].to_numpy()
        minutes = (
            tables["team_seasons"].set_index(["season", "team_id"]).at[(season, team), "minutes"]
        )
        expected = rotation_profile(members, team_minutes=5 * float(minutes))
        pd.testing.assert_series_equal(
            found.loc[(season, team), list(MEASURE_KEYS)], expected, check_names=False
        )

    def test_impacts_add_up_to_nothing_over_a_league(self, frames) -> None:
        # Impact is centred on the league's average minute, so the teams' sums of parts,
        # weighted by their minutes, come to zero in every season.
        league, archetypes, tables = frames
        found = team_profiles(tables, archetypes)
        teams = tables["team_seasons"].set_index(["season", "team_id"])["minutes"]
        weight = found.set_index(["season", "team_id"]).index.map(teams).to_numpy(dtype="float64")
        weighted = found.assign(
            weighted=found["impact_sum"] * weight, size=found["impact_sum"].abs() * weight
        )
        totals = weighted.groupby("season")[["weighted", "size"]].sum()
        # Not exact: the players without a profile carry a baseline impact, and logged
        # minutes are rounded.
        assert (totals["weighted"].abs() < 1e-3 * totals["size"]).all()

    def test_lagged_profiles_describe_what_was_known_before_the_season(self, frames) -> None:
        league, archetypes, tables = frames
        now = team_profiles(tables, archetypes).set_index(["season", "team_id"])
        lagged = team_profiles(tables, archetypes, lag=1).set_index(["season", "team_id"])
        first = min(league.years)
        first_label = f"{first}-{str(first + 1)[-2:]}"
        assert (lagged.loc[first_label, "unprofiled_share"] == 1.0).all()
        assert lagged.loc[first_label, "minutes_covered"].to_numpy() == pytest.approx(1.0, abs=1e-3)
        later = [
            label
            for label in lagged.index.get_level_values("season").unique()
            if label != first_label
        ]
        # Newcomers have no profile; everyone else is described by last season.
        assert 0 < lagged.loc[later, "unprofiled_share"].mean() < 0.5
        assert not now["three_point_rate"].equals(lagged["three_point_rate"])
        # One team by hand: last season's profiles, this season's minutes.
        season, team = now.index[-1]
        start = int(season[:4])
        played = stints(
            tables["player_seasons"], tables["player_game_logs"], tables["team_seasons"]
        )
        mine = played[(played["season"] == season) & (played["team_id"] == team)]
        profiles = player_profiles(tables, archetypes)
        profiles["start"] = profiles["season"].str.slice(0, 4).astype(int)
        previous = profiles[profiles["start"] == start - 1].set_index("player_id")
        members = previous.reindex(mine["player_id"]).reset_index(drop=True)
        members["minutes"] = mine["minutes"].to_numpy()
        minutes = (
            tables["team_seasons"].set_index(["season", "team_id"]).at[(season, team), "minutes"]
        )
        expected = rotation_profile(members, team_minutes=5 * float(minutes))
        pd.testing.assert_series_equal(
            lagged.loc[(season, team), list(MEASURE_KEYS)], expected, check_names=False
        )

    def test_no_games_no_profiles(self, frames) -> None:
        league, archetypes, tables = frames
        empty = {name: frame.iloc[0:0] for name, frame in tables.items()}
        found = team_profiles(empty, archetypes)
        assert found.empty and list(found.columns) == list(TEAM_COLUMNS)
