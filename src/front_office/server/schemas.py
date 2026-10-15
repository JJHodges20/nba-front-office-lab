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
    AskedQuestion,
    User,
    check_password,
    check_username,
)
from front_office.domain.rag import CitedSource, IndexReport, IndexStatus


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


# --- asking the documents (C3) -------------------------------------------------------------

QUESTION_MIN = 3
QUESTION_MAX = 500


class Question(_Model):
    """A question about the lab: how something is computed, tested or decided, or how to do
    something in it."""

    question: str = Field(
        min_length=QUESTION_MIN,
        max_length=QUESTION_MAX,
        examples=["How is a player's projected impact tested?"],
    )

    @field_validator("question")
    @classmethod
    def _words(cls, value: str) -> str:
        text = " ".join(value.split())
        if len(text) < QUESTION_MIN:
            raise ValueError(f"a question needs at least {QUESTION_MIN} characters")
        return text


class SourceOut(_Model):
    """A passage the answer was given, numbered as the answer cites it."""

    number: int = Field(ge=1)
    path: str = Field(description="The document, from the project root.")
    heading: str = Field(description="The document's title and the passage's heading.")
    location: str = Field(description="The document and the heading, as a link in the project.")
    distance: float = Field(description="How far the passage is from the question: 0 is nearest.")
    cited: bool = Field(description="Whether the answer cites it.")
    text: str = Field(description="The passage, as the model read it.")

    @classmethod
    def of(cls, source: CitedSource) -> SourceOut:
        return cls(
            number=source.number,
            path=source.path,
            heading=source.heading,
            location=source.location,
            distance=source.distance,
            cited=source.cited,
            text=source.text,
        )


class AnswerOut(_Model):
    """A question, the answer written from the documents, and the passages it was given -
    kept as it was answered, whatever the documents say since."""

    question_id: int
    question: str
    answer: str = Field(description="Cites its passages by number, like [2].")
    sources: list[SourceOut]
    notes: list[str] = Field(
        description="What to know about the answer: a sentence cut, no citation."
    )
    model: str = Field(description="The local model that wrote the answer.")
    seconds: float = Field(ge=0, description="How long the answer took.")
    asked_at: datetime = Field(description="When it was asked (UTC).")

    @classmethod
    def of(cls, asked: AskedQuestion) -> AnswerOut:
        return cls(
            question_id=asked.question_id,
            question=asked.question,
            answer=asked.answer,
            sources=[SourceOut.of(source) for source in asked.sources],
            notes=list(asked.notes),
            model=asked.model,
            seconds=asked.seconds,
            asked_at=asked.asked_at,
        )


class QuestionList(_Model):
    """The signed-in user's questions, the newest first."""

    questions: list[AnswerOut]


class Forgotten(_Model):
    """A question deleted from the user's history."""

    question_id: int


class IndexOut(_Model):
    """The vector index of the documents, beside what they are now."""

    built: bool
    current: bool = Field(
        description="Built from the documents as they are now, with the model the settings name."
    )
    passages: int = Field(ge=0, description="Passages in the index; 0 before it is built.")
    built_with: str | None = Field(description="The embedding model it was built with.")
    built_at: datetime | None = Field(description="When it was built (UTC).")
    embedding_model: str = Field(description="The embedding model the settings name.")
    documents_passages: int = Field(ge=0, description="Passages a build now would hold.")

    @classmethod
    def of(cls, status: IndexStatus) -> IndexOut:
        built = status.built
        return cls(
            built=built is not None,
            current=status.is_current,
            passages=built.passages if built else 0,
            built_with=built.model if built else None,
            built_at=built.built_at if built else None,
            embedding_model=status.model,
            documents_passages=status.passages,
        )


class IndexBuilt(_Model):
    """What building the index did."""

    rebuilt: bool = Field(description="False when the index already matched the documents.")
    passages: int = Field(ge=0)
    model: str
    built_at: datetime
    seconds: float = Field(ge=0)

    @classmethod
    def of(cls, report: IndexReport) -> IndexBuilt:
        return cls(
            rebuilt=report.rebuilt,
            passages=report.passages,
            model=report.model,
            built_at=report.built_at,
            seconds=round(report.seconds, 2),
        )
