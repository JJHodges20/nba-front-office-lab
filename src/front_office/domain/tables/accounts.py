"""Data contracts for the API's accounts: its users, and the questions each one asked.

Decision 0019. Kept in their own file, ``data/api/accounts.sqlite``: never in the lab's
database, never touched by a build. The two tables are related: a question belongs to the
user who asked it, and deleting a user deletes their questions. ``storage.accounts`` maps
them with SQLAlchemy's ORM, a relationship each way.
"""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract

API_USERS = TableContract(
    name="api_users",
    domain="api_accounts",
    description="People who may sign in to the lab's API.",
    grain="One row per user.",
    fields=(
        Field(
            "user_id",
            DType.INTEGER,
            "User id, assigned when the user registers and never given to anyone else: a "
            "signed-in token names its user by this id.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
        ),
        Field(
            "username",
            DType.STRING,
            "The name the user signs in with, in lower case; no two users share one.",
            nullable=False,
            provenance=Provenance.ASSUMPTION,
        ),
        Field(
            "password_hash",
            DType.STRING,
            "The password as a bcrypt hash, salt included. The password itself is never kept.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "created_at",
            DType.DATETIME,
            "When the user registered.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
    ),
    primary_key=("user_id",),
    introduced_in="C2",
)

API_QUESTIONS = TableContract(
    name="api_questions",
    domain="api_accounts",
    description="Questions users asked the lab's documents through the API, with the answers.",
    grain="One row per question asked.",
    fields=(
        Field(
            "question_id",
            DType.INTEGER,
            "Question id, never reused.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
        ),
        Field(
            "user_id",
            DType.INTEGER,
            "The user who asked.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
            references="api_users.user_id",
        ),
        Field(
            "question",
            DType.STRING,
            "The question, as asked.",
            nullable=False,
            provenance=Provenance.ASSUMPTION,
        ),
        Field(
            "answer",
            DType.STRING,
            "The answer the language model wrote from the passages it was given.",
            nullable=False,
            provenance=Provenance.MODELED,
        ),
        Field(
            "sources",
            DType.STRING,
            "The passages the answer was given, as JSON: number, document, heading, link and "
            "distance from the question.",
            nullable=False,
            provenance=Provenance.DERIVED,
        ),
        Field(
            "model",
            DType.STRING,
            "The chat model that wrote the answer.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "asked_at",
            DType.DATETIME,
            "When the question was asked.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "seconds",
            DType.FLOAT,
            "How long the answer took.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
            unit="seconds",
            minimum=0,
        ),
    ),
    primary_key=("question_id",),
    indexes=(("user_id",),),
    introduced_in="C2",
)

TABLES: tuple[TableContract, ...] = (API_USERS, API_QUESTIONS)
