from __future__ import annotations

import pytest

from front_office.assistant.checker import (
    FOR_THE_USER,
    bare_shares,
    check,
    cut,
    cut_phantoms,
    cut_wording,
    figures,
    phantoms,
    repair_note,
    without_repeats,
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
            # A5 (S02, M03): the lab's units had been cut as figures no result held.
            ("+8.3 points per 100 possessions", [8.3]),
            ("48 wins per 82 games, every 100 possessions", [48.0]),
            ("100 possessions and 82 games", [100.0, 82.0]),
            # A8, live: a season written with a dash, as typesetters write it, lost "07".
            ("from 2006–07 to 2025—26, and 2012‑13", []),
            ("a record of 56–26", [56.0, 26.0]),
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


class TestIntervals:
    def test_a_share_without_its_interval_is_bare(self) -> None:
        """A4: answers gave a benchmark's share and the simulator's chances alone."""
        assert bare_shares("0 of 10 won it: 0% [r1].", ["historical_benchmarks"])
        assert bare_shares("Their chance rises to 51.1% [r1].", ["simulate_scenario"])

    def test_a_share_with_its_interval_is_not(self) -> None:
        answer = "0 of 10 won it: 0%, with a 95% interval of 0% to 27.8% [r1]."
        assert not bare_shares(answer, ["historical_benchmarks"])

    def test_only_shares_that_come_with_intervals_need_them(self) -> None:
        assert not bare_shares("They shot 58.3% [r1].", ["team_stats"])
        assert not bare_shares("They went 0 for 10 [r1].", ["historical_benchmarks"])

    def test_the_note_asks_for_them(self) -> None:
        assert "interval" in repair_note(check("", []), bare=True)


class TestRepeats:
    def test_a_sentence_said_again_is_taken_out(self) -> None:
        """A4: a model wrote one sentence over and over until its output ran out."""
        loop = "The model's log loss for the playoffs is 0.250, lower than the base rate's."
        answer = f"First things first. {loop} {loop}\n{loop} And then the end."
        text, dropped = without_repeats(answer)
        assert dropped == 2
        assert text == f"First things first. {loop}\nAnd then the end."

    def test_a_short_phrase_that_recurs_stays(self) -> None:
        answer = "Before: no change.\nAfter: no change."
        assert without_repeats(answer) == (answer, 0)


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

    def test_the_labs_documents_may_describe_chances(self) -> None:
        """A4: an answer explaining the postseason model from its decision had "chances" cut."""
        answer = "The model gives each team's chances of each stage from two inputs [r1]."
        assert wording(answer, ["research_docs"]) == ()
        assert wording(answer, ["historical_benchmarks"]), "a frequency is still not a chance"

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
        # A5 (R01): the rewrite had begun "Here's the corrected version".
        assert note.endswith(FOR_THE_USER) and repair_note(check("", [])) == ""

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


class TestPlaces:
    def test_a_place_stands_only_on_a_place(self) -> None:
        # Live at A3: "2018-19: +4.3 (6th in the league)" passed on some +6.3 in the result.
        given = ["| 2018-19 | +4.3 |", "| 2017-18 | +6.3 |"]
        assert check("2018-19: +4.3 (6th in the league).", given).listed == "6"
        assert check("They were 4th of 30.", ["| Net rating | +8.3 | 4th of 30 |"]).ok

    def test_a_percentile_is_a_place_too(self) -> None:
        assert check("He was in the 99th percentile.", ["| Points | 28.7 | 99th percentile |"]).ok
        assert not check("He was in the 99th percentile.", ["| Points | 99.0 |"]).ok

    def test_a_plain_number_may_still_stand_on_a_place(self) -> None:
        assert check("Ranked 4 of 30.", ["4th of 30"]).ok


class TestWhatAPlaceRanks:
    """A7, the user's wish at the A6 review: a place is checked for its field as well."""

    TEAM = "New York Knicks, 2025-26 regular season, full season. 3rd in the East.\n| Wins | 53 | 6th of 30 | 41 |"  # fmt: skip

    def test_the_league_s_6th_does_not_hold_6th_in_the_east(self) -> None:
        # Live at A6: "53 wins, placing them 6th in the Eastern Conference" on the league's 6th.
        result = check("53 wins, 6th in the Eastern Conference.", [self.TEAM])
        assert result.listed == "6"
        (item,) = result.misplaced
        assert (item.figure.text, item.figure.scope, item.fields) == ("6", "east", ("league",))
        assert item.held == ("3rd",), "what the results do give for the East"
        note = repair_note(result)
        assert "These places rank something the results do not: 6th in the East" in note
        assert "(the results' 6th is in the league; in the East they give 3rd)" in note
        assert "in no tool result" not in note

    def test_a_misplaced_place_costs_its_clause_not_the_record(self) -> None:
        """Live at A7, H02: the record and the wrong place were one sentence, cut whole."""
        given = [self.TEAM, "| Losses | 29 | 6th of 30 | 41 |"]
        answer = (
            "The Knicks had a record of 53 wins and 29 losses, placing them 6th in the Eastern "
            "Conference. They won the title."
        )
        text, removed = cut(answer, given)
        assert text == "The Knicks had a record of 53 wins and 29 losses. They won the title."
        assert removed == ("6",)

    def test_what_leans_on_a_cut_clause_goes_with_it(self) -> None:
        """Live at A7, E01: the cut kept "as the league was split into conferences at that
        time)", a remark on the place it had taken out, and its closing bracket."""
        given = [self.TEAM, "| Losses | 29 | 6th of 30 | 41 |"]
        answer = "They had 53 wins and 29 losses, 6th in the Eastern Conference, as it stood then."
        text, removed = cut(answer, given)
        assert (text, removed) == ("They had 53 wins and 29 losses.", ("6",))

    @pytest.mark.parametrize(
        ("answer", "kept"),
        [
            (
                "They had 53 wins (a strong year, 6th in the Eastern Conference).",
                "They had 53 wins.",
            ),
            ("They had **53 wins, 6th in the Eastern Conference**.", "They had **53 wins**."),
        ],
    )
    def test_a_cut_leaves_no_bracket_or_bold_open(self, answer: str, kept: str) -> None:
        assert cut(answer, [self.TEAM])[0] == kept

    def test_a_place_in_the_main_clause_takes_the_sentence(self) -> None:
        text, _ = cut("The Knicks were 6th in the East, with 53 wins. They won it.", [self.TEAM])
        assert text == "They won it."

    def test_a_made_up_figure_still_takes_the_sentence(self) -> None:
        text, removed = cut("They won 53, placing them 6th in the East, by 99 points.", [self.TEAM])
        assert (text, removed) == ("", ("6", "99"))

    @pytest.mark.parametrize(
        "written",
        [
            "They won 53, 6th in the league.",
            "They won 53, the NBA's 6th-most.",
            "They won 53, 6th overall.",
            "Their 53 wins were 6th of 30.",
            "They won 53 games, 6th.",
            "They finished 3rd in the Eastern Conference with 53 wins.",
            "They were the 3rd seed.",
            "They were 3rd in the East and 6th in the league with 53 wins.",
        ],
    )
    def test_a_place_for_its_own_field_stands(self, written: str) -> None:
        assert check(written, [self.TEAM]).ok

    @pytest.mark.parametrize(
        "written",
        [
            "They were 3rd in the league.",
            "They were 3rd in the West.",
            "They were 6th in the East.",
        ],
    )
    def test_a_place_for_another_field_does_not(self, written: str) -> None:
        assert not check(written, [self.TEAM]).ok

    def test_the_standings_and_the_bracket_name_their_conference(self) -> None:
        standings = "| East | 3rd in the East | New York Knicks | 53-29 | +6.3 | Lost in the second round |"  # fmt: skip
        assert check("The Knicks were 3rd in the East at 53-29.", [standings]).ok
        assert not check("The Knicks were 3rd in the league at 53-29.", [standings]).ok

    def test_a_place_a_result_writes_alone_is_the_league_s(self) -> None:
        given = ["| Points | 28.7 | 12th of 211 |", "| Assists | 99th percentile |"]
        assert check("He was 12th in the league in points.", given).ok
        assert not check("He was 12th in the West in points.", given).ok
        assert check("He was in the 99th percentile.", given).ok
