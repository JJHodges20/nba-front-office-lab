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

A place is checked for what it ranks as well, wherever the answer says (A7, the user's wish
at the A6 review): "6th in the Eastern Conference" needs a 6th in the East among the
results, and the league's 6th does not hold it. The tools write every place with its field
- "4th of 30", "3rd in the East" - and a place a result writes without one is the league's.

What it cannot see: whether a figure is attached to the right thing. A real figure written
under the wrong label - a league average given as a team's, a team's rank in one measure
given for another - passes here; the evaluation's frozen figures (docs/AI_EVALUATION.md)
are what measure that.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-+−])?(?P<dollar>\$)?(?P<digits>\d{1,3}(?:,\d{3})+|\d+)(?P<fraction>\.\d+)?"
    r"(?P<percent>%)?(?:\s?(?P<scale>million|billion|thousand|M|B|K)\b)?"
)
MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
NOT_FIGURES = re.compile(
    r"(?<!\d)(?:19|20)\d{2}[-–—‑]\d{2}(?:-\d{2})?(?!\d)"  # 2025-26, 2025–26, 2026-10-09
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
TOOL_FOR_THE_USER = (
    "the user cannot call the lab's tools: say in plain words what the lab can show, or call "
    "the tool yourself"
)
NAMED_FOR_USE = re.compile(
    r"\b(?:use|call|run|try|via|using|through)\s+(?:the\s+)?[`'\"]?"
    r"(?P<name>[a-z]+(?:_[a-z]+)+)[`'\"]?",
    re.IGNORECASE,
)
"""A tool's name given to the user to use: "Use the roster_fit tool to verify..." (R03, A8).
Before any result the orchestrator holds it to like a promise (A5); after one it is wording
the user can do nothing with. A page's name is the user's to use, and stays."""
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
    scope: str | None = None
    """For a place, what it ranks, where the words around it say: :data:`LEAGUE`,
    :data:`EAST`, :data:`WEST`, or :data:`CONFERENCE` when they do not say which."""


ORDINAL = ("st", "nd", "rd", "th")
LEAGUE, EAST, WEST, CONFERENCE = "league", "east", "west", "conference"
FIELD_WORDS = {
    LEAGUE: "in the league",
    EAST: "in the East",
    WEST: "in the West",
    CONFERENCE: "in a conference",
}
SCOPE_AFTER = 60
"""Characters after a place read for what it ranks - up to the next figure or the end of the
clause, so that "6th in the East and 10th in the league" gives each its own."""
CLAUSE_END = re.compile(r"[.;:!?\n|,(\[]|\d")
OUT_OF = re.compile(r"\s*(?:out\s+)?of\s+(?P<field>\d+)\b", re.IGNORECASE)
"""\"4th of 30\": 30 teams are the league, 15 a conference."""
EAST_WORDS = re.compile(r"\beast(?:ern)?\b", re.IGNORECASE)
WEST_WORDS = re.compile(r"\bwest(?:ern)?\b", re.IGNORECASE)
CONFERENCE_WORDS = re.compile(r"\b(?:conference|seed(?:ed)?)\b", re.IGNORECASE)
LEAGUE_WORDS = re.compile(r"\b(?:league|nba|overall)\b|\b30\s+teams\b", re.IGNORECASE)
OWNER = re.compile(
    r"\b(?P<field>east(?:ern(?:\s+conference)?)?|west(?:ern(?:\s+conference)?)?|league|nba)"
    r"(?:'s|’s)\s*$",
    re.IGNORECASE,
)
"""Before a place: "the East's 3rd seed", "the league's 6th-best offense"."""


def place_scope(text: str, start: int, end: int) -> str | None:
    """What the place whose number runs from ``start`` to ``end`` in ``text`` ranks, from
    the words around it; ``None`` where they do not say."""
    after = text[end + 2 : end + 2 + SCOPE_AFTER]
    counted = OUT_OF.match(after)
    if counted is not None:
        return {"30": LEAGUE, "15": CONFERENCE}.get(counted.group("field"))
    stop = CLAUSE_END.search(after)
    if stop is not None:
        after = after[: stop.start()]
    owner = OWNER.search(text[max(0, start - 30) : start])
    words = f"{after} {owner.group('field') if owner else ''}"
    for pattern, field in (
        (EAST_WORDS, EAST),
        (WEST_WORDS, WEST),
        (CONFERENCE_WORDS, CONFERENCE),
        (LEAGUE_WORDS, LEAGUE),
    ):
        if pattern.search(words):
            return field
    return None


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
                place_scope(text, match.start(), match.end()) if place else None,
            )
        )
    return found


def same_field(written: str, given: str | None) -> bool:
    """Whether a place given for ``given`` holds one written for ``written``. A place a
    result writes without its field is the league's: the tools name every conference."""
    given = given or LEAGUE
    if written == CONFERENCE:
        return given in (EAST, WEST, CONFERENCE)
    return written == given


def supports(given: Figure, written: Figure) -> bool:
    """Whether a figure the model was given holds one it wrote, at the written precision.
    A place stands only on a place: "6th in the league" needs a 6th among the results, and
    a place named for a field - the league, a conference - one for the same field."""
    if written.ordinal and not given.ordinal:
        return False
    if written.ordinal and written.scope is not None and not same_field(written.scope, given.scope):
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
class Misplaced:
    """A place the results hold, written for a field they do not hold it for."""

    figure: Figure
    fields: tuple[str, ...]
    """The fields the results hold this place for."""
    held: tuple[str, ...]
    """The places the results hold for the field the answer named: "3rd". Live at A7 a
    model told only that its 6th was the league's wrote it again for the East."""


@dataclass(frozen=True, slots=True)
class Check:
    unsupported: tuple[Figure, ...]
    misplaced: tuple[Misplaced, ...] = ()
    """Unsupported places the results do hold, for another field."""

    @property
    def ok(self) -> bool:
        return not self.unsupported

    @property
    def listed(self) -> str:
        return ", ".join(dict.fromkeys(figure.text for figure in self.unsupported))

    @property
    def only_misplaced(self) -> bool:
        """Whether every figure that does not stand is a place written for the wrong field."""
        placed = {item.figure for item in self.misplaced}
        return not self.ok and all(figure in placed for figure in self.unsupported)


def check(answer: str, given: Iterable[str]) -> Check:
    """The figures of ``answer`` that nothing in ``given`` holds."""
    known = [figure for text in given for figure in figures(text)]
    unsupported = tuple(
        written
        for written in figures(answer)
        if not any(supports(figure, written) for figure in known)
    )
    misplaced = []
    for written in unsupported:
        if not written.ordinal or written.scope is None:
            continue
        unnamed = replace(written, scope=None)
        fields = tuple(
            dict.fromkeys(figure.scope or LEAGUE for figure in known if supports(figure, unnamed))
        )
        if fields:
            held = sorted(
                {
                    int(abs(figure.value))
                    for figure in known
                    if figure.ordinal and same_field(written.scope, figure.scope)
                }
            )
            misplaced.append(Misplaced(written, fields, tuple(_nth_of(value) for value in held)))
    return Check(unsupported, tuple(misplaced))


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
    found += [Wording(m.group("name"), TOOL_FOR_THE_USER) for m in NAMED_FOR_USE.finditer(answer)]
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
    placed = {item.figure for item in result.misplaced}
    missing = [figure for figure in result.unsupported if figure not in placed]
    if missing:
        listed = ", ".join(dict.fromkeys(figure.text for figure in missing))
        parts.append(
            f"These figures are in no tool result, the question or its context: {listed}. "
            "Write the answer again using only figures from the results, each cited like [r1], "
            "or leave them out and say what is missing."
        )
    if result.misplaced:
        said = "; ".join(_misplaced(item) for item in result.misplaced)
        parts.append(
            f"These places rank something the results do not: {said}. Give each place as the "
            "result gives it - for the league, or for the team's conference - or leave it out, "
            "and keep everything else as it was, each figure cited like [r1]."
        )
    for rule in dict.fromkeys(item.rule for item in phrases):
        said = ", ".join(dict.fromkeys(f'"{item.phrase}"' for item in phrases if item.rule == rule))
        parts.append(f"Do not write {said}: {rule}.")
    if bare:
        parts.append(WITH_INTERVALS)
    if parts:
        parts.append(FOR_THE_USER)
    return " ".join(parts)


PLACES_LISTED = 3
"""Places the note names for a field; more, and it points to the standings instead."""


def _misplaced(item: Misplaced) -> str:
    place, field = _nth(item.figure), FIELD_WORDS[item.figure.scope or LEAGUE]
    holds = " and ".join(FIELD_WORDS[name] for name in item.fields)
    if not item.held:
        instead = f"they give no place {field}"
    elif len(item.held) > PLACES_LISTED:
        instead = f"{field} they give every place, in the standings"
    else:
        instead = f"{field} they give {' and '.join(item.held)}"
    return f"{place} {field} (the results' {place} is {holds}; {instead})"


def _nth(place: Figure) -> str:
    """A place as it is said: 1st, 2nd, 3rd, 11th, 22nd."""
    return _nth_of(int(abs(place.value)))


def _nth_of(number: int) -> str:
    suffix = (
        "th" if number % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


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
    Lines are kept as lines, so that a list stays a list. A sentence whose only fault is a
    place written for the wrong field is cut at that clause instead, when its main clause
    stands without it (A7): at A7 "a record of 53 wins and 29 losses, placing them 6th in the
    Eastern Conference" was cut whole, and the answer lost the record it was asked for."""
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
                continue
            removed.extend(figure.text for figure in result.unsupported)
            shorter = _without_places(sentence, given) if result.only_misplaced else None
            if shorter:
                kept.append(shorter)
        if kept or not line.strip():
            lines.append(" ".join(kept))
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text), tuple(dict.fromkeys(removed))


CLAUSE = re.compile(r",\s+|;\s+|\s+[-–—]\s+")


def _without_places(sentence: str, given: Sequence[str]) -> str | None:
    """The sentence up to its first clause that does not stand, if that is not its first.
    What follows a cut clause goes with it: at A7 a cut that kept every clause standing left
    "15 wins and 67 losses, as the league was split into conferences at that time)" - a
    remark on the place it had taken out, and that place's closing bracket."""
    text = sentence.strip()
    end = text[-1] if text[-1] in ".!?" else ""
    body = text[:-1] if end else text
    seams = list(CLAUSE.finditer(body))
    starts = [0, *(seam.end() for seam in seams)]
    stops = [*(seam.start() for seam in seams), len(body)]
    standing = 0
    for start, stop in zip(starts, stops, strict=True):
        if not check(body[start:stop], given).ok:
            break
        standing = stop
    else:
        return None  # each clause stands alone: what fails spans them
    shorter = _closed(body[:standing]).rstrip(",;-–— ")
    if not shorter:
        return None
    shorter += end or "."
    return shorter if check(shorter, given).ok else None


def _closed(text: str) -> str:
    """The text without a bracket it leaves open and what follows it, and its bold closed."""
    opened: list[int] = []
    for index, character in enumerate(text):
        if character in "([":
            opened.append(index)
        elif character in ")]" and opened:
            opened.pop()
    if opened:
        text = text[: opened[0]].rstrip()
    return text + "**" if text.count("**") % 2 else text


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
