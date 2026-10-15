"""``/rag``: asking the lab's documents (decision 0019), and the index the answers come from.

An answer is the assistant's (``assistant.api.ask_documents``), kept under the user who
asked it; a user reads and deletes their own questions only - another user's is not found.
Every endpoint here needs a token.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

import front_office.assistant.api as api
from front_office.config.assistant import load_assistant_settings
from front_office.pipelines.rag import IndexingFailed, index_documents
from front_office.server.auth import REFUSED, SignedIn, State
from front_office.server.schemas import (
    AnswerOut,
    Forgotten,
    IndexBuilt,
    IndexOut,
    Problem,
    Question,
    QuestionList,
)
from front_office.services.accounts import AccountNotFound
from front_office.services.passages import PassageService

router = APIRouter(prefix="/rag", tags=["Ask the documents"])

UNAVAILABLE = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problem,
        "description": "Ollama, a model or the index is not ready; the detail says what to do",
    }
}
NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such question"}}
QuestionId = Annotated[int, Path(ge=1, description="The question's id, from its answer.")]


@router.post("/ask", status_code=status.HTTP_201_CREATED, responses={**REFUSED, **UNAVAILABLE})
def ask(question: Question, user: SignedIn, state: State) -> AnswerOut:
    """Ask the lab's documents. The answer is written by the local model from the passages
    nearest the question, cites them by number, and is kept in your history."""
    try:
        answer = api.ask_documents(question.question, settings=state.settings)
    except api.DocumentsUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None
    kept = state.accounts.record_question(
        user.user_id,
        question=answer.question,
        answer=answer.answer,
        sources=answer.sources,
        model=answer.model,
        seconds=answer.seconds,
        notes=answer.notes,
    )
    return AnswerOut.of(kept)


@router.get("/questions", responses=REFUSED)
def questions(
    user: SignedIn,
    state: State,
    limit: Annotated[int, Query(ge=1, le=100, description="How many, the newest first.")] = 20,
) -> QuestionList:
    """Your questions and their answers, the newest first."""
    asked = state.accounts.questions(user.user_id, limit=limit)
    return QuestionList(questions=[AnswerOut.of(item) for item in asked])


@router.get("/questions/{question_id}", responses={**REFUSED, **NOT_FOUND})
def question(question_id: QuestionId, user: SignedIn, state: State) -> AnswerOut:
    """One of your questions, as it was answered."""
    try:
        return AnswerOut.of(state.accounts.question(user.user_id, question_id))
    except AccountNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "You have no question with that id."
        ) from None


@router.delete("/questions/{question_id}", responses={**REFUSED, **NOT_FOUND})
def forget(question_id: QuestionId, user: SignedIn, state: State) -> Forgotten:
    """Delete one of your questions from your history."""
    try:
        state.accounts.forget_question(user.user_id, question_id)
    except AccountNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "You have no question with that id."
        ) from None
    return Forgotten(question_id=question_id)


@router.get("/index", responses=REFUSED)
def index(user: SignedIn, state: State) -> IndexOut:
    """Whether the documents are indexed, and whether the index matches them as they are."""
    return IndexOut.of(PassageService(state.settings).status())


@router.post("/index", responses={**REFUSED, **UNAVAILABLE})
def build_index(
    user: SignedIn,
    state: State,
    force: Annotated[
        bool, Query(description="Build it again even when it matches the documents.")
    ] = False,
) -> IndexBuilt:
    """Build the index of the documents with the local embedding model. Nothing is done when
    it already matches them, unless forced. Takes about a minute."""
    ollama = load_assistant_settings(state.settings.config_dir).ollama
    try:
        report = index_documents(
            state.settings,
            provider=api.connect(ollama.host, ollama.timeout_seconds),
            force=force,
        )
    except IndexingFailed as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None
    return IndexBuilt.of(report)
