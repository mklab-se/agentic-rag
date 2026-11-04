"""The model boundary: stream items and the Responses API implementation."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


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


@dataclass
class Failed:
    code: str
    message: str = ""


@dataclass
class Completed:
    usage: dict = field(default_factory=dict)


StreamItem = TextDelta | FunctionCall | McpCall | Completed | Failed


class ModelClient(Protocol):
    def stream(
        self, *, instructions: str, conversation: str, input: str | list[dict], tools: list[dict]
    ) -> AsyncIterator[StreamItem]: ...


class ResponsesModelClient:
    """Streams one model call through the Responses API of a Foundry project.

    With `agent_name` the call goes to that Foundry prompt agent instead: the agent's own
    definition supplies model, instructions and tools, and Foundry rejects a request that
    also sets them ("Not allowed when agent is specified"), so they are left out.
    """

    def __init__(self, openai_client, model: str | None = None, agent_name: str | None = None):
        if model is None and agent_name is None:
            raise ValueError("ResponsesModelClient needs a model or an agent_name")
        self._client = openai_client  # AsyncOpenAI from AIProjectClient.get_openai_client()
        self._model = model
        self._agent_name = agent_name

    async def stream(
        self, *, instructions: str, conversation: str, input: str | list[dict], tools: list[dict]
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
                stream=True,
            )
        async with events:
            async for event in events:
                item = _map_event(event)
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
            return McpCall(out.name, getattr(out, "server_label", ""), preview)
        return None
    if kind == "response.completed":
        usage = getattr(event.response, "usage", None)
        return Completed(usage.model_dump() if usage is not None else {})
    return None


def _failure_message(error) -> str:
    return str(getattr(error, "message", "") or "")
