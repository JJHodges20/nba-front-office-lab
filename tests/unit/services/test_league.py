"""The league service, against a database built from the fixture store.

The fixture has every team's season and games for 1996-97, 2012-13 and 2025-26.
"""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.analytics.teams import POSTSEASON_RESULTS, TEAM_METRICS
from front_office.config import Settings
from front_office.services import METRIC_CATALOGS, Lab, LabNotBuilt, metric_glossary

BOS, NYK, DET, OKC, SAS, MIA, CHI = (
    1610612738,
    1610612752,
    1610612765,
    1610612760,
    1610612759,
    1610612748,
    1610612741,
)


@pytest.fixture(scope="module")
def standings(lab: Lab) -> pd.DataFrame:
    return lab.league.standings("2025-26")


@pytest.fixture(scope="module")
def history(lab: Lab) -> pd.DataFrame:
    return lab.league.history()


class TestStandings:
    def test_conference_order(self, standings: pd.DataFrame) -> None:
        assert len(standings) == 30
        assert standings["conference"].tolist() == ["East"] * 15 + ["West"] * 15
        assert standings["conference_rank"].tolist() == [*range(1, 16), *range(1, 16)]
        assert standings.iloc[0]["team_name"] == "Detroit Pistons"
        assert standings.iloc[15]["team_name"] == "Oklahoma City Thunder"

    def test_games_behind_and_records(self, standings: pd.DataFrame) -> None:
        rows = standings.set_index("team_id")
        boston = rows.loc[BOS]
        assert (boston["wins"], boston["losses"], boston["games_behind"]) == (56, 26, 4.0)
        assert (boston["home_record"], boston["road_record"]) == ("30-11", "26-15")
        assert (boston["recent_record"], boston["streak_label"]) == ("8-2", "W2")
        knicks = rows.loc[NYK]
        assert (knicks["home_record"], knicks["road_record"]) == ("30-10", "22-19")
        assert (knicks["recent_record"], knicks["streak_label"]) == ("6-4", "L1")
        assert rows.loc[[DET, OKC], "games_behind"].tolist() == [0.0, 0.0]

    def test_every_team_metric_and_the_outcome_are_there(self, standings: pd.DataFrame) -> None:
        assert set(TEAM_METRICS.keys) <= set(standings.columns)
        rows = standings.set_index("team_id")
        assert rows.loc[NYK, "postseason_result"] == "Champion"
        assert rows.loc[SAS, "postseason_result"] == "Lost NBA Finals"
        assert rows.loc[BOS, "net_rating"] == 8.3

    def test_an_older_season(self, lab: Lab) -> None:
        bulls = lab.league.standings("1996-97").iloc[0]
        assert (bulls["team_name"], bulls["wins"], bulls["losses"]) == ("Chicago Bulls", 69, 13)
        assert (bulls["home_record"], bulls["road_record"]) == ("39-2", "30-11")
        assert bulls["postseason_result"] == "Champion"

    def test_an_unknown_season(self, lab: Lab) -> None:
        with pytest.raises(KeyError, match="no team statistics for 2031-32"):
            lab.league.standings("2031-32")

    def test_an_unbuilt_lab_says_so(self, settings: Settings) -> None:
        with Lab(settings) as empty, pytest.raises(LabNotBuilt):
            empty.league.standings("2025-26")


class TestAverages:
    def test_one_row_per_season_oldest_first(self, lab: Lab) -> None:
        averages = lab.league.averages()
        assert averages.index.tolist() == ["1996-97", "2012-13", "2025-26"]
        assert averages.loc["2025-26", "off_rating"] == pytest.approx(100 * 284395 / 247827)
        assert averages["teams"].tolist() == [29, 30, 30]
        assert set(TEAM_METRICS.keys) <= set(averages.columns)

    def test_changes_from_the_season_before(self, lab: Lab) -> None:
        averages, changes = lab.league.averages(), lab.league.changes()
        assert changes.index.tolist() == averages.index.tolist()
        assert "teams" not in changes.columns
        assert changes.loc["1996-97"].isna().all()
        assert changes.loc["2025-26", "off_rating"] == pytest.approx(
            averages.loc["2025-26", "off_rating"] - averages.loc["2012-13", "off_rating"]
        )

    def test_metrics_are_the_team_catalog(self, lab: Lab) -> None:
        assert lab.league.metrics is TEAM_METRICS


class TestHistory:
    def test_every_team_season_newest_first(self, history: pd.DataFrame) -> None:
        assert len(history) == 89
        assert history["season"].unique().tolist() == ["2025-26", "2012-13", "1996-97"]
        assert not history.duplicated(["season", "team_id"]).any()
        latest = history[history["season"] == "2025-26"]
        assert latest["team_name"].is_monotonic_increasing

    def test_ratings_are_ranked_within_each_season(self, history: pd.DataFrame) -> None:
        for season, rows in history.groupby("season"):
            teams = 29 if season == "1996-97" else 30
            assert (rows["league_teams"] == teams).all()
            for key in ("net_rating", "off_rating", "def_rating"):
                ranks = rows[f"{key}_rank"]
                assert ranks.min() == 1 and ranks.max() <= teams, (season, key)
            assert rows.loc[rows["net_rating"].idxmax(), "net_rating_rank"] == 1
            assert rows.loc[rows["def_rating"].idxmin(), "def_rating_rank"] == 1

    def test_a_real_row(self, history: pd.DataFrame) -> None:
        boston = history[(history["team_id"] == BOS) & (history["season"] == "2012-13")].iloc[0]
        assert (boston["wins"], boston["losses"]) == (41, 40)
        ranks = boston[["net_rating_rank", "off_rating_rank", "def_rating_rank"]].tolist()
        assert ranks == [16, 24, 7]
        assert boston["postseason_result"] == "Lost First Round"

    def test_every_season_ends_one_way_for_each_team(self, history: pd.DataFrame) -> None:
        assert set(history["postseason_result"]) == set(POSTSEASON_RESULTS)
        for _, rows in history.groupby("season"):
            assert (rows["postseason_result"] == "Champion").sum() == 1
            assert (rows["postseason_result"] == "Lost NBA Finals").sum() == 1
            assert (rows["postseason_result"] == "Lost Conference Finals").sum() == 2


class TestChampions:
    def test_each_finals_newest_first(self, lab: Lab) -> None:
        champions = lab.league.champions()
        assert champions["season"].tolist() == ["2025-26", "2012-13", "1996-97"]
        assert champions["champion"].tolist() == ["New York Knicks", "Miami Heat", "Chicago Bulls"]
        assert champions["runner_up"].tolist() == [
            "San Antonio Spurs",
            "San Antonio Spurs",
            "Utah Jazz",
        ]
        assert champions["series"].tolist() == ["4-1", "4-3", "4-2"]
        assert champions["winner_team_id"].tolist() == [NYK, MIA, CHI]

    def test_how_good_each_champion_was(self, lab: Lab) -> None:
        champions = lab.league.champions().set_index("season")
        assert champions[["wins", "losses"]].values.tolist() == [[53, 29], [66, 16], [69, 13]]
        assert champions["net_rating"].tolist() == [6.4, 8.2, 11.8]
        assert champions["net_rating_rank"].tolist() == [5, 2, 1]
        assert champions["off_rating_rank"].tolist() == [3, 1, 1]
        assert champions["def_rating_rank"].tolist() == [7, 9, 4]
        assert champions["conference_rank"].tolist() == [3, 1, 1]
        assert champions["league_teams"].tolist() == [30, 30, 29]

    def test_an_undecided_finals_is_not_listed(self, built_lab: Settings) -> None:
        with Lab(built_lab) as lab:
            with lab.database.begin() as connection:
                results = lab.database.table("playoff_results")
                connection.execute(
                    results.update()
                    .where(results.c.season == "2025-26", results.c.round == 4)
                    .values(is_complete=False, winner_team_id=None, loser_team_id=None)
                )
            assert lab.league.champions()["season"].tolist() == ["2012-13", "1996-97"]


class TestPlayoffs:
    def test_the_bracket_in_round_order(self, lab: Lab) -> None:
        bracket = lab.league.playoffs("2025-26")
        assert bracket["round"].tolist() == [1] * 8 + [2] * 4 + [3] * 2 + [4]
        assert bracket["round_name"].iloc[-1] == "NBA Finals"
        assert bracket["start_date"].iloc[:8].is_monotonic_increasing

    def test_names_seeds_and_winner(self, lab: Lab) -> None:
        finals = lab.league.playoffs("2025-26").iloc[-1]
        assert (finals["team_a"], finals["team_a_seed"], finals["team_a_wins"]) == (
            "San Antonio Spurs",
            2,
            1,
        )
        assert (finals["team_b"], finals["team_b_seed"], finals["team_b_wins"]) == (
            "New York Knicks",
            3,
            4,
        )
        assert finals["winner"] == "New York Knicks"

    def test_a_series_belongs_to_a_conference_until_the_finals(self, lab: Lab) -> None:
        bracket = lab.league.playoffs("2012-13")
        assert bracket["conference"].iloc[:14].isin(["East", "West"]).all()
        assert (bracket["conference"].iloc[:8] == "East").sum() == 4
        assert pd.isna(bracket["conference"].iloc[-1])
        assert bracket.iloc[-1]["winner"] == "Miami Heat"

    def test_names_are_those_of_the_season(self, lab: Lab) -> None:
        bracket = lab.league.playoffs("1996-97")
        names = set(bracket["team_a"]) | set(bracket["team_b"])
        assert "Seattle SuperSonics" in names and "Washington Bullets" in names
        assert (bracket.loc[bracket["round"] == 1, "best_of"] == 5).all()

    def test_a_season_without_a_postseason_is_empty(self, lab: Lab) -> None:
        bracket = lab.league.playoffs("2031-32")
        assert len(bracket) == 0
        assert {"team_a", "team_b", "winner", "conference"} <= set(bracket.columns)


class TestGlossary:
    def test_covers_players_and_teams(self) -> None:
        assert list(METRIC_CATALOGS) == [
            "Player metrics",
            "Team metrics",
            "Roster indicators",
            "Benchmark measures",
            "Player value",
        ]
        document = metric_glossary()
        for catalog in METRIC_CATALOGS.values():
            for spec in catalog:
                assert f"| `{spec.key}` |" in document, spec.key
                assert spec.description in document, spec.key

    def test_the_committed_glossary_matches_the_catalogs(self, repo_root) -> None:
        """docs/METRICS.md is generated; regenerate it with `fol metrics --write`."""
        committed = (repo_root / "docs" / "METRICS.md").read_text(encoding="utf-8")
        assert committed == metric_glossary()
