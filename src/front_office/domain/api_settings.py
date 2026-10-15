"""``configs/api.yaml``: the lab's HTTP API (decision 0019).

How long a sign-in lasts, and how costly a password is to check. The key that signs the
tokens is not a setting: it is the user's own (``FOL_API_SECRET``), or one the API makes
in the data folder, and an unknown field - a key, say - is refused here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SignInSettings(_Settings):
    token_minutes: int = Field(60, ge=1, le=24 * 60)
    """How long a token signs its user in, from the moment it is issued."""
    password_rounds: int = Field(12, ge=4, le=16)
    """bcrypt's cost: each step doubles the work of checking one password, for the API and
    for anyone trying to guess it from a stolen hash. A password is hashed at the cost set
    when it was registered."""


class ApiSettings(_Settings):
    version: int = Field(ge=1)
    sign_in: SignInSettings = SignInSettings()
