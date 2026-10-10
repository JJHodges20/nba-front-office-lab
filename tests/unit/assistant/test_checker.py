from __future__ import annotations

import pytest

from front_office.assistant.checker import (
    check,
    cut,
    cut_phantoms,
    cut_wording,
    figures,
    phantoms,
    repair_note,
    wording,
)

RESULT = """[r1] Boston Celtics, 2025-26 regular season (ok)
| Net rating | +8.3 | 4th of 30 | +0.0 |
| Record | 56-26 |
| True shooting percentage | 58.3% | 13th of 30 | 58.1% |
| Pace | 95.58 |
| Defensive rating | -7.2 |
| Salary | $40,000,000 |
Source: NBA.com statistics as the lab holds them, data build 16 of 2026-10-06"""


def values(text: str) -> list[float]:
    return [figure.value for figure in figures(text)]


class TestReading:
    @pytest.mark.parametrize(
        ("text", "read"),
        [
            ("a net rating of +8.3", [8.3]),
            ("a record of 56-26", [56.0, 26.0]),
            ("in 2025-26, as of 2026-10-09", []),
            ("see [r1] and s2", []),
            ("paid $40,000,000", [40_000_000.0]),
            ("about $40.5M", [40_500_000.0]),
            ("40 million", [40_000_000.0]),
            ("4th of 30", [4.0, 30.0]),
            ("−7.2 or -7.2", [-7.2, -7.2]),
            ("57.3%", [57.3]),
            # A1-A2: dates written out and years are labels, not figures (case K01).
            ("as of October 1, 2026, he earns $40M", [40_000_000.0]),
            ("on 1 October 2026 and Sept. 30", []),
            ("in 2026, and since 1996", []),
            ("$2026 and 2026%", [2026.0, 2026.0]),
            # A2, live: a numbered list's markers had been read as figures.
            ("Reports:\n1. Still working out the kinks\n  4) Starters sharp", []),
            ("The score was 4. Then 5.5 more.", [4.0, 5.5]),
        ],
    )
    def test_what_counts_as_a_figure(self, text: str, read: list[float]) -> None:
        assert values(text) == pytest.approx(read)

    def test_precision_is_what_is_written(self) -> None:
        (money,) = figures("$40.5M")
        assert money.step == pytest.approx(100_000)
        (rating,) = figures("8.31")
        assert rating.step == pytest.approx(0.01)


class TestChecking:
    @pytest.mark.parametrize(
        "answer",
        [
            "The Celtics' net rating was +8.3 [r1], 4th of 30.",
            "They went 56-26 [r1].",
            "Their pace was 95.6, rounded from the result [r1].",
            "True shooting of 58% [r1], or 0.583 as a fraction.",
            "Paid $40M, that is $40.0 million [r1].",
            "Their defensive figure was -7.2, or 7.2 below zero [r1].",
            "Nothing numeric here at all.",
        ],
    )
    def test_figures_the_results_hold_stand(self, answer: str) -> None:
        assert check(answer, [RESULT]).ok

    @pytest.mark.parametrize(
        ("answer", "unsupported"),
        [
            ("Their net rating was +9.1.", "+9.1"),
            ("Their net rating was 8.31.", "8.31"),  # more precise than anything given
            ("Their defensive figure was +7.2.", "+7.2"),  # a sign the result does not have
            ("They won 61 games.", "61"),
            ("Paid $45M.", "$45M"),
        ],
    )
    def test_figures_from_nowhere_do_not(self, answer: str, unsupported: str) -> None:
        result = check(answer, [RESULT])
        assert [figure.text for figure in result.unsupported] == [unsupported]
        assert unsupported in repair_note(result)

    def test_the_question_and_context_count_as_given(self) -> None:
        assert check("Under a budget of $150M, as you asked.", ["Propose rosters under $150M."]).ok


class TestCutting:
    def test_only_the_sentences_with_unsupported_figures_go(self) -> None:
        answer = (
            "The Celtics went 56-26 [r1]. They were 9th in pace. Their net rating was +8.3 [r1]."
        )
        text, removed = cut(answer, [RESULT])
        assert text == "The Celtics went 56-26 [r1]. Their net rating was +8.3 [r1]."
        assert removed == ("9",)

    def test_lines_stay_lines(self) -> None:
        answer = "Summary:\n- Record 56-26 [r1]\n- Bench points 41.2\n- Net rating +8.3 [r1]"
        text, removed = cut(answer, [RESULT])
        assert text == "Summary:\n- Record 56-26 [r1]\n- Net rating +8.3 [r1]"
        assert removed == ("41.2",)


class TestWording:
    def test_a_frequency_called_a_chance_is_caught(self) -> None:
        answer = "Teams like these had a 0% chance of winning the title [r1]."
        (found,) = wording(answer, ["historical_benchmarks"])
        assert found.phrase == "chance" and "only the postseason model" in found.rule

    @pytest.mark.parametrize(
        "disclaimer",
        [
            "These are frequencies among past teams, not probabilities.",
            "A share of past teams - not any team's chance [r1].",
            "This is never a team's chance of winning.",
        ],
    )
    def test_saying_what_a_frequency_is_not_stands(self, disclaimer: str) -> None:
        assert wording(disclaimer, ["historical_benchmarks"]) == ()

    def test_no_chance_is_still_a_claim(self) -> None:
        assert wording("They have no chance of a title.", ["historical_benchmarks"])

    def test_a_chance_from_the_postseason_model_stands(self) -> None:
        assert wording("A 12% chance of the title [r1].", ["postseason_outlook"]) == ()

    @pytest.mark.parametrize(
        "phrase", ["a title contender", "should sign him", "the best roster", "contenders"]
    )
    def test_verdicts_are_caught_whatever_the_results(self, phrase: str) -> None:
        assert wording(f"They are {phrase}.", ["postseason_outlook"])

    def test_plain_words_pass(self) -> None:
        answer = "The Knicks were 5th in net rating and won 53 games; the odds were long."
        assert wording(answer, ["team_stats"]) == ()

    def test_the_repair_note_names_both_kinds_of_problem(self) -> None:
        note = repair_note(check("+9.9", [RESULT]), wording("a 4% chance", []))
        assert "+9.9" in note and 'Do not write "chance"' in note

    def test_cutting_takes_only_the_sentences_that_break_the_rules(self) -> None:
        text, removed = cut_wording(
            "They won 53 games [r1]. That gives them a 9% chance.\n- They are contenders.", []
        )
        assert text == "They won 53 games [r1]."
        assert removed == ("chance", "contenders")

    @pytest.mark.parametrize(
        "claim",
        ["The roster for Option B has been saved.", "I've updated the settings.", "I deleted it."],
    )
    def test_a_claim_to_have_saved_or_changed_anything_is_caught(self, claim: str) -> None:
        (found,) = wording(claim, [])
        assert "cannot save, change or delete" in found.rule

    @pytest.mark.parametrize(
        "plain",
        [
            "The rules were changed by the 2023 CBA.",
            "Their roster has been changed since the build, by the league's file.",
            "You can save it with the Save button.",
        ],
    )
    def test_saying_what_happened_or_what_the_user_can_do_is_not_a_claim(self, plain: str) -> None:
        assert wording(plain, []) == ()


class TestCitations:
    def test_a_result_that_does_not_exist_is_found(self) -> None:
        assert phantoms("As in [r1] and [table r2] and [Chart R3].", ["r1"]) == ("r2", "r3")
        assert phantoms("Their net rating was +8.3 [r1].", ["r1"]) == ()

    def test_cutting_takes_the_sentences_that_cite_nothing(self) -> None:
        text, removed = cut_phantoms("Here is the season [table r2]. It was +8.3 [r1].", ["r1"])
        assert (text, removed) == ("It was +8.3 [r1].", ("r2",))
