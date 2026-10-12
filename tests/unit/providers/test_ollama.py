from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from front_office.providers.ollama import (
    ModelNotAvailable,
    NotLocal,
    OllamaError,
    OllamaProvider,
    OllamaResponseError,
    OllamaUnavailable,
    requests_transport,
)
from tests.ollama_fakes import ScriptedOllama, chat_chunks, tool_call

MESSAGES = [{"role": "user", "content": "How did the Celtics do?"}]


class Clock:
    """Advances a fixed step every time it is read."""

    def __init__(self, step: float = 0.5) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def provider(transport: ScriptedOllama, **kwargs: Any) -> OllamaProvider:
    return OllamaProvider(transport=transport, clock=Clock(), **kwargs)


class TestOnThisMachineOnly:
    @pytest.mark.parametrize(
        "host",
        [
            "http://127.0.0.1:11434",
            "http://localhost:11434",
            "http://[::1]:11434",
            "http://127.0.0.2:8080",
        ],
    )
    def test_a_loopback_address_is_accepted(self, host: str) -> None:
        assert OllamaProvider(host).host == host

    @pytest.mark.parametrize(
        "host",
        [
            "http://192.168.1.20:11434",
            "https://ollama.com",
            "http://0.0.0.0:11434",
            "ftp://127.0.0.1",
        ],
    )
    def test_any_other_address_is_refused(self, host: str) -> None:
        with pytest.raises(NotLocal):
            OllamaProvider(host)

    @pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "gemma4:cloud", "deepseek-v3-cloud"])
    def test_a_cloud_model_is_refused_by_name_before_asking(self, model: str) -> None:
        ollama = ScriptedOllama(models=[model])
        with pytest.raises(NotLocal):
            provider(ollama).require_local(model)
        assert ollama.requests == []

    def test_a_model_ollama_marks_remote_is_refused(self) -> None:
        listed = {
            "name": "big:latest",
            "size": 1,
            "remote_model": "big",
            "remote_host": "https://ollama.com:443",
        }
        with pytest.raises(NotLocal):
            provider(ScriptedOllama(models=[listed])).require_local("big")

    def test_a_missing_model_says_how_to_get_it(self) -> None:
        with pytest.raises(ModelNotAvailable, match="ollama pull qwen3:4b"):
            provider(ScriptedOllama(models=["qwen3:8b"])).require_local("qwen3:4b")

    def test_a_name_without_a_tag_means_latest(self) -> None:
        assert (
            provider(ScriptedOllama(models=["llama3.2:latest"])).require_local("llama3.2").name
            == "llama3.2:latest"
        )

    def test_chat_checks_the_model_before_sending(self) -> None:
        ollama = ScriptedOllama(models=["qwen3:8b"])
        with pytest.raises(ModelNotAvailable):
            provider(ollama).chat("qwen3:4b", MESSAGES, context_tokens=8192)
        assert ollama.chat_payloads == []


class TestChat:
    def test_the_request_carries_the_context_length_and_tools(self) -> None:
        ollama = ScriptedOllama(chats=[chat_chunks("Hello")])
        tools = [{"type": "function", "function": {"name": "data_status", "parameters": {}}}]
        provider(ollama).chat(
            "qwen3:8b", MESSAGES, context_tokens=8192, tools=tools, max_output_tokens=512, seed=0
        )
        sent = ollama.chat_payloads[0]
        assert sent["options"] == {
            "num_ctx": 8192,
            "temperature": 0.0,
            "num_predict": 512,
            "seed": 0,
        }
        assert sent["tools"] == tools
        assert sent["stream"] is True
        assert "think" not in sent and "keep_alive" not in sent

    def test_thinking_is_sent_only_when_asked(self) -> None:
        ollama = ScriptedOllama(chats=[chat_chunks("a"), chat_chunks("b")])
        lab = provider(ollama)
        lab.chat("qwen3:8b", MESSAGES, context_tokens=4096, think=False)
        lab.chat("qwen3:8b", MESSAGES, context_tokens=4096, think=True, keep_alive="10m")
        assert [p["think"] for p in ollama.chat_payloads] == [False, True]
        assert ollama.chat_payloads[1]["keep_alive"] == "10m"

    def test_a_streamed_reply_is_put_back_together(self) -> None:
        chunks = chat_chunks(
            "Looking it up.",
            thinking="The user wants a team.",
            tool_calls=[tool_call("team_stats", team_id=1610612738, season="2025-26")],
        )
        reply = provider(ScriptedOllama(chats=[chunks])).chat(
            "qwen3:8b", MESSAGES, context_tokens=8192
        )
        assert reply.content == "Looking it up."
        assert reply.thinking == "The user wants a team."
        assert [(c.name, dict(c.arguments)) for c in reply.tool_calls] == [
            ("team_stats", {"team_id": 1610612738, "season": "2025-26"})
        ]
        assert (reply.prompt_tokens, reply.output_tokens) == (1200, 40)
        assert reply.output_seconds == pytest.approx(0.8)
        assert reply.tokens_per_second == pytest.approx(50.0)
        assert reply.first_token_seconds == pytest.approx(0.5)
        assert reply.wall_seconds > reply.first_token_seconds
        assert not reply.cut_off

    def test_arguments_sent_as_text_are_read_as_json(self) -> None:
        call = {"function": {"name": "data_status", "arguments": json.dumps({"a": 1})}}
        reply = provider(ScriptedOllama(chats=[chat_chunks(tool_calls=[call])])).chat(
            "qwen3:8b", MESSAGES, context_tokens=4096
        )
        assert dict(reply.tool_calls[0].arguments) == {"a": 1}

    def test_arguments_that_are_not_an_object_are_kept_raw(self) -> None:
        call = {"function": {"name": "data_status", "arguments": "not json"}}
        reply = provider(ScriptedOllama(chats=[chat_chunks(tool_calls=[call])])).chat(
            "qwen3:8b", MESSAGES, context_tokens=4096
        )
        assert reply.tool_calls[0].arguments is None
        assert reply.tool_calls[0].raw == "not json"

    def test_a_reply_stopped_at_the_limit_is_cut_off(self) -> None:
        reply = provider(
            ScriptedOllama(chats=[chat_chunks(thinking="...", done_reason="length")])
        ).chat("qwen3:8b", MESSAGES, context_tokens=4096)
        assert reply.cut_off

    def test_a_404_while_chatting_means_the_model_is_gone(self) -> None:
        ollama = ScriptedOllama(chats=[OllamaResponseError(404, "model 'qwen3:8b' not found")])
        with pytest.raises(ModelNotAvailable, match="ollama pull qwen3:8b"):
            provider(ollama).chat("qwen3:8b", MESSAGES, context_tokens=4096)

    def test_an_error_in_the_stream_is_raised(self) -> None:
        ollama = ScriptedOllama(chats=[[{"error": "out of memory"}]])
        with pytest.raises(OllamaError, match="out of memory"):
            provider(ollama).chat("qwen3:8b", MESSAGES, context_tokens=4096)


class TestWhatIsThere:
    def test_version_and_models(self) -> None:
        listed = {
            "name": "qwen3:8b",
            "size": 5_200,
            "details": {
                "family": "qwen3",
                "parameter_size": "8.2B",
                "quantization_level": "Q4_K_M",
            },
        }
        lab = provider(ScriptedOllama(version="0.40.2", models=[listed]))
        assert lab.version() == "0.40.2"
        (model,) = lab.models()
        assert (model.family, model.parameter_size, model.quantization, model.remote) == (
            "qwen3",
            "8.2B",
            "Q4_K_M",
            False,
        )

    def test_details_read_capabilities_context_and_licence(self) -> None:
        shown = {
            "capabilities": ["completion", "tools", "thinking"],
            "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 40960},
            "license": "\n                                 Apache License\n   Version 2.0",
        }
        details = provider(ScriptedOllama(details={"qwen3:8b": shown})).details("qwen3:8b")
        assert details.can_call_tools and details.can_think
        assert details.context_length == 40960
        assert details.license == "Apache License"

    def test_loaded_models_say_where_they_sit(self) -> None:
        running = [{"name": "qwen3:8b", "size": 6_000, "size_vram": 4_500, "context_length": 8192}]
        (model,) = provider(ScriptedOllama(loaded=running)).loaded()
        assert (model.size_vram, model.in_system_memory, model.context_length) == (
            4_500,
            1_500,
            8192,
        )

    def test_unload_asks_ollama_to_let_go(self) -> None:
        ollama = ScriptedOllama()
        provider(ollama).unload("qwen3:8b")
        assert ollama.requests[-1] == (
            "POST",
            "/api/generate",
            {"model": "qwen3:8b", "keep_alive": 0},
        )

    def test_ollama_not_running_is_unavailable(self) -> None:
        with pytest.raises(OllamaUnavailable):
            provider(ScriptedOllama(down=True)).version()


class TestTheRequestsTransport:
    def response(self, status: int, body: bytes) -> requests.Response:
        answer = requests.Response()
        answer.status_code = status
        answer._content = body
        answer._content_consumed = True
        return answer

    def test_each_line_is_one_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            requests, "request", lambda *a, **k: self.response(200, b'{"a": 1}\n\n{"b": 2}\n')
        )
        assert list(requests_transport("GET", "http://127.0.0.1:11434/api/x", None, 5)) == [
            {"a": 1},
            {"b": 2},
        ]

    def test_an_error_status_carries_ollamas_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            requests, "request", lambda *a, **k: self.response(404, b'{"error": "model not found"}')
        )
        with pytest.raises(OllamaResponseError) as raised:
            list(requests_transport("POST", "http://127.0.0.1:11434/api/chat", {}, 5))
        assert (raised.value.status, raised.value.detail) == (404, "model not found")

    def test_no_connection_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*args: Any, **kwargs: Any) -> None:
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests, "request", refuse)
        with pytest.raises(OllamaUnavailable):
            list(requests_transport("GET", "http://127.0.0.1:11434/api/version", None, 5))

    def test_a_timeout_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def slow(*args: Any, **kwargs: Any) -> None:
            raise requests.Timeout("slow")

        monkeypatch.setattr(requests, "request", slow)
        with pytest.raises(OllamaUnavailable, match="within 5 seconds"):
            list(requests_transport("GET", "http://127.0.0.1:11434/api/version", None, 5))

    def test_a_stream_cut_off_midway_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A9: Ollama stopped, or the machine slept, while it was answering: what came
        before is passed on, then the reason, never a half-answer as if whole."""

        class Cut(requests.Response):
            def iter_lines(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def, override]
                yield b'{"message": {"content": "The Cel"}}'
                raise requests.exceptions.ChunkedEncodingError("Connection broken")

        answer = Cut()
        answer.status_code = 200
        answer._content_consumed = True
        monkeypatch.setattr(requests, "request", lambda *a, **k: answer)
        seen: list = []
        with pytest.raises(OllamaUnavailable, match="Ollama stopped answering"):
            for item in requests_transport("POST", "http://127.0.0.1:11434/api/chat", {}, 5):
                seen.append(item)
        assert seen == [{"message": {"content": "The Cel"}}]

    def test_text_that_is_not_json_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(requests, "request", lambda *a, **k: self.response(200, b"<html>"))
        with pytest.raises(OllamaError, match="not JSON"):
            list(requests_transport("GET", "http://127.0.0.1:11434/api/version", None, 5))
