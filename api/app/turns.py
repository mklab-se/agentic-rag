"""Turn state and the runner that drives a backend turn into an SSE stream.

State lives in this process: `TurnStore` is a dict, so the API runs with maxReplicas 1 and
a restart loses paused turns. Nothing durable is lost: conversation ownership is stored in
Foundry with the conversation, and a conversation touched for the first time by this
process (or left dirty by an abandoned, expired or failed turn) is repaired before use,
which gives every open function call an output.
"""

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from voltrieve_agent.events import AgentEvent, trace
from voltrieve_agent.tools import ClientTool, UserContext

from app.auth import Claims
from app.backends import BackendRegistry
from app.backends.base import TurnContext
from app.logging_setup import bind_log_context, correlation_id
from app.sse import KEEPALIVE, format_event

logger = logging.getLogger(__name__)

TURN_TTL_SECONDS = 15 * 60
MAX_CONVERSATIONS = 1000
# Container Apps closes connections that are idle for 240 seconds.
KEEPALIVE_SECONDS = 15.0
ABANDONED_OUTPUT = "the client did not return a result"
GENERIC_ERROR = AgentEvent(
    "error", {"code": "internal_error", "message": "The request could not be completed."}
)


def merge_usage(total: dict, more: dict) -> dict:
    """Sum two usage dicts, descending into nested ones (token detail breakdowns)."""
    merged = dict(total)
    for key, value in more.items():
        if isinstance(value, dict):
            merged[key] = merge_usage(merged.get(key) or {}, value)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            merged[key] = merged.get(key, 0) + value
    return merged


@dataclass
class PausedTurn:
    turn_id: str
    oid: str
    conversation_id: str
    backend: str
    client_tools: list[ClientTool]
    pending_outputs: list[dict]
    expected_call_ids: frozenset[str]
    usage: dict = field(default_factory=dict)
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


@dataclass
class _Conversation:
    oid: str
    dirty: bool


class TurnStore:
    def __init__(
        self,
        ttl: float = TURN_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_conversations: int = MAX_CONVERSATIONS,
    ):
        self._ttl = ttl
        self._clock = clock
        self._max_conversations = max_conversations
        self._paused: dict[str, PausedTurn] = {}
        self._paused_by_conversation: dict[str, str] = {}
        # A bounded LRU. Foundry holds the truth; a miss costs one lookup and a repair.
        self._conversations: OrderedDict[str, _Conversation] = OrderedDict()

    def register_conversation(self, conversation_id: str, oid: str, dirty: bool = False) -> None:
        self._conversations[conversation_id] = _Conversation(oid, dirty)
        self._conversations.move_to_end(conversation_id)
        while len(self._conversations) > self._max_conversations:
            self._conversations.popitem(last=False)

    def conversation_owner(self, conversation_id: str) -> str | None:
        entry = self._conversations.get(conversation_id)
        if entry is None:
            return None
        self._conversations.move_to_end(conversation_id)
        return entry.oid

    def mark_dirty(self, conversation_id: str) -> None:
        if conversation_id in self._conversations:
            self._conversations[conversation_id].dirty = True

    def mark_clean(self, conversation_id: str) -> None:
        if conversation_id in self._conversations:
            self._conversations[conversation_id].dirty = False

    def needs_repair(self, conversation_id: str) -> bool:
        entry = self._conversations.get(conversation_id)
        return entry is not None and entry.dirty

    def put(self, paused: PausedTurn) -> None:
        self.evict_expired()
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

    def evict_expired(self) -> int:
        """Drop expired pauses. Their conversations are left dirty, so the next touch repairs."""
        expired = [p for p in self._paused.values() if self.is_expired(p)]
        for paused in expired:
            self.remove(paused.turn_id)
            self.mark_dirty(paused.conversation_id)
        return len(expired)


@dataclass
class Job:
    claims: Claims
    backend: str
    conversation_id: str | None  # None: create one
    turn_id: str
    input: str | list[dict]
    client_tools: list[ClientTool] = field(default_factory=list)
    pending_outputs: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # of the earlier parts of this turn
    continuation: bool = False
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
        self._running: dict[str, _Run] = {}  # conversation id -> its running turn

    def is_running(self, conversation_id: str) -> bool:
        return conversation_id in self._running

    def start(self, job: Job) -> AsyncIterator[bytes]:
        """Start the turn in the background and return its SSE byte stream.

        The turn is not tied to the response: if the client disconnects, it still runs to
        its end, so the conversation is never left with a function call without output.
        """
        run = _Run()
        # A turn_expired job runs nothing, and its conversation id is unvalidated client input.
        if job.conversation_id is not None and not job.turn_expired:
            self._running[job.conversation_id] = run
        task = asyncio.create_task(self._execute(run, job, correlation_id.get()))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return self._drain(run)

    async def drain(self, timeout: float = 20.0) -> None:
        """Wait for running turns, for shutdown."""
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=timeout)

    @staticmethod
    async def _drain(run: _Run) -> AsyncIterator[bytes]:
        while True:
            try:
                event = await asyncio.wait_for(run.queue.get(), KEEPALIVE_SECONDS)
            except TimeoutError:
                yield KEEPALIVE
                continue
            if event is None:
                return
            yield format_event(event)

    def _release(self, conversation_id: str | None, run: _Run) -> None:
        if conversation_id is not None and self._running.get(conversation_id) is run:
            del self._running[conversation_id]

    async def _execute(self, run: _Run, job: Job, cid: str) -> None:
        correlation_id.set(cid)
        oid = job.claims.oid
        conversation_id = job.conversation_id
        bind_log_context(
            user_oid=oid,
            backend=job.backend,
            turn_id=job.turn_id,
            conversation_id=conversation_id or "",
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
            await run.emit(trace("backend_selected", "api", job.backend, backend=job.backend))
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
            if conversation_id and self.store.needs_repair(conversation_id):
                try:
                    await backend.repair(conversation_id)
                except Exception:
                    logger.exception("Conversation repair failed")
                    self.store.mark_dirty(conversation_id)
                    await run.emit(
                        AgentEvent(
                            "error",
                            {
                                "code": "conversation_recovery_failed",
                                "message": "The conversation could not be recovered. "
                                "Start a new conversation.",
                            },
                        )
                    )
                    return
                self.store.mark_clean(conversation_id)
                await run.emit(trace("conversation_repaired", "api", conversation_id))

            if conversation_id is None:
                conversation_id = await backend.create_conversation(oid)
                self.store.register_conversation(conversation_id, oid)
                self._running[conversation_id] = run
                bind_log_context(conversation_id=conversation_id)
                await run.emit(trace("conversation_created", "api", conversation_id))

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
            usage = merge_usage(job.usage, outcome.usage)
            if outcome.status == "paused":
                # No await between releasing the conversation and storing the pause, so a
                # fast continuation never meets a "running" turn.
                self._release(conversation_id, run)
                self.store.put(
                    PausedTurn(
                        job.turn_id,
                        oid,
                        conversation_id,
                        job.backend,
                        job.client_tools,
                        outcome.pending_outputs,
                        frozenset(outcome.client_call_ids),
                        usage,
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
                            "usage": usage,
                        },
                    )
                )
            elif job.continuation:
                # "failed": the loop has already emitted the error event. The results may
                # not have reached the conversation, so check it before its next use.
                self.store.mark_dirty(conversation_id)
        except Exception:
            logger.exception("Turn failed")
            if job.continuation and conversation_id:
                self.store.mark_dirty(conversation_id)
            await run.queue.put(GENERIC_ERROR)
        finally:
            self._release(job.conversation_id, run)
            self._release(conversation_id, run)
            await run.queue.put(None)

    async def _close(self, paused: PausedTurn, run: _Run) -> None:
        """Give the open function calls of an abandoned or expired turn an output."""
        try:
            backend = self._registry.get_backend(paused.backend)
            await backend.abandon(paused.conversation_id, paused.abandon_outputs())
        except Exception:
            logger.exception("Could not close the abandoned turn %s", paused.turn_id)
            self.store.mark_dirty(paused.conversation_id)
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
