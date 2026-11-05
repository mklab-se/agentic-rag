"""The model boundary: stream items and the Responses API implementation."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

import openai

# Comparison questions across documents went wrong too often at the default effort.
REASONING_EFFORT = "medium"
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_DELAY_SECONDS = 20.0


@dataclass
class TextDelta:
    text: str


@dataclass
class FunctionCall:
    call_id: str
    name: str
    arguments: str


@dataclass
class McpCall:
    name: str
    server: str
    output_preview: str
    arguments: str = ""
    # Milliseconds since this model call began. The interval is what shows whether two calls ran
    # at the same time, since Foundry runs them and the host only sees them go by.
    started_ms: int | None = field(default=None, compare=False)
    finished_ms: int | None = field(default=None, compare=False)


@dataclass
class Failed:
    code: str
    message: str = ""


@dataclass
class Completed:
    usage: dict = field(default_factory=dict)


def merge_usage(total: dict, more: dict) -> dict:
    """Sum two usage dicts, descending into nested ones (token detail breakdowns)."""
    merged = dict(total)
    for key, value in more.items():
        if isinstance(value, dict):
            merged[key] = merge_usage(merged.get(key) or {}, value)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            merged[key] = merged.get(key, 0) + value
    return merged


StreamItem = TextDelta | FunctionCall | McpCall | Completed | Failed


class ModelClient(Protocol):
    def stream(
        self, *, instructions: str, conversation: str, input: str | list[dict], tools: list[dict]
    ) -> AsyncIterator[StreamItem]: ...

    async def record(self, conversation: str, items: list[dict]) -> None: ...


class ResponsesModelClient:
    """Streams one model call through the Responses API of a Foundry project.

    With `agent_name` the call goes to that Foundry prompt agent instead: the agent's own
    definition supplies model, instructions and tools, and Foundry rejects a request that
    also sets them ("Not allowed when agent is specified"), so they are left out.
    """

    def __init__(
        self,
        openai_client,
        model: str | None = None,
        agent_name: str | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if model is None and agent_name is None:
            raise ValueError("ResponsesModelClient needs a model or an agent_name")
        self._client = openai_client  # AsyncOpenAI from AIProjectClient.get_openai_client()
        self._model = model
        self._agent_name = agent_name
        self._sleep = sleep

    async def stream(
        self, *, instructions: str, conversation: str, input: str | list[dict], tools: list[dict]
    ) -> AsyncIterator[StreamItem]:
        """Retries a rate limited call, which Foundry reports mid-stream, until output has started."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            started = False
            try:
                async for item in self._stream_once(instructions, conversation, input, tools):
                    started = True
                    yield item
                return
            except openai.APIError as exc:
                limited = "rate limit" in str(exc).lower()
                if started or not limited or attempt == RATE_LIMIT_RETRIES:
                    raise
                await self._sleep(RATE_LIMIT_DELAY_SECONDS * (attempt + 1))

    async def record(self, conversation: str, items: list[dict]) -> None:
        """Add items to the conversation without calling the model, so it costs no tokens."""
        await self._client.conversations.items.create(conversation, items=items)

    async def _stream_once(
        self, instructions: str, conversation: str, input: str | list[dict], tools: list[dict]
    ) -> AsyncIterator[StreamItem]:
        if self._agent_name is not None:
            events = await self._client.responses.create(
                conversation=conversation,
                input=input,
                extra_body={"agent_reference": {"name": self._agent_name, "type": "agent_reference"}},
                stream=True,
            )
        else:
            events = await self._client.responses.create(
                model=self._model,
                instructions=instructions,
                conversation=conversation,
                input=input,
                tools=tools,
                parallel_tool_calls=True,  # one response may ask for several tools at once
                reasoning={"effort": REASONING_EFFORT},
                stream=True,
            )
        began = time.perf_counter()
        mcp_started: dict[str, int] = {}

        def elapsed_ms() -> int:
            return round((time.perf_counter() - began) * 1000)

        async with events:
            async for event in events:
                if event.type == "response.output_item.added" and event.item.type == "mcp_call":
                    mcp_started[event.item.id] = elapsed_ms()
                item = _map_event(event)
                if isinstance(item, McpCall):
                    item.started_ms = mcp_started.get(getattr(event.item, "id", ""))
                    item.finished_ms = elapsed_ms()
                if item is not None:
                    yield item


def _map_event(event) -> StreamItem | None:
    kind = event.type
    if kind == "response.output_text.delta":
        return TextDelta(event.delta)
    if kind == "response.refusal.delta":
        return TextDelta(event.delta)
    if kind == "response.failed":
        return Failed("model_failed", _failure_message(getattr(event.response, "error", None)))
    if kind == "response.incomplete":
        details = getattr(event.response, "incomplete_details", None)
        return Failed("model_incomplete", str(getattr(details, "reason", "") or ""))
    if kind == "error":
        return Failed("model_error", str(getattr(event, "message", "") or ""))
    if kind == "response.output_item.done":
        out = event.item
        if out.type == "function_call":
            return FunctionCall(out.call_id, out.name, out.arguments)
        if out.type == "mcp_call":
            # A failed call has no output, only an error text: show that.
            preview = str(getattr(out, "output", None) or getattr(out, "error", None) or "")[:500]
            arguments = str(getattr(out, "arguments", "") or "")
            return McpCall(out.name, getattr(out, "server_label", ""), preview, arguments)
        return None
    if kind == "response.completed":
        usage = getattr(event.response, "usage", None)
        return Completed(usage.model_dump() if usage is not None else {})
    return None


def _failure_message(error) -> str:
    return str(getattr(error, "message", "") or "")
