"""``configs/api.yaml``: the lab's HTTP API (decision 0019).

How long a sign-in lasts, how costly a password is to check, and how the documents are
searched for an answer. The key that signs the tokens is not a setting: it is the user's own
(``FOL_API_SECRET``), or one the API makes in the data folder, and an unknown field - a key,
say - is refused here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from front_office.domain.assistant import is_cloud_model


class _Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SignInSettings(_Settings):
    token_minutes: int = Field(60, ge=1, le=24 * 60)
    """How long a token signs its user in, from the moment it is issued."""
    password_rounds: int = Field(12, ge=4, le=16)
    """bcrypt's cost: each step doubles the work of checking one password, for the API and
    for anyone trying to guess it from a stolen hash. A password is hashed at the cost set
    when it was registered."""


class RagSettings(_Settings):
    """Retrieval over the documents: the answer itself is written by the assistant's model,
    within its quick mode's limits (``configs/assistant.yaml``)."""

    embedding_model: str = Field("nomic-embed-text", min_length=1)
    """The local Ollama model that embeds the passages and the questions."""
    document_prefix: str = "search_document: "
    query_prefix: str = "search_query: "
    """nomic-embed-text tells a passage from a question by these; another model may want
    none."""
    passages: int = Field(5, ge=1, le=12)
    """How many of the nearest passages one answer is given."""
    batch: int = Field(32, ge=1, le=256)
    """Passages embedded per request while the index is built."""

    @field_validator("embedding_model")
    @classmethod
    def _local_model(cls, value: str) -> str:
        if is_cloud_model(value):
            raise ValueError(f"{value!r} is a cloud model; the lab uses local models only")
        return value


class ApiSettings(_Settings):
    version: int = Field(ge=1)
    sign_in: SignInSettings = SignInSettings()
    rag: RagSettings = RagSettings()
