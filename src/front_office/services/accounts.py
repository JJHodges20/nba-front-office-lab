"""Accounts for the lab's API (decision 0019): registering, signing in, and the questions a
user asked.

A password is kept only as a bcrypt hash, made with a salt of its own when the user
registers and checked against when they sign in; the password itself is never stored,
returned or logged. Signing in with a name nobody has takes as long as with a wrong
password - a hash is checked either way - so how long it takes says nothing about which
names exist.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import bcrypt

from front_office.domain.accounts import (
    PASSWORD_BYTES,
    AskedQuestion,
    User,
    check_password,
    check_username,
    normal_username,
)
from front_office.domain.rag import CitedSource
from front_office.storage.accounts import AccountNotFound, AccountStore, NameTaken

_NOBODY = b"the password of a name nobody has"


class AccountService:
    """Accounts in the file at ``path``, which is opened afresh for every call."""

    def __init__(self, path: Path, *, rounds: int) -> None:
        self.path = Path(path)
        self._rounds = rounds
        self._nobody: bytes | None = None

    def _store(self) -> AccountStore:
        return AccountStore(self.path)

    def _hash(self, password: str) -> str:
        salt = bcrypt.gensalt(rounds=self._rounds)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")

    # --- users -----------------------------------------------------------------------------

    def register(self, username: str, password: str) -> User:
        """A new user. Raises :class:`~front_office.domain.accounts.AccountRuleError` for a
        name or a password the rules refuse, and :class:`NameTaken` for a name in use -
        names are compared in lower case."""
        name = check_username(username)
        hashed = self._hash(check_password(password))
        with self._store() as store:
            return store.create_user(name, hashed)

    def authenticate(self, username: str, password: str) -> User | None:
        """The user a name and a password sign in, or ``None``."""
        secret = password.encode("utf-8")
        if len(secret) > PASSWORD_BYTES:
            # No password this long was ever registered, and bcrypt refuses to read one.
            return None
        with self._store() as store:
            found = store.sign_in_record(normal_username(username))
        if found is None:
            bcrypt.checkpw(secret, self._nobody_hash())
            return None
        user, hashed = found
        return user if bcrypt.checkpw(secret, hashed.encode("ascii")) else None

    def _nobody_hash(self) -> bytes:
        """A hash to check a sign-in against when no user has the name, at the same cost."""
        if self._nobody is None:
            self._nobody = bcrypt.hashpw(_NOBODY, bcrypt.gensalt(rounds=self._rounds))
        return self._nobody

    def user(self, user_id: int) -> User:
        """Raises :class:`AccountNotFound` for an id nobody has - a deleted user's included."""
        with self._store() as store:
            return store.user(user_id)

    def remove(self, user_id: int) -> int:
        """Delete a user and every question they asked; returns how many questions went."""
        with self._store() as store:
            return store.delete_user(user_id)

    def count(self) -> int:
        with self._store() as store:
            return store.count_users()

    # --- questions -------------------------------------------------------------------------

    def record_question(
        self,
        user_id: int,
        *,
        question: str,
        answer: str,
        sources: Sequence[CitedSource],
        model: str,
        seconds: float,
        notes: Sequence[str] = (),
    ) -> AskedQuestion:
        with self._store() as store:
            return store.add_question(
                user_id,
                question=question,
                answer=answer,
                sources=sources,
                model=model,
                seconds=seconds,
                notes=notes,
            )

    def questions(self, user_id: int, *, limit: int | None = None) -> tuple[AskedQuestion, ...]:
        """A user's questions, the newest first."""
        with self._store() as store:
            return store.questions(user_id, limit=limit)

    def question(self, user_id: int, question_id: int) -> AskedQuestion:
        """One of the user's questions; another user's raises :class:`AccountNotFound`."""
        with self._store() as store:
            return store.question(user_id, question_id)

    def forget_question(self, user_id: int, question_id: int) -> None:
        with self._store() as store:
            store.delete_question(user_id, question_id)


__all__ = ["AccountNotFound", "AccountService", "NameTaken"]
