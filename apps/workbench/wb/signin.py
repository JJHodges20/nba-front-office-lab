"""Signing in to the workbench (decision 0020): no page, no figure and no sidebar until
someone has signed in.

The workbench signs in against the project's accounts - the API's own file and rules, so one
name and password serve both - through the account service, on this machine, whether or not
the API is running. A sign-in lasts as long as one of the API's tokens (``configs/api.yaml``,
``sign_in.token_minutes``); every run checks that it has not run out and that the account is
still there. When the API answers at sign-in, the same name and password sign in to it as
well, so Ask the Docs opens signed in. Signing out forgets the whole session: whoever signs
in next starts with nothing of the last person's choices.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from front_office.domain.accounts import USERNAME_HELP, AccountRuleError, sign_in_ends
from front_office.services.accounts import (
    AccountNotFound,
    NameTaken,
    ProjectAccounts,
    project_accounts,
)
from wb import answers, api_client, components

USER_ID = "signin_user_id"
USER = "signin_user"
SINCE = "signin_since"
"""When the sign-in was made, UTC."""
NOTICE = "signin_notice"
"""A message for the sign-in page: signed out, the sign-in run out, the account gone."""
TABS = "signin_tabs"
SIGNED_OUT = "You are signed out."


def accounts() -> ProjectAccounts:
    """The project's accounts. The one seam the whole-workbench tests replace."""
    return project_accounts()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def current() -> str | None:
    """The name signed in to this session, or ``None``. A sign-in that has run out, or whose
    account has been deleted (from Ask the Docs, or through the API), signs the session out
    with a word on the sign-in page."""
    user_id = st.session_state.get(USER_ID)
    if user_id is None:
        return None
    project = accounts()
    since = st.session_state.get(SINCE)
    if not isinstance(since, datetime) or _now() >= sign_in_ends(since, project.sign_in_minutes):
        sign_out(f"Your sign-in ran out after {project.sign_in_minutes} minutes. Sign in again.")
        return None
    try:
        user = project.accounts.user(user_id)
    except AccountNotFound:
        sign_out("That account no longer exists. Sign in with another, or register.")
        return None
    return user.username


def sign_out(message: str = SIGNED_OUT) -> None:
    """Forget everything this session held, and say why on the sign-in page."""
    st.session_state.clear()
    st.session_state[NOTICE] = message


# --- the sign-in page ------------------------------------------------------------------------


def page() -> None:
    """The only page there is until someone signs in."""
    components.header(
        "NBA Front Office Lab",
        "Sign in to use the lab, or register first. The same name and password sign you in "
        "to the lab's API.",
    )
    notice = st.session_state.pop(NOTICE, None)
    if notice:
        components.alert("info", notice)  # the lab's own words, never outside text
    sign_in_tab, register_tab = st.tabs(["Sign in", "Register"], key=TABS)
    with sign_in_tab, st.form("signin_form"):
        name = st.text_input("Name", key="signin_name", autocomplete="username")
        password = st.text_input(
            "Password",
            type="password",
            key="signin_password",
            autocomplete="current-password",
        )
        if st.form_submit_button("Sign in", type="primary", icon=":material/login:"):
            _sign_in(name, password)
    with register_tab, st.form("signin_register"):
        name = st.text_input(
            "Name",
            key="signin_register_name",
            autocomplete="username",
            help=f"{USERNAME_HELP}.",
        )
        password = st.text_input(
            "Password",
            type="password",
            key="signin_register_password",
            autocomplete="new-password",
            help="At least 8 characters. Kept only as a hash: nobody can read it back.",
        )
        if st.form_submit_button(
            "Register and sign in", type="primary", icon=":material/person_add:"
        ):
            _register(name, password)


def _sign_in(name: str, password: str) -> None:
    if not name.strip() or not password:
        components.alert("error", "Give your name and your password.")
        return
    user = accounts().accounts.authenticate(name, password)
    if user is None:
        components.alert("error", "That name and password do not sign anyone in.")
        return
    _signed_in(user.user_id, user.username, password)


def _register(name: str, password: str) -> None:
    try:
        user = accounts().accounts.register(name, password)
    except AccountRuleError as error:
        components.alert("error", answers.escaped(f"{str(error)[0].upper()}{str(error)[1:]}."))
        return
    except NameTaken:
        components.alert("error", "That name is taken: choose another, or sign in.")
        return
    _signed_in(user.user_id, user.username, password)


def _signed_in(user_id: int, username: str, password: str) -> None:
    st.session_state[USER_ID] = user_id
    st.session_state[USER] = username
    st.session_state[SINCE] = _now()
    _sign_in_to_the_api(username, password)
    st.rerun()


def _sign_in_to_the_api(username: str, password: str) -> None:
    """The same name and password at the lab's API, when it answers, so Ask the Docs opens
    signed in. When it does not, Ask the Docs asks for them on its own page."""
    from wb.views import docs  # the page's own keys; it imports this module

    try:
        signed = api_client.connect().sign_in(username, password)
    except (ValueError, api_client.ApiError):
        return
    st.session_state[docs.TOKEN] = signed["access_token"]
    st.session_state[docs.USER] = username


# --- in the frame ----------------------------------------------------------------------------


def sidebar(username: str) -> None:
    """Who is signed in, and the way out, at the foot of the sidebar on every page."""
    with st.sidebar:
        st.divider()
        st.caption(f"Signed in as **{answers.escaped(username)}**")
        st.button(
            "Sign out",
            key="signin_sign_out",
            icon=":material/logout:",
            on_click=sign_out,
            args=(SIGNED_OUT,),
        )
