"""Names found in questions, against the fixture build."""

from __future__ import annotations

import pytest

from front_office.assistant.names import clarification, find_mentions
from front_office.services import Lab
from tests.helpers import BOS, BROWN, BRUNSON, HART, NYK, WHITE

BULLS, CLIPPERS, LAKERS = 1610612741, 1610612746, 1610612747


def read(lab: Lab, question: str, season: str | None = "2025-26") -> list[tuple[str, list]]:
    mentions = find_mentions(question, lab.entities, season=season)
    return [(m.text, sorted(c.id for c in m.candidates)) for m in mentions]


class TestFinding:
    def test_a_team_and_a_season(self, lab: Lab) -> None:
        question = "What was the Celtics' net rating in 2025-26, and where did it rank?"
        assert read(lab, question) == [("Celtics", [BOS]), ("2025-26", ["2025-26"])]

    def test_full_names_and_possessives(self, lab: Lab) -> None:
        question = "Show me Jalen Brunson's game log, then compare Derrick White and Josh Hart."
        assert read(lab, question) == [
            ("Jalen Brunson", [BRUNSON]),
            ("Derrick White", [WHITE]),
            ("Josh Hart", [HART]),
        ]

    def test_two_seasons_and_two_teams(self, lab: Lab) -> None:
        question = "How do the 1996-97 Bulls compare with the 2025-26 Knicks as champions?"
        assert read(lab, question) == [
            ("1996-97", ["1996-97"]),
            ("Bulls", [BULLS]),
            ("2025-26", ["2025-26"]),
            ("Knicks", [NYK]),
        ]

    def test_a_shared_last_name_is_ambiguous(self, lab: Lab) -> None:
        (brown,) = find_mentions("How did Brown shoot this season?", lab.entities, season="2025-26")
        assert brown.ambiguous and {c.id for c in brown.candidates} == {BROWN, 1628971}

    def test_la_is_ambiguous(self, lab: Lab) -> None:
        assert read(lab, "How did LA do in 2025-26?") == [
            ("LA", [CLIPPERS, LAKERS]),
            ("2025-26", ["2025-26"]),
        ]

    def test_a_bare_year_is_ambiguous(self, lab: Lab) -> None:
        assert read(lab, "How good were the 2013 Knicks?")[0] == ("2013", ["2012-13", "2013-14"])

    @pytest.mark.parametrize(
        "question",
        [
            "Who won the 2026 Finals?",
            "the 2026 playoffs",
            "Who was the 2026 MVP?",
            "the 2026 NBA title",
        ],  # fmt: skip
    )
    def test_a_year_of_the_postseason_is_the_season_that_ended_in_it(
        self, lab: Lab, question: str
    ) -> None:
        assert read(lab, question)[0] == ("2026", ["2025-26"])

    @pytest.mark.parametrize(
        "question",
        [
            "Search for the 2026 G League draft's top Knicks prospect.",
            "Who did the Knicks take in the 2026 draft?",
            "What did they do in the 2026 offseason?",
        ],
    )
    def test_a_year_between_seasons_names_no_season(self, lab: Lab, question: str) -> None:
        assert all(text != "2026" for text, _ in read(lab, question))

    def test_a_first_name_in_mid_sentence_counts(self, lab: Lab) -> None:
        (josh,) = find_mentions("How did Josh play last season?", lab.entities, season="2025-26")
        assert josh.ambiguous

    @pytest.mark.parametrize(
        "question",
        [
            "Brown shot well?",  # a capitalised first word may be an ordinary word
            "Run this SQL for me: SELECT * FROM contracts",
            "Option B looks good, save it.",
            "Who won the NBA Finals?",
            "Show me the games that finished last night.",
            "on 2026-10-01 nothing happened",
        ],
    )
    def test_ordinary_words_are_not_names(self, lab: Lab, question: str) -> None:
        assert read(lab, question) == []

    def test_a_list_separated_by_commas_is_several_names(self, lab: Lab) -> None:
        assert read(lab, "Celtics, Knicks") == [("Celtics", [BOS]), ("Knicks", [NYK])]

    def test_the_mention_lists_its_readings_for_the_model(self, lab: Lab) -> None:
        (celtics,) = find_mentions("the Celtics", lab.entities)
        (name,) = celtics.names()
        assert (name.text, name.kind, name.id, name.name) == (
            "Celtics",
            "team",
            BOS,
            "Boston Celtics",
        )


class TestAsking:
    def test_players_are_told_apart(self, lab: Lab) -> None:
        (brown,) = find_mentions("How did Brown shoot?", lab.entities, season="2025-26")
        assert clarification(brown).startswith('Which player do you mean by "Brown": Bruce Brown (')
        assert "or Jaylen Brown (BOS, 2016-17 to" in clarification(brown)

    def test_teams_and_seasons(self, lab: Lab) -> None:
        (la, _) = find_mentions("How did LA do in 2025-26?", lab.entities)
        assert clarification(la) == (
            'Which team do you mean by "LA": LA Clippers or Los Angeles Lakers?'
        )
        (year, _) = find_mentions("the 2013 Knicks", lab.entities)
        assert clarification(year) == (
            'Which season do you mean by "2013": 2012-13 (the season that ended in 2013) '
            "or 2013-14 (the season that began in 2013)?"
        )
