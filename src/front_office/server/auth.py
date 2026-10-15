"""``/auth``: registering, signing in, and the signed-in user's own account.

Every endpoint outside this router's ``/register`` and ``/token`` and the health check asks
for :func:`current_user`: a valid, unexpired token whose user still exists.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from front_office.domain.accounts import User
from front_office.server.schemas import (
    AccountRemoved,
    Problem,
    Registration,
    SignIn,
    Token,
    UserOut,
)
from front_office.server.security import TokenRefused
from front_office.server.state import ServerState, server_state
from front_office.services.accounts import AccountNotFound, NameTaken

TOKEN_PATH = "/auth/token"
bearer = OAuth2PasswordBearer(tokenUrl=TOKEN_PATH)
router = APIRouter(prefix="/auth", tags=["Sign-in"])

State = Annotated[ServerState, Depends(server_state)]
_SIGN_IN_AGAIN = {"WWW-Authenticate": "Bearer"}
REFUSED = {status.HTTP_401_UNAUTHORIZED: {"model": Problem, "description": "Not signed in"}}


def current_user(state: State, token: Annotated[str, Depends(bearer)]) -> User:
    """The user the request's token signs in. Missing, altered, expired, or naming a user
    who has since been deleted: 401, and the caller signs in again."""
    try:
        return state.accounts.user(state.tokens.user_id(token))
    except TokenRefused as refused:
        detail = (
            "The sign-in has expired. Sign in again."
            if refused.expired
            else "The token is not valid. Sign in again."
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail, _SIGN_IN_AGAIN) from None
    except AccountNotFound:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "The token's user no longer exists. Register again.",
            _SIGN_IN_AGAIN,
        ) from None


SignedIn = Annotated[User, Depends(current_user)]


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": Problem, "description": "Name taken"}},
)
def register(registration: Registration, state: State) -> UserOut:
    """Register a user. Names are compared in lower case, so "Analyst" and "analyst" are
    one name."""
    try:
        user = state.accounts.register(registration.username, registration.password)
    except NameTaken:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"The name {registration.username} is taken."
        ) from None
    return UserOut.of(user)


@router.post("/token", responses=REFUSED)
def sign_in(form: Annotated[SignIn, Form()], state: State) -> Token:
    """Sign in with a name and a password, sent as a form, and receive a token."""
    user = state.accounts.authenticate(form.username, form.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong name or password.", _SIGN_IN_AGAIN)
    issued = state.tokens.issue(user.user_id)
    return Token(access_token=issued.token, expires_in=issued.seconds)


@router.get("/me", responses=REFUSED)
def me(user: SignedIn) -> UserOut:
    """The signed-in user."""
    return UserOut.of(user)


@router.delete("/me", responses=REFUSED)
def remove_me(user: SignedIn, state: State) -> AccountRemoved:
    """Delete the signed-in user's account and every question they asked. It cannot be
    undone, and the token stops working."""
    try:
        removed = state.accounts.remove(user.user_id)
    except AccountNotFound:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "The account no longer exists.", _SIGN_IN_AGAIN
        ) from None
    return AccountRemoved(username=user.username, questions_removed=removed)
