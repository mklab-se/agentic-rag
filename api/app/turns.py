"""Turn state and the runner that drives a backend turn into an SSE stream.

State lives in this process: `TurnStore` is a dict, so the API runs with maxReplicas 1 and
a restart loses paused turns and conversation ownership. Clients then get `turn_expired`
or a 403 for an unknown conversation and start over.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from voltrieve_agent.events import AgentEvent, trace
from voltrieve_agent.tools import ClientTool, UserContext

from app.auth import Claims
from app.backends import BackendRegistry
from app.backends.base import TurnContext
from app.logging_setup import bind_log_context, correlation_id
from app.sse import format_event

logger = logging.getLogger(__name__)

TURN_TTL_SECONDS = 15 * 60
ABANDONED_OUTPUT = "the client did not return a result"
GENERIC_ERROR = AgentEvent(
    "error", {"code": "internal_error", "message": "The request could not be completed."}
)


@dataclass
class PausedTurn:
    turn_id: str
    oid: str
    conversation_id: str
    backend: str
    client_tools: list[ClientTool]
    pending_outputs: list[dict]
    expected_call_ids: frozenset[str]
    expires_at: float = 0.0

    def abandon_outputs(self) -> list[dict]:
        """Outputs that close every open function_call of this turn."""
        return [
            *self.pending_outputs,
            *(
                {"type": "function_call_output", "call_id": call_id, "output": ABANDONED_OUTPUT}
                for call_id in sorted(self.expected_call_ids)
            ),
        ]


class TurnStore:
    def __init__(self, ttl: float = TURN_TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl
        self._clock = clock
        self._paused: dict[str, PausedTurn] = {}
        self._paused_by_conversation: dict[str, str] = {}
        self._conversation_owner: dict[str, str] = {}

    def register_conversation(self, conversation_id: str, oid: str) -> None:
        self._conversation_owner[conversation_id] = oid

    def conversation_owner(self, conversation_id: str) -> str | None:
        return self._conversation_owner.get(conversation_id)

    def put(self, paused: PausedTurn) -> None:
        paused.expires_at = self._clock() + self._ttl
        self._paused[paused.turn_id] = paused
        self._paused_by_conversation[paused.conversation_id] = paused.turn_id

    def get(self, turn_id: str) -> PausedTurn | None:
        return self._paused.get(turn_id)

    def is_expired(self, paused: PausedTurn) -> bool:
        return self._clock() >= paused.expires_at

    def remove(self, turn_id: str) -> PausedTurn | None:
        paused = self._paused.pop(turn_id, None)
        if paused and self._paused_by_conversation.get(paused.conversation_id) == turn_id:
            del self._paused_by_conversation[paused.conversation_id]
        return paused

    def remove_for_conversation(self, conversation_id: str) -> PausedTurn | None:
        """Take the paused turn of a conversation, expired or not (it still needs closing)."""
        turn_id = self._paused_by_conversation.get(conversation_id)
        return self.remove(turn_id) if turn_id else None


@dataclass
class Job:
    claims: Claims
    backend: str
    conversation_id: str | None  # None: create one
    turn_id: str
    input: str | list[dict]
    client_tools: list[ClientTool] = field(default_factory=list)
    pending_outputs: list[dict] = field(default_factory=list)
    stale: PausedTurn | None = None  # a paused turn to close before running
    turn_expired: bool = False  # answer turn_expired instead of running
    expired: PausedTurn | None = None  # with turn_expired: also close this turn


class _Run:
    """The events of one request: a queue the response drains, fed by a background task."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._start = time.perf_counter()
        self.held_tool_calls: AgentEvent | None = None

    async def emit(self, event: AgentEvent) -> None:
        if event.type == "trace" and "elapsed_ms" not in event.data:
            elapsed = round((time.perf_counter() - self._start) * 1000, 1)
            event = AgentEvent("trace", {**event.data, "elapsed_ms": elapsed})
        if event.type == "client_tool_calls":
            # Held until the paused turn is stored, so a fast client never beats the store.
            self.held_tool_calls = event
            return
        await self.queue.put(event)


class TurnService:
    def __init__(self, store: TurnStore, registry: BackendRegistry):
        self.store = store
        self._registry = registry
        self._tasks: set[asyncio.Task] = set()

    def start(self, job: Job) -> AsyncIterator[bytes]:
        """Start the turn in the background and return its SSE byte stream.

        The turn is not tied to the response: if the client disconnects, it still runs to
        its end, so the conversation is never left with a function call without output.
        """
        run = _Run()
        task = asyncio.create_task(self._execute(run, job, correlation_id.get()))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return self._drain(run)

    @staticmethod
    async def _drain(run: _Run) -> AsyncIterator[bytes]:
        while (event := await run.queue.get()) is not None:
            yield format_event(event)

    async def _execute(self, run: _Run, job: Job, cid: str) -> None:
        correlation_id.set(cid)
        oid = job.claims.oid
        bind_log_context(
            user_oid=oid,
            backend=job.backend,
            turn_id=job.turn_id,
            conversation_id=job.conversation_id or "",
        )
        try:
            await run.emit(
                trace(
                    "token_validated",
                    "auth",
                    "roles: " + ", ".join(job.claims.roles),
                    roles=job.claims.roles,
                    user=job.claims.username,
                )
            )
            await run.emit(
                trace("backend_selected", "api", job.backend, backend=job.backend)
            )
            if job.turn_expired:
                if job.expired is not None:
                    await self._close(job.expired, run)
                await run.emit(
                    AgentEvent(
                        "error",
                        {
                            "code": "turn_expired",
                            "message": "This turn is no longer available. Send the message again.",
                        },
                    )
                )
                return
            backend = self._registry.get_backend(job.backend)
            if job.stale is not None:
                await self._close(job.stale, run)

            conversation_id = job.conversation_id
            if conversation_id is None:
                conversation_id = await backend.create_conversation()
                self.store.register_conversation(conversation_id, oid)
                bind_log_context(conversation_id=conversation_id)
                await run.emit(
                    trace("conversation_created", "api", conversation_id)
                )

            ctx = TurnContext(
                user=UserContext(oid, job.claims.username, frozenset(job.claims.roles)),
                conversation_id=conversation_id,
                turn_id=job.turn_id,
                input=job.input,
                client_tools=job.client_tools,
                pending_outputs=job.pending_outputs,
                correlation_id=correlation_id.get(),
            )
            outcome = await backend.run_turn(ctx, run.emit)
            if outcome.status == "paused":
                self.store.put(
                    PausedTurn(
                        job.turn_id,
                        oid,
                        conversation_id,
                        job.backend,
                        job.client_tools,
                        outcome.pending_outputs,
                        frozenset(outcome.client_call_ids),
                    )
                )
                if run.held_tool_calls is not None:
                    # A first turn has no `done` before this, so the client learns the
                    # conversation id here.
                    data = {**run.held_tool_calls.data, "conversation_id": conversation_id}
                    await run.queue.put(AgentEvent("client_tool_calls", data))
            elif outcome.status == "done":
                await run.emit(
                    AgentEvent(
                        "done",
                        {
                            "conversation_id": conversation_id,
                            "turn_id": job.turn_id,
                            "backend": job.backend,
                            "usage": outcome.usage,
                        },
                    )
                )
            # "failed": the loop has already emitted the error event.
        except Exception:
            logger.exception("Turn failed")
            await run.queue.put(GENERIC_ERROR)
        finally:
            await run.queue.put(None)

    async def _close(self, paused: PausedTurn, run: _Run) -> None:
        """Give the open function calls of an abandoned or expired turn an output."""
        try:
            backend = self._registry.get_backend(paused.backend)
            await backend.abandon(paused.conversation_id, paused.abandon_outputs())
        except Exception:
            logger.exception("Could not close the abandoned turn %s", paused.turn_id)
            return
        await run.emit(
            trace(
                "turn_abandoned",
                "api",
                f"closed unfinished turn {paused.turn_id}",
                turn_id=paused.turn_id,
            )
        )


def new_turn_id() -> str:
    return str(uuid.uuid4())
