"""Accounts for the lab's API: who may sign in, and the questions each one asked.

Decision 0019. A user signs in with a name and a password and receives a token; the
questions they ask the lab's documents are kept with their answers, theirs alone. The rules
for a name and a password are here, in one place: the API's request models and the account
service both read them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from front_office.domain.rag import CitedSource

USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
"""A name: 3 to 32 lower-case letters, digits, dots, hyphens or underscores, starting with a
letter or a digit. Names are compared in lower case, so "Josh" and "josh" are one name."""
USERNAME_HELP = (
    "3 to 32 letters, digits, dots, hyphens or underscores, starting with a letter or a digit"
)
PASSWORD_MIN = 8
"""Characters a password needs at least."""
PASSWORD_BYTES = 72
"""The most a password may hold, in UTF-8 bytes: bcrypt reads no further, and a longer one
would be cut without a word."""


class AccountRuleError(ValueError):
    """A name or a password the rules do not allow."""


def normal_username(name: str) -> str:
    """A name as it is kept and compared: trimmed and in lower case."""
    return name.strip().lower()


def check_username(name: str) -> str:
    """The name, normalised, or :class:`AccountRuleError`."""
    normal = normal_username(name)
    if not USERNAME.fullmatch(normal):
        raise AccountRuleError(f"a name must be {USERNAME_HELP}")
    return normal


def check_password(password: str) -> str:
    """The password as given, or :class:`AccountRuleError`. Never trimmed: a space is part
    of a password."""
    if len(password) < PASSWORD_MIN:
        raise AccountRuleError(f"a password needs at least {PASSWORD_MIN} characters")
    if len(password.encode("utf-8")) > PASSWORD_BYTES:
        raise AccountRuleError(f"a password may hold at most {PASSWORD_BYTES} bytes")
    return password


def sign_in_ends(signed_in_at: datetime, minutes: int) -> datetime:
    """When a sign-in made at ``signed_in_at`` stops counting. The workbench's sign-in lasts as
    long as one of the API's tokens (``sign_in.token_minutes``, decision 0020)."""
    return signed_in_at + timedelta(minutes=minutes)


@dataclass(frozen=True, slots=True)
class User:
    """Someone who may sign in to the API. The password is never part of it."""

    user_id: int
    username: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AskedQuestion:
    """A question a user asked the lab's documents, with the answer it got - kept exactly as
    it was given, whatever the documents say since."""

    question_id: int
    user_id: int
    question: str
    answer: str
    sources: tuple[CitedSource, ...]
    model: str
    """The chat model that wrote the answer."""
    asked_at: datetime
    seconds: float
    notes: tuple[str, ...] = ()


def sources_to_json(sources: Sequence[CitedSource]) -> str:
    """The sources as the questions table keeps them."""
    return json.dumps([asdict(source) for source in sources], ensure_ascii=False)


def sources_from_json(text: str) -> tuple[CitedSource, ...]:
    """The sources as :func:`sources_to_json` wrote them."""
    return tuple(CitedSource(**item) for item in json.loads(text))


def notes_to_json(notes: Sequence[str]) -> str | None:
    """The notes as the questions table keeps them: none is null, never an empty list."""
    return json.dumps(list(notes), ensure_ascii=False) if notes else None


def notes_from_json(text: str | None) -> tuple[str, ...]:
    return tuple(json.loads(text)) if text else ()
