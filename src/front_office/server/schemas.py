"""What the API accepts and returns: a Pydantic model for every request and response.

FastAPI validates each request against its model before an endpoint runs - a wrong type, a
missing field or an unknown one is refused with 422 and the reason - and each response
against its model before it is sent. The ``/docs`` page is drawn from these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from front_office.domain.accounts import (
    PASSWORD_BYTES,
    PASSWORD_MIN,
    USERNAME_HELP,
    AccountRuleError,
    User,
    check_password,
    check_username,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Problem(_Model):
    """Why a request was refused."""

    detail: str


class Health(_Model):
    status: Literal["ok"] = "ok"
    version: str = Field(description="The lab's version.")


class Registration(_Model):
    """A new user: a name and a password."""

    username: str = Field(min_length=3, max_length=32, description=USERNAME_HELP)
    password: str = Field(
        min_length=PASSWORD_MIN,
        max_length=PASSWORD_BYTES,
        description=f"At least {PASSWORD_MIN} characters, at most {PASSWORD_BYTES} bytes.",
    )

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"username": "analyst", "password": "a long passphrase"}]}
    )

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        try:
            return check_username(value)
        except AccountRuleError as error:
            raise ValueError(str(error)) from None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        try:
            return check_password(value)
        except AccountRuleError as error:
            raise ValueError(str(error)) from None


class SignIn(BaseModel):
    """OAuth2's password form, as the ``/docs`` page's *Authorize* button sends it: a name
    and a password, with fields that form may add and the lab does not use."""

    grant_type: Literal["password"] | None = None
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    scope: str = ""


class UserOut(_Model):
    """A user, without the password - which is never returned, not even as a hash."""

    user_id: int
    username: str
    created_at: datetime = Field(description="When the user registered (UTC).")

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(user_id=user.user_id, username=user.username, created_at=user.created_at)


class Token(_Model):
    """A signed sign-in token. Send it as ``Authorization: Bearer <token>``."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the token stops working.")


class AccountRemoved(_Model):
    """A deleted account, and how many of its questions went with it."""

    username: str
    questions_removed: int = Field(ge=0)
