"""The backend interface: what a host needs from an agent implementation."""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from voltrieve_agent.events import Emit
from voltrieve_agent.loop import TurnOutcome
from voltrieve_agent.tools import ClientTool, UserContext

logger = logging.getLogger(__name__)

# The output given to a function call that nobody answered (an abandoned or expired pause,
# or a call found open when a conversation is repaired).
ABANDONED_OUTPUT = "the client did not return a result"
REPAIR_SCAN_ITEMS = 100
REPAIR_BATCH = 20
# Statuses with which Foundry says the conversation does not exist or is not ours.
NOT_FOUND_STATUSES = (400, 403, 404)


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
    async def create_conversation(self, owner_oid: str) -> str:
        """Create the server-side conversation for a first turn and return its id.
        The owner is stored with the conversation, so ownership survives restarts."""
        ...

    async def get_conversation_owner(self, conversation_id: str) -> str | None:
        """The owner oid stored with the conversation, or None if unknown or not readable."""
        ...

    async def run_turn(self, ctx: TurnContext, emit: Emit) -> TurnOutcome:
        """Run or continue a turn. Emits trace/delta/client_tool_calls/error, never done."""
        ...

    async def abandon(self, conversation_id: str, outputs: list[dict]) -> None:
        """Close a paused turn nobody will continue by adding outputs for its open calls."""
        ...

    async def repair(self, conversation_id: str) -> None:
        """Give every recent function_call without an output a synthetic output. Raises if
        the conversation cannot be repaired."""
        ...

    async def close(self) -> None:
        """Release clients and credentials at shutdown."""
        ...


class BackendUnavailable(Exception):
    """The named backend is unknown or not configured in this deployment."""


class ConversationBackend:
    """What backends share: the conversation lives in Foundry Conversations."""

    def __init__(self, openai_client, closers: Sequence[Callable[[], Awaitable[None]]] = ()):
        self._openai = openai_client  # AsyncOpenAI; only its conversations API is used here
        self._closers = closers

    async def create_conversation(self, owner_oid: str) -> str:
        conversation = await self._openai.conversations.create(metadata={"owner_oid": owner_oid})
        return conversation.id

    async def get_conversation_owner(self, conversation_id: str) -> str | None:
        """None when Foundry says there is no such conversation. Any other failure (an
        outage) raises, so the API can answer 503 instead of pretending it was not found."""
        try:
            conversation = await self._openai.conversations.retrieve(conversation_id)
        except Exception as exc:
            if getattr(exc, "status_code", None) in NOT_FOUND_STATUSES:
                logger.info("Conversation %s not found (HTTP %s)", conversation_id, exc.status_code)
                return None
            raise
        return (getattr(conversation, "metadata", None) or {}).get("owner_oid")

    async def abandon(self, conversation_id: str, outputs: list[dict]) -> None:
        # Adding items does not call the model, so abandoning costs no tokens.
        if outputs:
            await self._openai.conversations.items.create(conversation_id, items=outputs)

    async def repair(self, conversation_id: str) -> None:
        calls: list[str] = []
        answered: set[str] = set()
        page = await self._openai.conversations.items.list(
            conversation_id, limit=REPAIR_SCAN_ITEMS, order="desc"
        )
        async for item in page:
            if item.type == "function_call":
                calls.append(item.call_id)
            elif item.type == "function_call_output":
                answered.add(item.call_id)
            if len(calls) + len(answered) >= REPAIR_SCAN_ITEMS:
                break
        missing = [
            {"type": "function_call_output", "call_id": c, "output": ABANDONED_OUTPUT}
            for c in dict.fromkeys(calls)
            if c not in answered
        ]
        for start in range(0, len(missing), REPAIR_BATCH):
            await self._openai.conversations.items.create(
                conversation_id, items=missing[start : start + REPAIR_BATCH]
            )
        if missing:
            logger.info("Repaired %d open calls in %s", len(missing), conversation_id)

    async def close(self) -> None:
        for closer in self._closers:
            try:
                await closer()
            except Exception:
                logger.exception("Closing the backend failed")


async def close_all(http, openai_client, project, credential) -> None:
    """Close what a backend opened at start-up (every backend closes the same four things)."""
    await http.aclose()
    await openai_client.close()
    await project.close()
    await credential.close()
