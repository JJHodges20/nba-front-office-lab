"""What the API accepts and returns: a Pydantic model for every request and response.

FastAPI validates each request against its model before an endpoint runs - a wrong type, a
missing field or an unknown one is refused with 422 and the reason - and each response
against its model before it is sent. The ``/docs`` page is drawn from these models.
"""

from __future__ import annotations

from datetime import date, datetime
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
from front_office.domain.metrics import MetricSpec
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


# --- the lab's data (C4) -------------------------------------------------------------------

Figures = dict[str, float | None]
"""Metric key to value, as the services computed it; null where it is missing - never 0."""


class BuildOut(_Model):
    """The build the figures come from."""

    build_id: int | None
    built_at: datetime | None = Field(description="When the database was built (UTC).")


class LabOut(_Model):
    """What the lab holds."""

    built: bool
    current: bool = Field(description="Built by this version of the lab.")
    build: BuildOut
    team_seasons: list[str] = Field(description="Seasons with team statistics, newest first.")
    player_seasons: list[str] = Field(description="Seasons with player statistics, newest first.")
    cap_seasons: list[str] = Field(description="Seasons with cap rules, newest first.")
    contract_file_as_of: date | None = Field(
        description="The date your contract file was current; no salary is served by the API."
    )


class MetricOut(_Model):
    """What a figure is, and where it comes from."""

    key: str
    label: str
    name: str
    description: str
    category: str
    provenance: str = Field(
        description="measured (recorded by the source), derived (arithmetic on measured "
        "figures) or modeled (a model's estimate, not a measurement)."
    )
    estimated: bool = Field(
        False,
        description="An estimate from box scores over a span, not the league's published figure.",
    )
    format: str = Field(description="decimal, percent (a share 0-1), count, signed or money.")
    decimals: int
    higher_is_better: bool | None = Field(description="null where neither direction is better.")

    @classmethod
    def of(cls, spec: MetricSpec, *, estimated: bool = False) -> MetricOut:
        return cls(
            key=spec.key,
            label=spec.label,
            name=spec.name,
            description=spec.description,
            category=spec.category,
            provenance=spec.provenance.value,
            estimated=estimated,
            format=spec.format.value,
            decimals=spec.decimals,
            higher_is_better=spec.higher_is_better,
        )


class TeamRow(_Model):
    team_id: int
    team_name: str
    abbreviation: str
    conference: str | None
    division: str | None
    conference_rank: int | None
    postseason_result: str | None = Field(description="How the season ended, where it has.")
    figures: Figures
    ranks: dict[str, int | None] = Field(
        description="Each figure's place among the season's teams: 1 is best, or the highest "
        "where neither is better."
    )


class TeamsOut(_Model):
    """Every team of one regular season, compared within that season."""

    season: str
    build: BuildOut
    metrics: list[MetricOut]
    league_average: Figures = Field(description="The league's average of each figure that season.")
    teams: list[TeamRow]


class TeamSeasonRow(_Model):
    season: str
    team_name: str
    conference_rank: int | None
    postseason_result: str | None
    league_teams: int | None = Field(description="Teams in the league that season.")
    figures: Figures
    rating_ranks: dict[str, int | None] = Field(
        description="The net, offensive and defensive rating's place in the league that season."
    )


class TeamOut(_Model):
    """A franchise as it is now, and every season on record, newest first."""

    team_id: int
    full_name: str
    abbreviation: str
    city: str | None
    conference: str | None
    division: str | None
    build: BuildOut
    metrics: list[MetricOut]
    seasons: list[TeamSeasonRow]


class QualificationOut(_Model):
    min_games: int
    min_minutes: float
    described: str


class PlayerRow(_Model):
    player_id: int
    player_name: str
    team: str | None = Field(description="The team's abbreviation; TOT for several teams.")
    team_id: int | None
    teams_played_for: int | None
    position: str | None
    age: int | None
    qualified: bool = Field(description="Played enough to be compared (see qualification).")
    figures: Figures


class PlayersOut(_Model):
    """Players of one regular season. No salary or contract figure is served."""

    season: str
    build: BuildOut
    qualification: QualificationOut
    metrics: list[MetricOut]
    matched: int = Field(ge=0, description="Players the filters matched, before the limit.")
    players: list[PlayerRow]


class PlayerSeasonRow(_Model):
    season: str
    season_type: str
    team: str | None
    age: int | None
    figures: Figures


class ValueRow(_Model):
    season: str
    team: str | None
    age: int | None
    projection_only: bool = Field(
        description="A season still to be played: the projection, with no impact of its own."
    )
    figures: Figures


class ValueModelOut(_Model):
    """The player value model the modeled figures come from, and how it was tested."""

    revision: int
    tested_seasons: str
    team_seasons: int
    rmse_minutes_played: float = Field(
        description="Error predicting a team's net rating from its players, points per 100 "
        "possessions, with each season's minutes as played."
    )
    rmse_minutes_projected: float | None = Field(
        description="The same with the minutes projected: what a forecast carries."
    )
    note: str


class PlayerOut(_Model):
    """A player: who they are, every season, and the value model's estimates. No salary or
    contract figure is served."""

    player_id: int
    full_name: str
    position: str | None
    position_group: str | None
    height_inches: int | None
    weight_lbs: int | None
    birth_date: date | None
    country: str | None
    college: str | None
    is_active: bool | None
    current_team: str | None
    build: BuildOut
    metrics: list[MetricOut]
    seasons: list[PlayerSeasonRow]
    value: list[ValueRow]
    value_model: ValueModelOut | None
