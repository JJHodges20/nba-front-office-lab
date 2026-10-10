"""Names in a question, found and resolved before the model is asked.

The A1 benchmark showed models guessing: one Brown chosen of two, a team id invented. So
names are found here, by code (decision 0018): a season label, a year, a run of capitalised
words that is a team's or a player's name. A name with one reading goes to the model as an
id; a name with several makes the assistant ask which, and the model is not asked at all.
A name not found is left to the model, which may look it up with ``resolve_entities``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from front_office.domain.assistant import NameCandidate
from front_office.services.entities import (
    BARE_YEAR,
    SEASON_LABEL,
    Candidate,
    EntityService,
    fold,
)

# Capitalised words a question uses that are not anybody's name here, or not on their own.
STOPWORDS = frozenset(
    """
    a about after against all an and any are as at b be been before best between both but
    by can compare could did do does during each east eastern for from get give had has
    have he her here him his how i if in into is it its last league let list me more most
    my next nba no not of on or our please per pull search season seasons she should show
    since so some star summarise summarize team teams tell than that the their them then
    there these they this those to today tomorrow top was we were west western what when
    where which while who whom whose why will with would yesterday you your
    mvp ppg rpg apg ts efg war espn yahoo cbs nbc tnt abc
    conference finals final playoffs playoff postseason championship title cup draft rookie
    coach option quick deep
    january february march april may june july august september october november december
    monday tuesday wednesday thursday friday saturday sunday
    """.split()
)
WORD = re.compile(r"[^\W\d_][\w'’.\-]*")
MAX_WORDS = 4
SHOWN_OPTIONS = 6
SEASON_ENDING = re.compile(
    r"\s*(?:nba\s+)?(?:playoffs?|finals?|champions?|championship|title|postseason|play-?in|"
    r"trade deadline|deadline|all-?star|mvp|awards?)\b",
    re.IGNORECASE,
)
"""After a bare year: something that happens in the season ending that year - the 2026
playoffs are 2025-26's."""
BETWEEN_SEASONS = re.compile(
    r"\s*(?:nba\s+)?(?:draft|g league|offseason|off-season|free agency|summer league)\b",
    re.IGNORECASE,
)
"""After a bare year: something between seasons, which is no season to ask about."""


@dataclass(frozen=True, slots=True)
class Mention:
    """A name as the question wrote it, and every reading of it."""

    text: str
    candidates: tuple[Candidate, ...]

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1

    def names(self) -> tuple[NameCandidate, ...]:
        """The readings as the model's context lists them."""
        return tuple(
            NameCandidate(text=self.text, kind=c.kind, id=c.id, name=c.name)
            for c in self.candidates
        )


def find_mentions(
    question: str, entities: EntityService, *, season: str | None = None
) -> tuple[Mention, ...]:
    """Every season and name in ``question``, in the order written.

    Players and teams are read in the season the question names, when it names exactly
    one, else in ``season`` (the sidebar's).
    """
    found: list[tuple[int, Mention]] = []
    rest = question

    def blank(start: int, end: int) -> None:
        nonlocal rest
        rest = rest[:start] + " " * (end - start) + rest[end:]

    for pattern in (SEASON_LABEL, BARE_YEAR):
        for match in pattern.finditer(rest):
            candidates = entities.seasons(match.group(0))
            if pattern is BARE_YEAR:
                after = question[match.end() :]
                if BETWEEN_SEASONS.match(after):
                    candidates = ()  # the 2026 draft: no season meant
                elif SEASON_ENDING.match(after):
                    candidates = candidates[:1]  # the 2026 playoffs: 2025-26's
            if candidates:
                found.append((match.start(), Mention(match.group(0), candidates)))
            blank(match.start(), match.end())
    named = {c.id for _, mention in found if not mention.ambiguous for c in mention.candidates}
    within = next(iter(named)) if len(named) == 1 else (None if named else season)

    for start, words in _capitalised_runs(rest):
        index = 0
        while index < len(words):
            for length in range(min(MAX_WORDS, len(words) - index), 0, -1):
                span = words[index : index + length]
                mention = _read(span, entities, within, initial=start == 0 and index == 0)
                if mention is not None:
                    found.append((span[0][0], mention))
                    index += length
                    break
            else:
                index += 1
    return tuple(mention for _, mention in sorted(found, key=lambda item: item[0]))


def _read(
    span: Sequence[tuple[int, str]], entities: EntityService, season: str | None, *, initial: bool
) -> Mention | None:
    text = " ".join(word for _, word in span)
    if len(span) == 1 and (len(text) < 2 or fold(text) in STOPWORDS):
        return None
    teams = entities.find_teams(text, season)
    if teams:
        return Mention(text, teams)
    if len(span) == 1 and initial:
        # A capitalised first word is as likely an ordinary word as a player's name.
        return None
    players = entities.find_players(text, season)
    return Mention(text, players) if players else None


def _capitalised_runs(text: str) -> list[tuple[int, list[tuple[int, str]]]]:
    """Runs of capitalised words separated only by spaces, each word cleaned of a
    possessive and of trailing punctuation; the run's ``start`` is 0 when it opens the
    question or a sentence."""
    runs: list[tuple[int, list[tuple[int, str]]]] = []
    previous_end = None
    for match in WORD.finditer(text):
        word = _clean(match.group(0))
        if not word or not word[0].isupper():
            previous_end = None
            continue
        between = text[previous_end : match.start()] if previous_end is not None else None
        if between is not None and between.strip() == "" and runs:
            runs[-1][1].append((match.start(), word))
        else:
            opening = text[: match.start()].rstrip()
            starts_sentence = opening == "" or opening.endswith((".", "!", "?"))
            runs.append((0 if starts_sentence else match.start(), [(match.start(), word)]))
        previous_end = match.end() if not match.group(0).endswith((",", ";", ":")) else None
    return runs


def _clean(word: str) -> str:
    word = word.rstrip(".,;:!?")
    for suffix in ("'s", "’s", "'", "’"):
        if word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    return word


def clarification(mention: Mention) -> str:
    """The question back for an ambiguous name, its readings listed."""
    kind = mention.candidates[0].kind
    shown = mention.candidates[:SHOWN_OPTIONS]
    if kind == "season":
        options = [f"{c.name} ({c.detail})" for c in shown]
        what = f'Which season do you mean by "{mention.text}"'
    elif kind == "team":
        options = [c.name for c in shown]
        what = f'Which team do you mean by "{mention.text}"'
    else:
        options = [f"{c.name} ({c.detail})" if c.detail else c.name for c in shown]
        what = f'Which player do you mean by "{mention.text}"'
    more = len(mention.candidates) - len(shown)
    listed = ", ".join(options[:-1]) + f" or {options[-1]}" if len(options) > 1 else options[0]
    tail = f", or one of {more} others (give the full name)" if more > 0 else ""
    return f"{what}: {listed}{tail}?"
