"""The backend interface: what a host needs from an agent implementation."""

from dataclasses import dataclass, field
from typing import Protocol

from voltrieve_agent.events import Emit
from voltrieve_agent.loop import TurnOutcome
from voltrieve_agent.tools import ClientTool, UserContext


@dataclass
class TurnContext:
    user: UserContext
    conversation_id: str
    turn_id: str
    # The new user message (str), or, when continuing a paused turn, the client results as
    # function_call_output items covering every pending call id.
    input: str | list[dict]
    client_tools: list[ClientTool] = field(default_factory=list)
    # Server tool outputs from the paused iteration. They must reach the conversation
    # together with the client results. Empty for a new message.
    pending_outputs: list[dict] = field(default_factory=list)
    correlation_id: str | None = None


class Backend(Protocol):
    async def create_conversation(self) -> str:
        """Create the server-side conversation for a first turn and return its id."""
        ...

    async def run_turn(self, ctx: TurnContext, emit: Emit) -> TurnOutcome:
        """Run or continue a turn. Emits trace/delta/client_tool_calls/error, never done."""
        ...

    async def abandon(self, conversation_id: str, outputs: list[dict]) -> None:
        """Close a paused turn nobody will continue by adding outputs for its open calls."""
        ...


class BackendUnavailable(Exception):
    """The named backend is unknown or not configured in this deployment."""
