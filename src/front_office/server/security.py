"""Sign-in tokens and the key that signs them (decision 0019).

A token is a JWT signed with HS256: it names its user by id (``sub``), says who issued it
(``iss``) and when (``iat``), and stops working when it expires (``exp``). Changing a
single character of it breaks the signature. The key is the user's own: ``FOL_API_SECRET``
from the environment or the project's git-ignored ``.env``. When neither gives one, the API
makes a key once, keeps it in the data folder beside the accounts, and uses it from then on.
The key is never printed, logged or returned.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

from front_office.config.settings import ConfigError, Settings
from front_office.domain.env_file import setting_in

SECRET_VARIABLE = "FOL_API_SECRET"
KEY_FILE = "signing.key"
ALGORITHM = "HS256"
ISSUER = "nba-front-office-lab"
SECRET_MIN_BYTES = 32
"""RFC 7518 (3.2): an HS256 key must be at least as long as the hash it makes."""


class TokenRefused(Exception):
    """A token that signs nobody in: malformed, altered, signed with another key, issued by
    someone else, or expired."""

    def __init__(self, reason: str, *, expired: bool = False) -> None:
        super().__init__(reason)
        self.expired = expired


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_at: datetime
    seconds: int
    """How long the token lasts, from the moment it was issued."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Tokens:
    """Issues tokens and reads them back."""

    def __init__(
        self, secret: str, *, minutes: int, now: Callable[[], datetime] = _utc_now
    ) -> None:
        if len(secret.encode("utf-8")) < SECRET_MIN_BYTES:
            raise ValueError(f"a signing key needs at least {SECRET_MIN_BYTES} bytes")
        self._secret = secret
        self._minutes = minutes
        self._now = now

    def __repr__(self) -> str:  # never the key
        return f"Tokens(minutes={self._minutes})"

    def issue(self, user_id: int) -> IssuedToken:
        moment = self._now()
        expires = moment + timedelta(minutes=self._minutes)
        claims = {"sub": str(user_id), "iss": ISSUER, "iat": moment, "exp": expires}
        token = jwt.encode(claims, self._secret, algorithm=ALGORITHM)
        return IssuedToken(token=token, expires_at=expires, seconds=self._minutes * 60)

    def user_id(self, token: str) -> int:
        """The id of the user a token signs in, or :class:`TokenRefused`. Expiry is read
        against the clock of this machine."""
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                issuer=ISSUER,
                options={"require": ["sub", "iss", "iat", "exp"]},
            )
        except jwt.ExpiredSignatureError:
            raise TokenRefused("the sign-in has expired", expired=True) from None
        except jwt.InvalidTokenError as error:
            raise TokenRefused(f"the token is not valid: {error}") from None
        subject = claims["sub"]
        if not subject.isdigit():
            raise TokenRefused("the token names no user")
        return int(subject)


def signing_secret(settings: Settings) -> str:
    """The key that signs tokens: ``FOL_API_SECRET`` from the environment, else from the
    project's ``.env``, else the key file in the data folder - made the first time, with a
    random key of 64 characters."""
    given = os.environ.get(SECRET_VARIABLE, "").strip()
    if not given:
        env_file = settings.project_root / ".env"
        if env_file.is_file():
            given = setting_in(env_file.read_bytes(), SECRET_VARIABLE) or ""
    if given:
        if len(given.encode("utf-8")) < SECRET_MIN_BYTES:
            raise ConfigError(
                f"{SECRET_VARIABLE} is too short: a signing key needs at least "
                f"{SECRET_MIN_BYTES} characters"
            )
        return given
    return _key_file(settings.api_dir / KEY_FILE)


def _key_file(path: Path) -> str:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        made = secrets.token_urlsafe(48)
        try:
            # Made only if absent: two servers starting at once keep one key between them.
            with path.open("x", encoding="ascii") as handle:
                handle.write(made + "\n")
        except FileExistsError:
            pass
        else:
            # Readable by its owner alone where the system honours it (not on Windows, where
            # the data folder's own permissions apply).
            path.chmod(0o600)
    kept = path.read_text(encoding="utf-8").strip()
    if len(kept.encode("utf-8")) < SECRET_MIN_BYTES:
        raise ConfigError(f"{path} holds no usable signing key; delete it and the API makes one")
    return kept
