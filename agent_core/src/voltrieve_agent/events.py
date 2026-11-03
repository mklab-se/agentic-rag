"""Events streamed from an agent turn to its client."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentEvent:
    type: str  # trace, delta, client_tool_calls, done, error
    data: dict


Emit = Callable[[AgentEvent], Awaitable[None]]


def trace(step: str, component: str, detail: str = "", **extra) -> AgentEvent:
    return AgentEvent("trace", {"step": step, "component": component, "detail": detail, **extra})
