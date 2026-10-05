"""The Postseason Outlook page: what it shows must be what the postseason service returns.

``plain_home`` is the fixture store with the model the lab ships (two valued teams, so no
bracket can be read); ``postseason_home`` the invented league with its playoffs and a
model fitted on it; ``scratch_home`` a copy with contracts that a test may add a roster to.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from front_office.config import load_settings, postseason_model_path
from front_office.services import Lab, probability_key
from tests.helpers import BOS, BROWN, PRITCHARD, TATUM, WHITE
from tests.ui.conftest import drawn, figures, texts
from wb import formats, state
from wb.views.postseason import CURVE_STAGE, NET, ROSTER, SUBJECT, TABS

SEASON = "2005-06"
TITLE = probability_key("won_championship")


def service(home: Path) -> Lab:
    return Lab(load_settings(home))


def table_having(opened: AppTest, *columns: str, without: tuple[str, ...] = ()):  # type: ignore[no-untyped-def]
    """The first table on the page that carries every one of these columns and none of
    ``without``."""
    return next(
        frame.value
        for frame in opened.dataframe
        if set(columns) <= set(frame.value.columns) and not set(without) & set(frame.value.columns)
    )


def altered(home: Path, tmp_path: Path, old: str, new: str) -> Path:
    """A private copy of a project with one phrase of its postseason model file changed."""
    target = tmp_path / "home"
    shutil.copytree(home, target)
    path = postseason_model_path(target / "configs")
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return target


class TestThePage:
    def test_it_says_what_it_is_and_asks_for_a_subject(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "postseason")
        said = texts(opened)
        assert [title.value for title in opened.title] == ["Postseason Outlook"]
        assert "How likely each stage of the playoffs is" in said
        assert "Modeled" in said and "Measured" in said and "Your assumption" in said
        assert [tab.label for tab in opened.tabs] == list(TABS)
        assert "**Choose a team**" in said and "Out of date" not in said

    def test_without_a_model_it_says_how_to_fit_one(
        self, page, plain_home: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "home"
        shutil.copytree(plain_home, target)
        postseason_model_path(target / "configs").unlink()
        opened = page(target, "postseason")
        assert "**No postseason model has been fitted**" in texts(opened)
        assert "fol playoffs fit --write" in texts(opened) and not opened.tabs

    def test_a_model_from_another_value_model_is_flagged(
        self, page, plain_home: Path, tmp_path: Path
    ) -> None:
        home = altered(
            plain_home, tmp_path, '"value_model_version": "r1"', '"value_model_version": "r9"'
        )
        said = texts(page(home, "postseason"))
        assert "fitted with top-player quality from value model r9" in said
        assert "the database was built with r1" in said


class TestATeamsChances:
    def test_the_sidebar_team_is_read_as_a_team_of_its_strength(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "postseason", **{state.TEAM: BOS})
        with service(plain_home) as lab:
            read = lab.postseason.team(BOS, "2025-26")
        shown = figures(opened)
        assert shown["Net rating"] == (f"{read.net_rating:+.1f}", "2025-26, measured")
        assert shown["Top-player quality"] == (f"{read.top_players:+.2f}", "mean impact, modeled")
        chances = read.outlook.stages.set_index("key")
        assert shown["Winning the title"][0] == formats.share(
            chances.at["won_championship", "probability"]
        )
        assert shown["Making the playoffs"][0] == formats.share(
            chances.at["made_playoffs", "probability"]
        )
        table = table_having(opened, "stage", "probability", "low", "high")
        assert table["probability"].tolist() == pytest.approx(
            read.outlook.stages["probability"].tolist()
        )
        dots = drawn(opened)["ps_outlook"].data[-1]
        assert list(dots.x) == pytest.approx(read.outlook.stages["probability"].tolist())
        assert "Top 3 by impact:" in texts(opened)
        assert "ps_curve" in drawn(opened)

    def test_a_team_without_valued_players_says_so(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "postseason", **{state.TEAM: BOS, state.SEASON: "1996-97"})
        said = texts(opened)
        assert "**Nothing to read for Boston Celtics**" in said and "has been valued" in said

    def test_a_strength_set_by_hand(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "postseason", **{SUBJECT: "Set it yourself", NET: 6.0})
        with service(plain_home) as lab:
            outlook = lab.postseason.outlook(6.0)
        shown = figures(opened)
        assert shown["Net rating"] == ("+6.0", "your assumption")
        assert shown["Top-player quality"] == (
            f"{outlook.top_players:+.2f}",
            "typical of the rating",
        )
        assert shown["Making the playoffs"][0] == formats.share(
            outlook.stages["probability"].iloc[0]
        )
        assert len(table_having(opened, "net_rating", "top_players")) == 45

    def test_the_curve_follows_the_chosen_stage(self, page, plain_home: Path) -> None:
        opened = page(
            plain_home, "postseason", **{SUBJECT: "Set it yourself", CURVE_STAGE: "made_playoffs"}
        )
        with service(plain_home) as lab:
            curve = lab.postseason.curve()
        band = drawn(opened)["ps_curve"].data
        column = probability_key("made_playoffs")
        assert list(band[2].y) == pytest.approx(curve[column].tolist())
        assert list(band[0].y) == pytest.approx(curve[f"{column}_low"].tolist())
        assert "the top-player quality typical of teams at each rating" in texts(opened)


class TestABuiltRoster:
    @pytest.fixture
    def roster(self, scratch_home: Path) -> int:
        with service(scratch_home) as lab:
            roster_id = lab.builder.create("Outlook roster")
            for player in (TATUM, BROWN, PRITCHARD, WHITE):
                lab.builder.add_player(roster_id, player)
        return roster_id

    def test_the_roster_is_the_sum_of_its_parts_with_the_error_folded_in(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        opened = page(scratch_home, "postseason", **{SUBJECT: "Built roster", ROSTER: roster})
        with service(scratch_home) as lab:
            read = lab.postseason.roster(roster)
        shown = figures(opened)
        assert shown["Sum of parts"] == (f"{read.net_rating:+.1f}", f"±{read.error:.1f} (RMSE)")
        assert shown["Top-player quality"][0] == f"{read.top_players:+.2f}"
        said = texts(opened)
        assert "added up for the minutes they played" in said and "is folded in" in said


class TestASeason:
    def test_every_team_lists_the_services_odds(self, page, postseason_home: Path) -> None:
        opened = page(postseason_home, "postseason", **{state.SEASON: SEASON})
        with service(postseason_home) as lab:
            odds = lab.postseason.season_odds(SEASON)
        table = table_having(opened, "team_name", probability_key("made_playoffs"), TITLE)
        assert table["team_name"].tolist() == odds["team_name"].tolist()
        assert table[TITLE].tolist() == pytest.approx(odds[TITLE].tolist())
        said = texts(opened)
        assert f"Every team of {SEASON} under the season model" in said
        dots = drawn(opened)["ps_odds"].data[-1]
        assert list(dots.x) == pytest.approx(odds[TITLE].tolist())

    def test_the_bracket_is_read_from_the_series_played(self, page, postseason_home: Path) -> None:
        opened = page(postseason_home, "postseason", **{state.SEASON: SEASON})
        with service(postseason_home) as lab:
            report = lab.postseason.bracket(SEASON)
        shown = figures(opened)
        short = report.teams.set_index("team_name")["abbreviation"]
        assert shown["Title favourite"] == (
            short[report.favourite],
            f"given {formats.share(report.favourite_probability)}",
        )
        assert shown["Champion"] == (
            short[report.champion],
            f"had been given {formats.share(report.champion_probability)}",
        )
        dots = drawn(opened)["ps_bracket"].data[-1]
        assert list(dots.x) == pytest.approx(
            report.teams[TITLE].sort_values(ascending=False).tolist()
        )
        table = table_having(
            opened,
            "team_name",
            probability_key("won_a_round"),
            "result",
            without=(probability_key("made_playoffs"),),
        )
        assert len(table) == 16 and probability_key("made_playoffs") not in table.columns

    def test_the_series_are_the_services(self, page, postseason_home: Path) -> None:
        opened = page(postseason_home, "postseason", **{state.SEASON: SEASON})
        with service(postseason_home) as lab:
            series = lab.postseason.series(SEASON)
        shown = figures(opened)
        assert shown["Series decided"] == ("15", "15 with both inputs known")
        favourites = int(series["favourite_won"].astype(bool).sum())
        assert shown["Favourite won"] == (f"{favourites} of 15", "the side given over 50%")
        table = table_having(opened, "round_name", "home_team", "winner")
        assert table["winner"].tolist() == series["winner"].tolist()
        dots = drawn(opened)["ps_series"].data[-1]
        assert list(dots.x) == pytest.approx(series["probability"].tolist())

    def test_a_bracket_that_cannot_be_read_says_who_is_missing(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "postseason")
        said = texts(opened)
        assert "**No bracket to read for 2025-26**" in said
        assert "Without a valued player:" in said
        shown = figures(opened)
        assert (
            shown["Series decided"][0] == "15"
            and "with both inputs known" in shown["Series decided"][1]
        )
        assert "ps_bracket" not in drawn(opened)


class TestTheModel:
    def test_the_figures_and_tables_are_the_models(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "postseason")
        with service(plain_home) as lab:
            model = lab.postseason.model()
        tested = model.evaluation
        shown = figures(opened)
        assert shown["Series tested"] == (
            str(tested.series.series),
            f"{tested.series.first_test_season[:4]} to {tested.series.last_test_season}",
        )
        assert shown["Log loss, series"][0] == f"{tested.series.log_loss:.3f}"
        assert shown["Title favourite won"] == (
            f"{tested.bracket.favourite_won} of {len(tested.bracket.favourites)}",
            "postseasons tested",
        )
        assert shown["Revision"] == (str(model.revision), f"fitted {model.fitted_at:%b %d, %Y}")
        methods = table_having(opened, "Method", "Log loss", "Brier")
        assert methods["Log loss"].tolist()[0] == tested.series.log_loss
        assert methods["Method"].tolist()[1:] == [item.label for item in tested.series.baselines]
        alternatives = table_having(opened, "Alternative", "Verdict")
        assert alternatives["Alternative"].tolist() == [c.label for c in tested.series.comparisons]
        reliability = drawn(opened)["ps_reliability_series"].data[-1]
        assert list(reliability.y) == pytest.approx([b.observed for b in tested.series.reliability])
        steps = table_having(opened, "Step", "Intercept")
        assert len(steps) == 5 and steps["Step"].iloc[0] == "Made the playoffs, for every team"
        favourites = table_having(opened, "Season", "Favourite", "Champion")
        assert len(favourites) == len(tested.bracket.favourites)
        said = texts(opened)
        assert "The inputs are the regular season" in said
        assert "A record out-predicts a rating on seasons already played" in said
