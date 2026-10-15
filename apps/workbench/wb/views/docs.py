"""Ask the Docs: the lab's documentation, asked through the lab's own API (decision 0019).

The one page that reaches the lab over HTTP rather than through the services: it signs in to
the API, asks the documents, and lists the questions this account has asked - through
``wb/api_client.py`` alone, at the address ``FOL_API_URL`` names. The API retrieves the
passages nearest a question and the local model answers from them; this page only draws what
comes back. The token is kept in the session, never shown.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from wb import answers, api_client, components, formats

TOKEN = "docs_token"
USER = "docs_user"
LAST = "docs_last_answer"
NOTICE = "docs_notice"
"""A message for the top of the next run: the account deleted, the sign-in run out."""
TABS = "docs_tabs"
"""Sign in or Register: kept while a form refuses and the page runs again around it."""
HISTORY = 20
"""Questions listed under "Your questions", the newest first."""
QUESTION_MAX = 500


def render() -> None:
    components.header(
        "Ask the Docs",
        "Ask the lab's own documentation through its API. The local model answers from the "
        "passages nearest your question and names each one, so you can read the source.",
    )
    try:
        client = api_client.connect()
    except ValueError as error:
        components.alert("warning", answers.escaped(str(error)))
        return
    try:
        client.health()
    except api_client.ApiError:
        offline(client.base_url)
        return
    notice = st.session_state.pop(NOTICE, None)
    if notice:
        components.alert("info", answers.escaped(notice))
    token = st.session_state.get(TOKEN)
    if token is None:
        signing_in(client)
    else:
        signed_in(client, token)


def offline(address: str) -> None:
    components.alert(
        "warning",
        f"The lab's API is not answering at {answers.escaped(address)}. Start it in a "
        "terminal, then reload this page. Everything else in the workbench works without it.",
    )
    st.code("fol api", language="powershell")
    st.caption("With Docker, `docker compose up` starts the API beside the workbench.")


# --- signing in ------------------------------------------------------------------------------


def signing_in(client: api_client.LabApi) -> None:
    st.markdown(
        "Sign in to ask, or register first. Your questions and their answers are kept under "
        "your name, for you alone."
    )
    sign_in_tab, register_tab = st.tabs(["Sign in", "Register"], key=TABS)
    with sign_in_tab, st.form("docs_sign_in"):
        name = st.text_input("Name", key="docs_sign_in_name", autocomplete="username")
        password = st.text_input(
            "Password",
            type="password",
            key="docs_sign_in_password",
            autocomplete="current-password",
        )
        if st.form_submit_button("Sign in", type="primary", icon=":material/login:"):
            _sign_in(client, name, password)
    with register_tab, st.form("docs_register"):
        name = st.text_input(
            "Name",
            key="docs_register_name",
            autocomplete="username",
            help="3 to 32 letters, digits, dots, hyphens or underscores.",
        )
        password = st.text_input(
            "Password",
            type="password",
            key="docs_register_password",
            autocomplete="new-password",
            help="At least 8 characters. Kept only as a hash: nobody can read it back.",
        )
        if st.form_submit_button(
            "Register and sign in", type="primary", icon=":material/person_add:"
        ):
            try:
                client.register(name, password)
            except api_client.ApiError as error:
                components.alert("error", answers.escaped(error.detail))
            else:
                _sign_in(client, name, password)


def _sign_in(client: api_client.LabApi, name: str, password: str) -> None:
    try:
        signed = client.sign_in(name, password)
    except api_client.ApiError as error:
        components.alert("error", answers.escaped(error.detail))
        return
    st.session_state[TOKEN] = signed["access_token"]
    st.session_state[USER] = name.strip().lower()
    st.rerun()


def _signed_out(message: str) -> None:
    # The tab row is not drawn while signed in, so it may be reset here: the page comes back
    # on Sign in, not on whichever tab was used last.
    for key in (TOKEN, USER, LAST, TABS):
        st.session_state.pop(key, None)
    st.session_state[NOTICE] = message


# --- signed in -------------------------------------------------------------------------------


def signed_in(client: api_client.LabApi, token: str) -> None:
    try:
        index = client.index(token)
        asked = client.questions(token, limit=HISTORY)["questions"]
    except api_client.SignedOut as error:
        _signed_out(error.detail)
        st.rerun()
    except api_client.ApiError as error:
        components.alert("warning", answers.escaped(error.detail))
        return

    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"Signed in as **{answers.escaped(st.session_state.get(USER, ''))}**.")
        if st.button("Sign out", key="docs_sign_out", icon=":material/logout:"):
            _signed_out("You are signed out.")
            st.rerun()

    index_state(client, token, index)
    ask(client, token, built=bool(index["built"]))
    last = st.session_state.get(LAST)
    if last is not None:
        answer(last, heading="Answer")
    history(
        client,
        token,
        [item for item in asked if last is None or item["question_id"] != last["question_id"]],
    )
    account(client, token)


def index_state(client: api_client.LabApi, token: str, index: dict[str, Any]) -> None:
    """Whether the documents are indexed, and a button to index them when they are not, or
    when they have changed since."""
    if index["built"] and index["current"]:
        st.caption(
            f"The index holds {index['passages']:,} passages of the lab's documents, built "
            f"{formats.moment(index['built_at'])} with {index['built_with']}."
        )
        return
    if not index["built"]:
        components.alert(
            "info",
            "The documents are not indexed yet. Build the index once: the local model reads "
            "every passage, which takes about a minute.",
        )
        label = "Build the index"
    else:
        components.alert(
            "info",
            "The documents have changed since the index was built "
            f"({formats.moment(index['built_at'])}). Build it again to search what they say now.",
        )
        label = "Build the index again"
    if st.button(label, key="docs_build_index", icon=":material/database:"):
        with st.spinner("Reading every passage with the local model..."):
            try:
                built = client.build_index(token)
            except api_client.ApiError as error:
                components.alert("error", answers.escaped(error.detail))
                return
        st.session_state[NOTICE] = (
            f"Indexed {built['passages']:,} passages in {built['seconds']:.0f} seconds."
        )
        st.rerun()


def ask(client: api_client.LabApi, token: str, *, built: bool) -> None:
    with st.form("docs_ask"):
        question = st.text_area(
            "Your question",
            key="docs_question",
            max_chars=QUESTION_MAX,
            placeholder="How is a player's projected impact tested?",
            help="About how the lab works: how something is computed, tested or decided.",
        )
        sent = st.form_submit_button(
            # Not "Ask": the top bar's menu of the same name would share it, to a keyboard too.
            "Ask the documents",
            type="primary",
            icon=":material/send:",
            disabled=not built,
        )
    if not sent:
        return
    if len(question.strip()) < 3:
        components.alert("warning", "Write a question of a few words first.")
        return
    with st.spinner("Finding the nearest passages and writing an answer: up to a minute..."):
        try:
            st.session_state[LAST] = client.ask(token, question.strip())
        except api_client.SignedOut as error:
            _signed_out(error.detail)
            st.rerun()
        except api_client.ApiError as error:
            components.alert("error", answers.escaped(error.detail))


def answer(item: dict[str, Any], *, heading: str | None = None) -> None:
    """An answer as the API kept it: the text, its notes, and every passage it was given."""
    if heading:
        st.subheader(heading)
    st.markdown(answers.prose(item["answer"]))
    for note in item["notes"]:
        components.tagged(components.NOTE, answers.escaped(note))
    st.caption(
        f"Written by {answers.escaped(item['model'])} in {item['seconds']:.0f} seconds from "
        f"{len(item['sources'])} passages of the lab's documents. Check a claim against its "
        "source below."
    )
    for source in item["sources"]:
        cited = " (cited)" if source["cited"] else ""
        label = f"[{source['number']}] {answers.escaped(source['heading'])}{cited}"
        key = f"docs_source_{item['question_id']}_{source['number']}"
        with st.expander(label, key=key):
            st.caption(
                f"{answers.escaped(source['path'])} · how far from the question: "
                f"{source['distance']:.2f} (0 is nearest)"
            )
            st.markdown(answers.prose(source["text"]))


def history(client: api_client.LabApi, token: str, asked: list[dict[str, Any]]) -> None:
    st.subheader("Your questions")
    if not asked:
        st.caption("Earlier questions are kept here, the newest first.")
        return
    for item in asked:
        key = item["question_id"]
        with st.expander(answers.escaped(item["question"]), key=f"docs_history_{key}"):
            st.caption(f"Asked {formats.moment(item['asked_at'])}")
            answer(item)
            if components.confirmed_button(
                "Delete this question",
                "Yes, delete this question and its answer",
                key=f"docs_forget_{key}",
                confirm_key=f"docs_forget_confirm_{key}",
            ):
                try:
                    client.forget(token, key)
                except api_client.ApiError as error:
                    components.alert("error", answers.escaped(error.detail))
                else:
                    st.rerun()


def account(client: api_client.LabApi, token: str) -> None:
    with st.expander("Your account", key="docs_account"):
        st.caption("Deleting your account deletes every question you asked. It cannot be undone.")
        if components.confirmed_button(
            "Delete my account",
            "Yes, delete my account and my questions",
            key="docs_remove_account",
            confirm_key="docs_remove_account_confirm",
        ):
            try:
                client.remove_account(token)
            except api_client.ApiError as error:
                components.alert("error", answers.escaped(error.detail))
            else:
                _signed_out("Your account and its questions were deleted.")
                st.rerun()
