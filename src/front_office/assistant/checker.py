"""Every figure in an answer must be one the assistant was given (decision 0018).

Numbers are read from a draft answer and from what the model was given - the tool results
exactly as it read them, the question and its context - and a figure in the answer stands
only if one of those holds it, to the precision the answer writes it: 8.3 stands on 8.31,
57% on 57.3%, $40M on $40,000,000, 4th on "4th of 30". Season labels, dates - "2026-10-01"
or "October 1, 2026" - years, result ids and the numbers of a numbered list are not figures,
and a record such as 56-26 is two. What does not stand is sent back once to be rewritten;
what still does not is cut out with its sentence.

The lab's language is checked the same way (``wording``): a chance in an answer that rests
on no chance - only the postseason model and the simulator give one, so a benchmark's
frequency called a chance is caught - a verdict: a contender, a signing that should be
made, a best roster - and a claim to have saved or changed anything, which the assistant
cannot do.

What it cannot see: whether a figure is attached to the right thing. A real figure written
under the wrong label - a league average given as a team's - passes here; the evaluation's
frozen figures (docs/AI_EVALUATION.md) are what measure that.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-+−])?(?P<dollar>\$)?(?P<digits>\d{1,3}(?:,\d{3})+|\d+)(?P<fraction>\.\d+)?"
    r"(?P<percent>%)?(?:\s?(?P<scale>million|billion|thousand|M|B|K)\b)?"
)
MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
NOT_FIGURES = re.compile(
    r"(?<!\d)(?:19|20)\d{2}-\d{2}(?:-\d{2})?(?!\d)"  # 2025-26, 2026-10-09
    rf"|\b{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+(?:19|20)\d{{2}})?\b"  # October 1, 2026
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}(?:,?\s+(?:19|20)\d{{2}})?\b"  # 1 October 2026
    r"|(?<![\d$.,])(?:19[4-9]\d|20\d{2})(?![\d%]|[.,]\d|\s?(?:million|billion|thousand|[MBK])\b)"  # 2026
    r"|(?m:^)[ \t]*\d{1,2}[.)](?=[ \t])"  # 1. or 2) opening a line: a list, not a figure
    r"|\b(?:per|every)\s+(?:100\s+possessions|82\s+games)\b"  # the lab's units (A5: S02, M03)
    r"|\[[a-z]{1,2}\d{1,4}\]"  # [r1], [s2]
    r"|(?<![\w.])[a-z]{1,2}\d{1,4}(?![\w.])"  # r1, u3
)
BETWEEN_DIGITS = re.compile(r"(?<=\d)[-–](?=\d)")
CHANCE = re.compile(r"\b(?:chances?|probabilit(?:y|ies)|odds (?:of|to|that))\b", re.IGNORECASE)
DENIED = re.compile(
    r"\b(?:not|never|rather than|instead of|is(?:n't|’t| not)|are(?:n't|’t| not))\b[^.;:!?]{0,30}$",
    re.IGNORECASE,
)
"""Just before a chance word: the answer says what a figure is not - "a frequency among past
teams, not a team's chance" - which the lab's rules ask for."""
VERDICT = re.compile(
    r"\b(?:(?:title |championship )?contenders?"
    r"|should (?:sign|trade for|trade|acquire|pursue|target)"
    r"|(?:the )?best (?:roster|option|choice|signing|move|trade))\b",
    re.IGNORECASE,
)
DONE_FOR_THE_USER = re.compile(
    r"\b(?:has been|have been|is now|are now)\s+(?:successfully\s+)?"
    r"(?:saved|deleted|stored|applied|refitted)\b"
    r"|\b(?:i|we)(?:'ve|’ve| have)?\s+(?:now\s+|successfully\s+)?"
    r"(?:saved|deleted|removed|updated|changed|refitted|refit|applied|stored)\b",
    re.IGNORECASE,
)
"""A claim to have saved or changed something: the assistant cannot, and must not say so."""
CHANCE_TOOLS = frozenset({"postseason_outlook", "simulate_scenario"})
"""The only tools whose results are chances (decisions 0009, 0014, 0015)."""
ABOUT_CHANCES = CHANCE_TOOLS | {"research_docs"}
"""The tools a chance word may rest on: the two that give chances, and the lab's documents,
which describe them. At A4 an answer explaining the postseason model from its decision had
"chances" cut."""
INTERVAL_TOOLS = CHANCE_TOOLS | {"historical_benchmarks"}
"""The tools whose shares come with intervals: a model's chance and a benchmark's frequency,
which the rules give only with their intervals (rule 4)."""
INTERVAL = re.compile(r"\binterval", re.IGNORECASE)
WITH_INTERVALS = (
    "Your answer gives percentages without their intervals. Write it again with each chance "
    'or share followed by its interval as the result writes it - "X% (95% interval Y% to '
    'Z%)" - as rule 4 asks, and keep everything else as it was.'
)
FOR_THE_USER = (
    "Write the whole answer for the user, as if for the first time: do not mention this note "
    "or that anything was corrected."
)
"""Closing every note sent back: at A2, and again at A5 (R01: "Here's the corrected
version"), a model answered the note instead of the user."""
INTERVALS_IN_ROWS = (
    "Some percentages above are given without their 95% interval; each interval is in the "
    "table below."
)
FREQUENCY_NOT_CHANCE = (
    "only the postseason model and the simulator give a chance; a benchmark is how often "
    "past teams did something - say it as a count and a share"
)
NO_VERDICT = "no verdicts or recommendations: lay out the evidence and the trade-offs"
NOTHING_DONE = (
    "you cannot save, change or delete anything; say so, and what the user can do instead"
)
SCALES = {"thousand": 10**3, "k": 10**3, "million": 10**6, "m": 10**6, "billion": 10**9, "b": 10**9}
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[*\"'-])")


@dataclass(frozen=True, slots=True)
class Figure:
    """A number as written: its value, how finely it is written, whether it is a share."""

    text: str
    value: float
    step: float
    """The precision written: 0.1 for 8.3, 1,000,000 for $40M."""
    percent: bool
    signed: bool
    ordinal: bool = False
    """A place - 4th, 21st - which only a place can hold: a 6th is no 6.3."""


ORDINAL = ("st", "nd", "rd", "th")


def figures(text: str) -> list[Figure]:
    masked = NOT_FIGURES.sub(lambda match: " " * len(match.group()), text)
    masked = BETWEEN_DIGITS.sub(" ", masked)
    found = []
    for match in NUMBER.finditer(masked):
        digits = match.group("digits").replace(",", "")
        fraction = match.group("fraction") or ""
        scale = SCALES.get((match.group("scale") or "").lower(), 1)
        value = float(digits + fraction) * scale
        step = (10.0 ** -(len(fraction) - 1) if fraction else 1.0) * scale
        sign = match.group("sign")
        if sign in ("-", "−"):
            value = -value
        place = not fraction and masked[match.end() : match.end() + 2].lower() in ORDINAL
        found.append(
            Figure(
                match.group(0).strip(),
                value,
                step,
                bool(match.group("percent")),
                sign is not None,
                place,
            )
        )
    return found


def supports(given: Figure, written: Figure) -> bool:
    """Whether a figure the model was given holds one it wrote, at the written precision.
    A place stands only on a place: "6th in the league" needs a 6th among the results."""
    if written.ordinal and not given.ordinal:
        return False
    tolerance = written.step / 2 + 1e-9 * max(1.0, abs(written.value))
    candidates = [given.value]
    if given.percent and not written.percent:
        candidates.append(given.value / 100)
    if written.percent and not given.percent:
        candidates.append(given.value * 100)
    for value in candidates:
        if written.signed and abs(value - written.value) <= tolerance:
            return True
        if not written.signed and abs(abs(value) - abs(written.value)) <= tolerance:
            return True
    return False


@dataclass(frozen=True, slots=True)
class Check:
    unsupported: tuple[Figure, ...]

    @property
    def ok(self) -> bool:
        return not self.unsupported

    @property
    def listed(self) -> str:
        return ", ".join(dict.fromkeys(figure.text for figure in self.unsupported))


def check(answer: str, given: Iterable[str]) -> Check:
    """The figures of ``answer`` that nothing in ``given`` holds."""
    known = [figure for text in given for figure in figures(text)]
    return Check(
        tuple(
            written
            for written in figures(answer)
            if not any(supports(figure, written) for figure in known)
        )
    )


CITATION = re.compile(r"\[(?:table\s+|chart\s+)?(r\d{1,4})\]", re.IGNORECASE)


def phantoms(answer: str, ids: Iterable[str]) -> tuple[str, ...]:
    """The results ``answer`` cites that do not exist: a model that has seen "[table r1]"
    in an earlier turn may write "[table r2]" without calling anything."""
    known = {result_id.lower() for result_id in ids}
    cited = (match.group(1).lower() for match in CITATION.finditer(answer))
    return tuple(dict.fromkeys(result_id for result_id in cited if result_id not in known))


def cut_phantoms(answer: str, ids: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """The answer without the sentences that cite a result that does not exist."""
    ids = tuple(ids)
    removed: list[str] = []
    lines: list[str] = []
    for line in answer.splitlines():
        kept = []
        for sentence in SENTENCE.split(line):
            if not sentence.strip():
                continue
            missing = phantoms(sentence, ids)
            if missing:
                removed.extend(missing)
            else:
                kept.append(sentence.strip())
        if kept or not line.strip():
            lines.append(" ".join(kept))
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text), tuple(dict.fromkeys(removed))


@dataclass(frozen=True, slots=True)
class Wording:
    """A phrase the lab's rules do not allow, and the rule."""

    phrase: str
    rule: str


def wording(answer: str, tools: Iterable[str]) -> tuple[Wording, ...]:
    """Phrases of ``answer`` that break the lab's language: a chance where no result is a
    chance, a verdict anywhere. ``tools`` are the tools whose results the answer rests on."""
    found = []
    if not set(tools) & ABOUT_CHANCES:
        found += [
            Wording(m.group(0), FREQUENCY_NOT_CHANCE)
            for m in CHANCE.finditer(answer)
            if not DENIED.search(answer[max(0, m.start() - 40) : m.start()])
        ]
    found += [Wording(m.group(0), NO_VERDICT) for m in VERDICT.finditer(answer)]
    found += [Wording(m.group(0), NOTHING_DONE) for m in DONE_FOR_THE_USER.finditer(answer)]
    return tuple(found)


def bare_shares(answer: str, tools: Iterable[str]) -> bool:
    """Whether the answer gives a model's chance or a benchmark's share without its
    interval: it rests on a tool whose shares come with one, states a percentage, and never
    says "interval". At A4 answers gave the shares alone, though every row held them."""
    if not set(tools) & INTERVAL_TOOLS or INTERVAL.search(answer):
        return False
    return any(figure.percent for figure in figures(answer))


def repair_note(
    result: Check,
    phrases: Sequence[Wording] = (),
    cited: Sequence[str] = (),
    *,
    bare: bool = False,
) -> str:
    parts = []
    if cited:
        parts.append(
            f"You cite {', '.join(cited)}, which no tool returned: cite only the results above, "
            "or leave the sentence out."
        )
    if not result.ok:
        parts.append(
            f"These figures are in no tool result, the question or its context: {result.listed}. "
            "Write the answer again using only figures from the results, each cited like [r1], "
            "or leave them out and say what is missing."
        )
    for rule in dict.fromkeys(item.rule for item in phrases):
        said = ", ".join(dict.fromkeys(f'"{item.phrase}"' for item in phrases if item.rule == rule))
        parts.append(f"Do not write {said}: {rule}.")
    if bare:
        parts.append(WITH_INTERVALS)
    if parts:
        parts.append(FOR_THE_USER)
    return " ".join(parts)


def cut_wording(answer: str, tools: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """The answer without the sentences whose wording breaks the lab's rules, and those
    phrases."""
    tools = tuple(tools)
    removed: list[str] = []
    lines: list[str] = []
    for line in answer.splitlines():
        kept = []
        for sentence in SENTENCE.split(line):
            if not sentence.strip():
                continue
            broken = wording(sentence, tools)
            if broken:
                removed.extend(item.phrase for item in broken)
            else:
                kept.append(sentence.strip())
        if kept or not line.strip():
            lines.append(" ".join(kept))
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text), tuple(dict.fromkeys(removed))


def cut(answer: str, given: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    """The answer without the sentences whose figures nothing holds, and those figures.
    Lines are kept as lines, so that a list stays a list."""
    removed: list[str] = []
    lines: list[str] = []
    for line in answer.splitlines():
        kept = []
        for sentence in SENTENCE.split(line):
            if not sentence.strip():
                continue
            result = check(sentence, given)
            if result.ok:
                kept.append(sentence.strip())
            else:
                removed.extend(figure.text for figure in result.unsupported)
        if kept or not line.strip():
            lines.append(" ".join(kept))
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text), tuple(dict.fromkeys(removed))


REPEATED = 40
"""Characters a sentence needs before saying it again counts as a loop rather than an echo."""


def without_repeats(answer: str) -> tuple[str, int]:
    """The answer with every sentence said a second time taken out, and how many were. At A4
    a model wrote one sentence over and over until its output ran out; a short phrase that
    recurs - "No change." - is left alone. Lines are kept as lines."""
    seen: set[str] = set()
    dropped = 0
    lines: list[str] = []
    for line in answer.splitlines():
        kept = []
        for sentence in SENTENCE.split(line):
            said = " ".join(sentence.split()).lower()
            if len(said) >= REPEATED and said in seen:
                dropped += 1
                continue
            seen.add(said)
            kept.append(sentence.strip())
        if kept or not line.strip():
            lines.append(" ".join(item for item in kept if item))
    if not dropped:
        return answer, 0
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), dropped
