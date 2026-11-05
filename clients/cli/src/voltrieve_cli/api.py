"""HTTP/SSE client for the Voltrieve API contract."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .tools import CLIENT_TOOLS, run_tool

Event = tuple[str, dict[str, Any]]


def parse_sse(lines: Iterable[str]) -> Iterator[Event]:
    """Pure SSE parser: text lines in, (event, data) out. Non-JSON data is kept under 'raw'."""
    name = "message"
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                yield name, _decode("\n".join(data))
            name, data = "message", []
        elif line.startswith(":"):
            continue
        else:
            field_name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field_name == "event":
                name = value
            elif field_name == "data":
                data.append(value)
    if data:
        yield name, _decode("\n".join(data))


def _decode(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    return value if isinstance(value, dict) else {"value": value}


class ApiError(Exception):
    pass


@dataclass
class TurnOutcome:
    conversation_id: str | None = None
    correlation_id: str = ""
    text: str = ""
    done: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    tool_runs: list[tuple[str, str]] = field(default_factory=list)


class ApiClient:
    def __init__(self, base_url: str, token: str | Callable[[], str], backend: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout: float = 120.0):
        self._token = token if callable(token) else (lambda: token)
        self._backend = backend
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def _stream(self, path: str, body: dict[str, Any], correlation_id: str | None) -> Iterator[Event]:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if self._backend:
            headers["X-Agent-Backend"] = self._backend
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id
        try:
            with self._http.stream("POST", path, json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise ApiError(f"{path} returned HTTP {resp.status_code}")
                yield from parse_sse(resp.iter_lines())
        except httpx.HTTPError as exc:
            # Unreachable, timed out, or the stream broke: one error type for the callers.
            raise ApiError(f"{path} failed: {type(exc).__name__}") from exc

    def chat(self, message: str, conversation_id: str | None = None,
             client_tools: list[dict[str, Any]] | None = None,
             correlation_id: str | None = None) -> Iterator[Event]:
        body: dict[str, Any] = {"message": message, "client_tools": client_tools or []}
        if conversation_id:
            body["conversation_id"] = conversation_id
        return self._stream("/chat", body, correlation_id)

    def tool_results(self, conversation_id: str, turn_id: str, results: list[dict[str, str]],
                     correlation_id: str | None = None) -> Iterator[Event]:
        return self._stream("/chat/tool-results", {
            "conversation_id": conversation_id, "turn_id": turn_id, "results": results},
            correlation_id)


def run_turn(client: ApiClient, message: str, conversation_id: str | None,
             on_event: Callable[[str, dict[str, Any]], None],
             banner: Callable[[str], None] | None = None,
             bell: Callable[[], None] | None = None,
             gauge: Callable[[int], None] | None = None,
             tools: list[dict[str, Any]] | None = None,
             max_rounds: int = 8) -> TurnOutcome:
    """Send a message, run any requested client tools, post results, until done or error.

    One correlation id covers the whole turn: every request of it (the message and each
    tool-results post) carries it, so logs and traces of all of them can be found together."""
    outcome = TurnOutcome(conversation_id=conversation_id, correlation_id=str(uuid.uuid4()))
    on_event("turn_started", {"correlation_id": outcome.correlation_id})
    stream = client.chat(message, conversation_id, CLIENT_TOOLS if tools is None else tools,
                         outcome.correlation_id)
    for _ in range(max_rounds):
        pending: dict[str, Any] | None = None
        for name, data in stream:
            on_event(name, data)
            if data.get("conversation_id"):
                outcome.conversation_id = data["conversation_id"]
            if name == "delta":
                outcome.text += str(data.get("text", ""))
            elif name == "client_tool_calls":
                pending = data
            elif name == "done":
                outcome.done = data
                outcome.conversation_id = data.get("conversation_id") or outcome.conversation_id
            elif name == "error":
                outcome.error = data
        if pending is None:
            return outcome
        results = []
        for call in pending.get("calls", []):
            output = run_tool(call.get("name", ""), call.get("arguments"), banner=banner, bell=bell,
                              gauge=gauge)
            outcome.tool_runs.append((call.get("name", ""), output))
            on_event("tool_ran", {"name": call.get("name"), "output": output})
            results.append({"call_id": call.get("call_id", ""), "output": output})
        conv = pending.get("conversation_id") or outcome.conversation_id
        if not conv:
            outcome.error = {"code": "client", "message": "no conversation id to post tool results"}
            return outcome
        stream = client.tool_results(conv, pending.get("turn_id", ""), results,
                                     outcome.correlation_id)
    outcome.error = {"code": "client", "message": "too many tool rounds"}
    return outcome
