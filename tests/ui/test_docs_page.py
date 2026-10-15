"""Ask the Docs (C5): the page signs in, asks and lists through the lab's own API.

The API is the real app, run in this process and reached through the API client's one seam
(``api_client.connect``); its model is scripted where the API reaches one
(``assistant.api.connect``). Nothing here opens a connection.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import front_office.assistant.api as assistant_api
from front_office.config import load_settings
from front_office.providers.ollama import OllamaProvider
from front_office.server.app import create_app
from tests.ollama_fakes import chat_chunks
from tests.rag_fakes import ollama, write_documents
from tests.unit.server.conftest import FAST, PASSWORD, SECRET
from wb import api_client
from wb.views import docs

ANSWER = "A token expires after 60 minutes [1]."


def _through(client: TestClient) -> api_client.Send:
    """The API client's way out, into an app in this process."""

    def send(method: str, url: str, **kwargs: object) -> tuple[int, object]:
        kwargs.pop("timeout", None)
        response = client.request(method, url, **kwargs)  # type: ignore[arg-type]
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None

    return send


@pytest.fixture
def api_home(tmp_path: Path) -> Path:
    """The API's own project: the configuration, a few documents, and its accounts."""
    root = tmp_path / "api"
    root.mkdir()
    shutil.copytree(Path(__file__).resolve().parents[2] / "configs", root / "configs")
    write_documents(root)
    return root


@pytest.fixture
def online(api_home: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The API answering, with a scripted model that embeds by words and answers ANSWER."""
    client = TestClient(create_app(load_settings(api_home), api=FAST, secret=SECRET))
    monkeypatch.setattr(
        api_client, "connect", lambda: api_client.LabApi("http://testserver", send=_through(client))
    )
    monkeypatch.setattr(
        assistant_api,
        "connect",
        lambda host, timeout: OllamaProvider(
            transport=ollama(chats=[chat_chunks(ANSWER) for _ in range(5)])
        ),
    )
    return client


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(button for button in app.button if button.label == label)


def _register(app: AppTest, name: str = "analyst", password: str = PASSWORD) -> AppTest:
    app.text_input(key="docs_register_name").input(name)
    app.text_input(key="docs_register_password").input(password)
    _button(app, "Register and sign in").click()
    return app.run()


def _texts(app: AppTest) -> str:
    return "\n".join(
        [*(item.value for item in app.markdown), *(item.value for item in app.caption)]
        + [*(item.value for item in app.info), *(item.value for item in app.warning)]
    )


Page = Callable[..., AppTest]


def test_the_api_not_running_is_said_plainly(page: Page, plain_home: Path) -> None:
    opened = page(plain_home, "docs")
    assert "not answering at http://127.0.0.1:8000" in opened.warning[0].value
    assert opened.code[0].value == "fol api"
    assert not opened.error


def test_signing_in_or_registering(page: Page, plain_home: Path, online: TestClient) -> None:
    opened = page(plain_home, "docs")
    assert [tab.label for tab in opened.tabs] == ["Sign in", "Register"]
    assert docs.TOKEN not in opened.session_state
    opened = _register(opened)
    assert opened.session_state[docs.TOKEN]
    assert "Signed in as **analyst**." in _texts(opened)
    # The index is not built yet: the page says so, and asking waits for it.
    assert "not indexed yet" in opened.info[0].value
    assert _button(opened, "Ask the documents").disabled


def test_a_wrong_password_is_refused_with_the_apis_words(
    page: Page, plain_home: Path, online: TestClient
) -> None:
    online.post("/auth/register", json={"username": "analyst", "password": PASSWORD})
    opened = page(plain_home, "docs")
    opened.text_input(key="docs_sign_in_name").input("analyst")
    opened.text_input(key="docs_sign_in_password").input("not the passphrase")
    _button(opened, "Sign in").click()
    opened.run()
    assert opened.error[0].value == "Wrong name or password."
    assert docs.TOKEN not in opened.session_state


def test_building_the_index_then_asking(page: Page, plain_home: Path, online: TestClient) -> None:
    opened = _register(page(plain_home, "docs"))
    _button(opened, "Build the index").click()
    opened.run()
    assert opened.info[0].value.startswith("Indexed 5 passages")
    assert "The index holds 5 passages" in _texts(opened)
    opened.text_area(key="docs_question").input("When does a token expire?")
    _button(opened, "Ask the documents").click()
    opened.run()
    assert not opened.error, [item.value for item in opened.error]
    assert ANSWER in _texts(opened)
    sources = [expander.label for expander in opened.expander if expander.label.startswith("[")]
    assert sources[0] == "[1] Architecture › The API (cited)"
    assert len(sources) == 5
    # Kept under the user: the API lists it.
    token = opened.session_state[docs.TOKEN]
    kept = online.get("/rag/questions", headers={"Authorization": f"Bearer {token}"}).json()
    assert [item["answer"] for item in kept["questions"]] == [ANSWER]


def test_an_index_older_than_the_documents_is_offered_again(
    page: Page, plain_home: Path, api_home: Path, online: TestClient
) -> None:
    opened = _register(page(plain_home, "docs"))
    token = opened.session_state[docs.TOKEN]
    online.post("/rag/index", headers={"Authorization": f"Bearer {token}"})
    changed = api_home / "docs" / "WORKBENCH.md"
    changed.write_text(changed.read_text(encoding="utf-8") + "\nA new line.\n", encoding="utf-8")
    opened.run()
    assert "have changed since the index was built" in opened.info[0].value
    _button(opened, "Build the index again").click()
    opened.run()
    assert opened.info[0].value.startswith("Indexed 5 passages")
    assert "The index holds 5 passages" in _texts(opened)


def test_earlier_questions_are_listed_and_can_be_deleted(
    page: Page, plain_home: Path, online: TestClient
) -> None:
    opened = _register(page(plain_home, "docs"))
    token = opened.session_state[docs.TOKEN]
    headers = {"Authorization": f"Bearer {token}"}
    assert online.post("/rag/index", headers=headers).status_code == 200
    asked = online.post("/rag/ask", json={"question": "When?"}, headers=headers).json()
    opened.run()
    key = asked["question_id"]
    assert any(expander.label == "When?" for expander in opened.expander)
    delete = opened.button(key=f"docs_forget_{key}")
    assert delete.disabled  # off until its box is ticked
    opened.checkbox(key=f"docs_forget_confirm_{key}").check()
    opened.run()
    opened.button(key=f"docs_forget_{key}").click()
    opened.run()
    assert online.get("/rag/questions", headers=headers).json() == {"questions": []}
    assert not any(expander.label == "When?" for expander in opened.expander)


def test_signing_out_and_a_sign_in_that_has_ended(
    page: Page, plain_home: Path, online: TestClient
) -> None:
    opened = _register(page(plain_home, "docs"))
    opened.button(key="docs_sign_out").click()
    opened.run()
    assert docs.TOKEN not in opened.session_state
    assert opened.info[0].value == "You are signed out."
    opened = page(plain_home, "docs", **{docs.TOKEN: "not.a.token", docs.USER: "analyst"})
    assert docs.TOKEN not in opened.session_state
    assert opened.info[0].value == "The token is not valid. Sign in again."


def test_deleting_the_account(page: Page, plain_home: Path, online: TestClient) -> None:
    opened = _register(page(plain_home, "docs"))
    assert opened.button(key="docs_remove_account").disabled
    opened.checkbox(key="docs_remove_account_confirm").check()
    opened.run()
    opened.button(key="docs_remove_account").click()
    opened.run()
    assert docs.TOKEN not in opened.session_state
    assert opened.info[0].value == "Your account and its questions were deleted."
    refused = online.post("/auth/token", data={"username": "analyst", "password": PASSWORD})
    assert refused.status_code == 401


def test_a_question_too_short(page: Page, plain_home: Path, online: TestClient) -> None:
    opened = _register(page(plain_home, "docs"))
    token = opened.session_state[docs.TOKEN]
    online.post("/rag/index", headers={"Authorization": f"Bearer {token}"})
    opened.run()
    opened.text_area(key="docs_question").input("  ")
    _button(opened, "Ask the documents").click()
    opened.run()
    assert opened.warning[0].value == "Write a question of a few words first."


def test_the_page_is_in_the_frames_ask_menu(app, plain_home: Path) -> None:
    opened = app(plain_home)
    assert "Ask the Docs" in [link.label for link in opened.get("page_link")]
