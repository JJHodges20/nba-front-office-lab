"""Ollama on this machine: the AI research assistant's language model, over HTTP.

Decision 0018. The model runs locally, and this adapter makes sure of it: it talks to the
loopback address only, and refuses a model that Ollama marks as remote or whose name is a
cloud model's - a signed-in Ollama serves cloud models through the same local interface,
and bills for them. The context length is sent with every request rather than left to the
server's default. Like every provider it returns what it was sent, in plain types, and
interprets nothing.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from front_office.domain.assistant import is_cloud_model, is_loopback_url

DEFAULT_HOST = "http://127.0.0.1:11434"
# Ollama reports durations in nanoseconds. Written as a power, since a literal this large is
# what the boundary test reads as a cap figure.
NANOSECONDS = 1_000**3


class OllamaError(RuntimeError):
    """Ollama answered with an error, or with something that is not its interface."""


class OllamaUnavailable(OllamaError):
    """Ollama is not running at the address, or did not answer in time."""


class ModelNotAvailable(OllamaError):
    """The model is not pulled on this machine."""


class NotLocal(OllamaError):
    """An address, or a model, that is not on this machine."""


class OllamaResponseError(OllamaError):
    """Ollama answered a request with an error status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Ollama answered {status}: {detail}")
        self.status = status
        self.detail = detail


class Transport(Protocol):
    """Sends one request and yields each JSON object of the answer: one, or one per line
    of a streamed answer."""

    def __call__(
        self, method: str, url: str, payload: Mapping[str, Any] | None, timeout: float
    ) -> Iterator[Mapping[str, Any]]: ...


def requests_transport(
    method: str, url: str, payload: Mapping[str, Any] | None, timeout: float
) -> Iterator[Mapping[str, Any]]:
    """Ollama's HTTP interface through ``requests``, reading a streamed answer line by line."""
    try:
        response = requests.request(method, url, json=payload, timeout=timeout, stream=True)
    except requests.Timeout as error:
        raise OllamaUnavailable(f"Ollama did not answer within {timeout:g} seconds") from error
    except requests.RequestException as error:
        raise OllamaUnavailable(f"Ollama is not answering at {url}: {error}") from error
    with response:
        if response.status_code >= 400:
            raise OllamaResponseError(response.status_code, _error_detail(response))
        try:
            for line in response.iter_lines():
                if line:
                    yield json.loads(line)
        except requests.RequestException as error:
            raise OllamaUnavailable(f"Ollama stopped answering: {error}") from error
        except ValueError as error:
            raise OllamaError(f"Ollama sent something that is not JSON: {error}") from error


def _error_detail(response: requests.Response) -> str:
    try:
        return str(response.json().get("error") or response.text)
    except ValueError:
        return response.text.strip()[:300] or response.reason


@dataclass(frozen=True, slots=True)
class LocalModel:
    """A model Ollama lists on this machine."""

    name: str
    size: int
    family: str | None
    parameter_size: str | None
    quantization: str | None
    remote: bool
    """Ollama marks a cloud model it lists with a remote model or host."""


@dataclass(frozen=True, slots=True)
class ModelDetails:
    name: str
    capabilities: tuple[str, ...]
    context_length: int | None
    """The longest context the model was trained for, not what a request uses."""
    license: str | None
    """The first line of the model's licence, as Ollama reports it."""

    @property
    def can_call_tools(self) -> bool:
        return "tools" in self.capabilities

    @property
    def can_think(self) -> bool:
        return "thinking" in self.capabilities


@dataclass(frozen=True, slots=True)
class LoadedModel:
    """A model Ollama holds in memory, and where."""

    name: str
    size: int
    size_vram: int
    context_length: int | None

    @property
    def in_system_memory(self) -> int:
        """Bytes of the model held in system memory rather than on the GPU."""
        return max(self.size - self.size_vram, 0)


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any] | None
    """``None`` when the model's arguments were not a JSON object; ``raw`` holds them."""
    raw: str | None = None


@dataclass(frozen=True, slots=True)
class ChatReply:
    """One answer from the model, with Ollama's own counts and timings."""

    model: str
    content: str
    thinking: str
    tool_calls: tuple[ToolCall, ...]
    done_reason: str | None
    prompt_tokens: int | None
    output_tokens: int | None
    load_seconds: float | None
    prompt_seconds: float | None
    output_seconds: float | None
    total_seconds: float | None
    first_token_seconds: float | None
    """Wall-clock time to the first streamed text, thinking or tool call."""
    wall_seconds: float

    @property
    def cut_off(self) -> bool:
        """Whether the answer stopped at the output limit rather than finishing."""
        return self.done_reason == "length"

    @property
    def tokens_per_second(self) -> float | None:
        if not self.output_tokens or not self.output_seconds:
            return None
        return self.output_tokens / self.output_seconds


class OllamaProvider:
    """The local Ollama server's interface, refusing anything that is not on this machine."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        *,
        timeout: float = 180.0,
        transport: Transport = requests_transport,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not is_loopback_url(host):
            raise NotLocal(
                f"the model must run on this machine; {host!r} is not a loopback address"
            )
        self.host = host.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._clock = clock
        self._checked: dict[str, LocalModel] = {}

    # --- what is there ------------------------------------------------------------------

    def version(self) -> str:
        return str(self._one("GET", "/api/version").get("version", ""))

    def models(self) -> tuple[LocalModel, ...]:
        """Every model Ollama lists, remote ones included and marked."""
        listed = self._one("GET", "/api/tags").get("models") or []
        return tuple(_local_model(item) for item in listed)

    def details(self, model: str) -> ModelDetails:
        shown = self._one("POST", "/api/show", {"model": model})
        info = shown.get("model_info") or {}
        context = next(
            (int(value) for key, value in info.items() if key.endswith(".context_length")), None
        )
        licence = str(shown.get("license") or "").strip()
        return ModelDetails(
            name=model,
            capabilities=tuple(shown.get("capabilities") or ()),
            context_length=context,
            license=licence.splitlines()[0].strip() if licence else None,
        )

    def loaded(self) -> tuple[LoadedModel, ...]:
        running = self._one("GET", "/api/ps").get("models") or []
        return tuple(
            LoadedModel(
                name=str(item.get("name") or item.get("model")),
                size=int(item.get("size") or 0),
                size_vram=int(item.get("size_vram") or 0),
                context_length=_maybe_int(item.get("context_length")),
            )
            for item in running
        )

    def require_local(self, model: str) -> LocalModel:
        """The model as listed on this machine; refused if remote, missing or a cloud model."""
        if is_cloud_model(model):
            raise NotLocal(f"{model} is a cloud model; the lab uses local models only")
        if model in self._checked:
            return self._checked[model]
        wanted = model if ":" in model else f"{model}:latest"
        for listed in self.models():
            if listed.name in (model, wanted):
                if listed.remote:
                    raise NotLocal(f"{model} runs remotely; the lab uses local models only")
                self._checked[model] = listed
                return listed
        raise ModelNotAvailable(f"{model} is not on this machine. Run: ollama pull {model}")

    # --- asking -------------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        context_tokens: int,
        tools: Sequence[Mapping[str, Any]] = (),
        think: bool | None = None,
        max_output_tokens: int | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        keep_alive: str | int | None = None,
    ) -> ChatReply:
        """One answer, streamed and put back together. ``think`` is sent only when given:
        a model that cannot think refuses the field."""
        self.require_local(model)
        options: dict[str, Any] = {"num_ctx": context_tokens, "temperature": temperature}
        if max_output_tokens is not None:
            options["num_predict"] = max_output_tokens
        if seed is not None:
            options["seed"] = seed
        payload: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            "options": options,
        }
        if tools:
            payload["tools"] = list(tools)
        if think is not None:
            payload["think"] = think
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        started = self._clock()
        first: float | None = None
        content: list[str] = []
        thinking: list[str] = []
        calls: list[ToolCall] = []
        final: Mapping[str, Any] = {}
        try:
            for chunk in self._transport("POST", f"{self.host}/api/chat", payload, self._timeout):
                if chunk.get("error"):
                    raise OllamaError(f"Ollama stopped with an error: {chunk['error']}")
                message = chunk.get("message") or {}
                piece = str(message.get("content") or "")
                thought = str(message.get("thinking") or "")
                asked = message.get("tool_calls") or []
                if first is None and (piece or thought or asked):
                    first = self._clock() - started
                content.append(piece)
                thinking.append(thought)
                calls.extend(_tool_call(item) for item in asked)
                if chunk.get("done"):
                    final = chunk
        except OllamaResponseError as error:
            if error.status == 404:
                raise ModelNotAvailable(
                    f"{model} is not on this machine. Run: ollama pull {model}"
                ) from error
            raise
        return ChatReply(
            model=model,
            content="".join(content),
            thinking="".join(thinking),
            tool_calls=tuple(calls),
            done_reason=final.get("done_reason"),
            prompt_tokens=_maybe_int(final.get("prompt_eval_count")),
            output_tokens=_maybe_int(final.get("eval_count")),
            load_seconds=_seconds(final.get("load_duration")),
            prompt_seconds=_seconds(final.get("prompt_eval_duration")),
            output_seconds=_seconds(final.get("eval_duration")),
            total_seconds=_seconds(final.get("total_duration")),
            first_token_seconds=first,
            wall_seconds=self._clock() - started,
        )

    def unload(self, model: str) -> None:
        """Take a model out of memory now, so that the next request loads it afresh."""
        self._one("POST", "/api/generate", {"model": model, "keep_alive": 0})

    def _one(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Mapping:
        answers = self._transport(method, f"{self.host}{path}", payload, self._timeout)
        try:
            for answer in answers:
                return answer
        finally:
            close = getattr(answers, "close", None)
            if close is not None:
                close()
        raise OllamaError(f"Ollama sent nothing for {path}")


def _local_model(item: Mapping[str, Any]) -> LocalModel:
    details = item.get("details") or {}
    return LocalModel(
        name=str(item.get("name") or item.get("model")),
        size=int(item.get("size") or 0),
        family=details.get("family"),
        parameter_size=details.get("parameter_size"),
        quantization=details.get("quantization_level"),
        remote=bool(item.get("remote_model") or item.get("remote_host")),
    )


def _tool_call(item: Mapping[str, Any]) -> ToolCall:
    function = item.get("function") or {}
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except ValueError:
            return ToolCall(str(function.get("name") or ""), None, arguments)
        arguments = parsed
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, Mapping):
        return ToolCall(str(function.get("name") or ""), None, json.dumps(arguments))
    return ToolCall(str(function.get("name") or ""), dict(arguments))


def _maybe_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _seconds(nanoseconds: Any) -> float | None:
    return None if nanoseconds is None else float(nanoseconds) / NANOSECONDS
