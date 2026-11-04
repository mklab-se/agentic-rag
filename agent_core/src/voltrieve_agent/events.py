"""Events streamed from an agent turn to its client, and their server-sent-event wire format."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# An SSE comment: ignored by clients, but keeps idle connections open (Container Apps closes
# connections that are idle for 240 seconds).
KEEPALIVE = b": keep-alive\n\n"
KEEPALIVE_SECONDS = 15.0


@dataclass(frozen=True)
class AgentEvent:
    type: str  # trace, delta, client_tool_calls, done, error
    data: dict


Emit = Callable[[AgentEvent], Awaitable[None]]


def trace(step: str, component: str, detail: str = "", **extra) -> AgentEvent:
    return AgentEvent("trace", {"step": step, "component": component, "detail": detail, **extra})


def format_event(event: AgentEvent) -> bytes:
    """One server-sent event: `event:` is the type, `data:` a single line of JSON.

    ASCII only: U+2028, U+2029 and U+0085 would be taken as line breaks by readers that split
    lines on them (httpx does), which would corrupt the event."""
    data = json.dumps(event.data, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event.type}\ndata: {data}\n\n".encode()
