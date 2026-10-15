"""``/rag``: asking the documents through the API, and the index behind it (decision 0019).

Ollama is scripted where the API reaches it - ``assistant.api.connect``, the facade's one
place for a model - so nothing here needs a running model.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

import front_office.assistant.api as api
from front_office.config import Settings
from front_office.providers.ollama import OllamaProvider
from tests.ollama_fakes import ScriptedOllama, chat_chunks
from tests.rag_fakes import ollama, write_documents
from tests.unit.server.conftest import sign_in

QUESTION = {"question": "When does a token expire?"}
ANSWER = "A token expires after 60 minutes [1]."

Script = Callable[..., ScriptedOllama]


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    """Puts a scripted Ollama where the API reaches the model, with these chat replies."""

    def use(*replies: str, **kwargs: object) -> ScriptedOllama:
        transport = kwargs.pop("transport", None) or ollama(
            chats=[chat_chunks(reply) for reply in replies], **kwargs
        )
        monkeypatch.setattr(
            api, "connect", lambda host, timeout: OllamaProvider(transport=transport)
        )
        return transport  # type: ignore[return-value]

    return use


@pytest.fixture
def documented(settings: Settings) -> Settings:
    write_documents(settings.project_root)
    return settings


@pytest.fixture
def indexed(client: TestClient, documented: Settings, signed_in: dict, script: Script) -> dict:
    """A signed-in user, and the documents indexed through the API."""
    script()
    response = client.post("/rag/index", headers=signed_in)
    assert response.status_code == 200, response.text
    return signed_in


class TestTheIndex:
    def test_before_and_after_a_build(
        self, client: TestClient, documented: Settings, signed_in: dict, script: Script
    ) -> None:
        before = client.get("/rag/index", headers=signed_in).json()
        assert before["built"] is False and before["passages"] == 0
        assert before["embedding_model"] == "nomic-embed-text"
        assert before["documents_passages"] > 0
        script()
        built = client.post("/rag/index", headers=signed_in).json()
        assert built["rebuilt"] is True
        assert built["passages"] == before["documents_passages"]
        after = client.get("/rag/index", headers=signed_in).json()
        assert after["built"] is True and after["current"] is True
        assert after["built_with"] == "nomic-embed-text"

    def test_a_matching_index_is_left_alone_unless_forced(
        self, client: TestClient, indexed: dict, script: Script
    ) -> None:
        transport = script()
        assert client.post("/rag/index", headers=indexed).json()["rebuilt"] is False
        assert transport.embed_payloads == []
        assert client.post("/rag/index?force=true", headers=indexed).json()["rebuilt"] is True

    def test_ollama_not_running(
        self, client: TestClient, documented: Settings, signed_in: dict, script: Script
    ) -> None:
        script(transport=ScriptedOllama(down=True))
        response = client.post("/rag/index", headers=signed_in)
        assert response.status_code == 503
        assert "Ollama is not answering" in response.json()["detail"]


class TestAsking:
    def test_an_answer_with_its_sources_is_kept_in_the_users_history(
        self, client: TestClient, indexed: dict, script: Script
    ) -> None:
        script(ANSWER)
        response = client.post("/rag/ask", json=QUESTION, headers=indexed)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["answer"] == ANSWER
        assert body["question"] == QUESTION["question"]
        assert body["model"] == "qwen3:8b"
        assert body["notes"] == []
        first = body["sources"][0]
        assert first["number"] == 1 and first["cited"] is True
        assert first["location"] == "docs/ARCHITECTURE.md#the-api"
        assert "60 minutes" in first["text"]
        history = client.get("/rag/questions", headers=indexed).json()["questions"]
        assert [item["question_id"] for item in history] == [body["question_id"]]
        assert history[0] == body
        one = client.get(f"/rag/questions/{body['question_id']}", headers=indexed)
        assert one.json() == body

    def test_the_newest_first_and_as_many_as_asked(
        self, client: TestClient, indexed: dict, script: Script
    ) -> None:
        script(ANSWER, ANSWER)
        first = client.post("/rag/ask", json=QUESTION, headers=indexed).json()
        second = client.post("/rag/ask", json=QUESTION, headers=indexed).json()
        listed = client.get("/rag/questions", headers=indexed).json()["questions"]
        assert [item["question_id"] for item in listed] == [
            second["question_id"],
            first["question_id"],
        ]
        latest = client.get("/rag/questions?limit=1", headers=indexed).json()["questions"]
        assert [item["question_id"] for item in latest] == [second["question_id"]]
        assert client.get("/rag/questions?limit=0", headers=indexed).status_code == 422

    def test_a_note_travels_with_the_answer(
        self, client: TestClient, indexed: dict, script: Script
    ) -> None:
        script("Tokens expire after 60 minutes.")
        body = client.post("/rag/ask", json=QUESTION, headers=indexed).json()
        assert body["notes"] == ["The answer cites no passage: nothing shows where it comes from."]
        kept = client.get(f"/rag/questions/{body['question_id']}", headers=indexed).json()
        assert kept["notes"] == body["notes"]

    def test_each_user_sees_only_their_own_questions(
        self, client: TestClient, indexed: dict, script: Script
    ) -> None:
        script(ANSWER)
        mine = client.post("/rag/ask", json=QUESTION, headers=indexed).json()
        other = sign_in(client, "other")
        assert client.get("/rag/questions", headers=other).json() == {"questions": []}
        theirs = client.get(f"/rag/questions/{mine['question_id']}", headers=other)
        assert theirs.status_code == 404
        assert (
            client.delete(f"/rag/questions/{mine['question_id']}", headers=other).status_code == 404
        )
        assert (
            client.get(f"/rag/questions/{mine['question_id']}", headers=indexed).status_code == 200
        )

    def test_a_question_can_be_deleted(
        self, client: TestClient, indexed: dict, script: Script
    ) -> None:
        script(ANSWER)
        asked = client.post("/rag/ask", json=QUESTION, headers=indexed).json()
        gone = client.delete(f"/rag/questions/{asked['question_id']}", headers=indexed)
        assert gone.json() == {"question_id": asked["question_id"]}
        assert (
            client.get(f"/rag/questions/{asked['question_id']}", headers=indexed).status_code == 404
        )

    def test_deleting_the_account_deletes_its_questions(
        self, client: TestClient, indexed: dict, script: Script
    ) -> None:
        script(ANSWER, ANSWER)
        client.post("/rag/ask", json=QUESTION, headers=indexed)
        client.post("/rag/ask", json=QUESTION, headers=indexed)
        removed = client.delete("/auth/me", headers=indexed).json()
        assert removed["questions_removed"] == 2

    @pytest.mark.parametrize(
        "body",
        [
            {"question": "  a "},
            {"question": "x" * 501},
            {"question": "What?", "model": "something else"},
            {},
        ],
    )
    def test_pydantic_refuses_a_question_out_of_bounds(
        self, client: TestClient, indexed: dict, body: dict
    ) -> None:
        assert client.post("/rag/ask", json=body, headers=indexed).status_code == 422

    def test_not_indexed_yet(
        self, client: TestClient, documented: Settings, signed_in: dict, script: Script
    ) -> None:
        script(ANSWER)
        response = client.post("/rag/ask", json=QUESTION, headers=signed_in)
        assert response.status_code == 503
        assert "fol rag index" in response.json()["detail"]
        assert client.get("/rag/questions", headers=signed_in).json() == {"questions": []}

    def test_ollama_not_running(self, client: TestClient, indexed: dict, script: Script) -> None:
        script(transport=ScriptedOllama(down=True))
        response = client.post("/rag/ask", json=QUESTION, headers=indexed)
        assert response.status_code == 503
        assert "Ollama is not running" in response.json()["detail"]

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("post", "/rag/ask"),
            ("get", "/rag/questions"),
            ("get", "/rag/questions/1"),
            ("delete", "/rag/questions/1"),
            ("get", "/rag/index"),
            ("post", "/rag/index"),
        ],
    )
    def test_every_endpoint_needs_a_token(self, client: TestClient, method: str, path: str) -> None:
        response = getattr(client, method)(path, **({"json": QUESTION} if method == "post" else {}))
        assert response.status_code == 401
