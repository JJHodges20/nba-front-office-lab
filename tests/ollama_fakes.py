"""A stand-in for Ollama's HTTP interface, for tests that need no running model.

``ScriptedOllama`` is a transport for ``OllamaProvider``: it answers by path, hands out
scripted chat replies in order, and records every request, so a test can check what was
sent as well as what came back.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from front_office.providers.ollama import OllamaResponseError, OllamaUnavailable

TOOLS_MODEL = {
    "capabilities": ["completion", "tools"],
    "model_info": {"qwen3.context_length": 40960},
}


def tool_call(name: str, **arguments: Any) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": arguments}}


def chat_chunks(
    content: str = "",
    *,
    thinking: str = "",
    tool_calls: Sequence[Mapping[str, Any]] = (),
    done_reason: str = "stop",
    prompt_tokens: int = 1200,
    output_tokens: int = 40,
) -> list[dict[str, Any]]:
    """A streamed reply as Ollama sends it: thinking, then text, then calls, then the counts."""
    chunks: list[dict[str, Any]] = []
    if thinking:
        chunks.append({"message": {"role": "assistant", "content": "", "thinking": thinking}})
    if content:
        chunks.append({"message": {"role": "assistant", "content": content}})
    if tool_calls:
        chunks.append(
            {"message": {"role": "assistant", "content": "", "tool_calls": list(tool_calls)}}
        )
    chunks.append(
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": done_reason,
            "prompt_eval_count": prompt_tokens,
            "eval_count": output_tokens,
            "load_duration": 2_000_000,
            "prompt_eval_duration": 300_000_000,
            "eval_duration": 800_000_000,
            "total_duration": 1_102_000_000,
        }
    )
    return chunks


class ScriptedOllama:
    """Ollama's interface, answering from a script."""

    def __init__(
        self,
        *,
        version: str = "0.40.0",
        models: Sequence[str | Mapping[str, Any]] = ("qwen3:8b",),
        details: Mapping[str, Mapping[str, Any]] | None = None,
        chats: Sequence[Sequence[Mapping[str, Any]] | Exception] = (),
        loaded: Sequence[Mapping[str, Any]] = (),
        down: bool = False,
    ) -> None:
        self.version = version
        self.models = [
            {"name": m, "size": 5_000} if isinstance(m, str) else dict(m) for m in models
        ]
        self.details = dict(details or {})
        self.chats = list(chats)
        self.loaded = list(loaded)
        self.down = down
        self.requests: list[tuple[str, str, Any]] = []

    @property
    def chat_payloads(self) -> list[Mapping[str, Any]]:
        return [payload for _, path, payload in self.requests if path == "/api/chat"]

    def __call__(
        self, method: str, url: str, payload: Mapping[str, Any] | None, timeout: float
    ) -> Iterator[Mapping[str, Any]]:
        path = urlsplit(url).path
        self.requests.append((method, path, payload))
        if self.down:
            raise OllamaUnavailable("connection refused")
        if path == "/api/version":
            yield {"version": self.version}
        elif path == "/api/tags":
            yield {"models": self.models}
        elif path == "/api/show":
            yield self.details.get(str(payload["model"]), TOOLS_MODEL)
        elif path == "/api/ps":
            yield {"models": self.loaded}
        elif path == "/api/generate":
            yield {"done": True}
        elif path == "/api/chat":
            if not self.chats:
                raise AssertionError("the script has no chat reply left")
            step = self.chats.pop(0)
            if isinstance(step, Exception):
                raise step
            yield from step
        else:
            raise OllamaResponseError(404, f"no such path {path}")
