import json
import logging

from pydantic import BaseModel, ValidationError
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.auth import AuthError, Claims
from app.backends import BACKEND_NAMES
from app.backends.base import BackendUnavailable
from app.logging_setup import correlation_id
from app.schemas import (
    MAX_CLIENT_TOOLS_BYTES,
    ChatRequest,
    ToolResultsRequest,
    to_client_tools,
)
from app.turns import Job, new_turn_id

logger = logging.getLogger(__name__)

SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


async def authenticate(request: Request, authorization: str | None = Header(default=None)) -> Claims:
    try:
        return await request.app.state.validator.validate(authorization)
    except AuthError as exc:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        raise HTTPException(exc.status_code, exc.detail, headers=headers) from exc


MAX_SCHEMA_DEPTH = 32


def _depth(value) -> int:
    """Nesting depth of parsed JSON, computed without recursion."""
    deepest = 0
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict | list):
            deepest = max(deepest, depth)
            if deepest > MAX_SCHEMA_DEPTH:
                return deepest
            stack.extend((child, depth + 1) for child in (node.values() if isinstance(node, dict) else node))
    return deepest


REF_KEYWORDS = ("$ref", "$dynamicRef")


def _has_ref(value) -> bool:
    """Whether a reference keyword appears anywhere in parsed JSON (iterative, like _depth)."""
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if any(k in node for k in REF_KEYWORDS):
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def json_body(model: type[BaseModel]):
    """Parse the body by hand: FastAPI turns a RecursionError from deeply nested JSON into a
    400 or 500, and clients should get a 422."""

    async def parse(request: Request) -> BaseModel:
        try:
            return model.model_validate(json.loads(await request.body()))
        except RecursionError as exc:
            raise HTTPException(422, "JSON is nested too deeply") from exc
        except ValidationError as exc:
            raise HTTPException(422, json.loads(exc.json(include_url=False, include_context=False))) from exc
        except ValueError as exc:
            raise HTTPException(422, "Invalid JSON") from exc

    return parse


def _check_client_tools(body: ChatRequest, server_tool_names: frozenset[str]) -> None:
    for tool in body.client_tools:
        if _depth(tool.parameters) > MAX_SCHEMA_DEPTH:
            raise HTTPException(422, f"client tool '{tool.name}' schema is nested too deeply")
        if _has_ref(tool.parameters):
            # A reference could make the validator fetch a URL of the client's choosing.
            raise HTTPException(422, f"client tool '{tool.name}' schema must not use $ref")
    names = [t.name for t in body.client_tools]
    if len(set(names)) != len(names):
        raise HTTPException(422, "client_tools has duplicate names")
    clashes = sorted(set(names) & server_tool_names)
    if clashes:
        raise HTTPException(422, f"client_tools collide with server tools: {', '.join(clashes)}")
    size = len(json.dumps([t.model_dump() for t in body.client_tools]).encode())
    if size > MAX_CLIENT_TOOLS_BYTES:
        raise HTTPException(422, f"client_tools exceed {MAX_CLIENT_TOOLS_BYTES} bytes")
    for tool in body.client_tools:
        try:
            Draft202012Validator.check_schema(tool.parameters)
        except SchemaError as exc:
            raise HTTPException(422, f"client tool '{tool.name}' has an invalid schema") from exc


async def _check_owner(state, backend, conversation_id: str, oid: str) -> None:
    """Refuse conversations of other users with the same answer as unknown ones, so ids
    cannot be probed. Foundry holds the owner; the in-process map is only a cache."""
    owner = state.store.conversation_owner(conversation_id)
    if owner is None:
        try:
            owner = await backend.get_conversation_owner(conversation_id)
        except Exception as exc:
            # Foundry is down or failing: that is not "unknown conversation".
            logger.warning("Could not look up the owner of %s", conversation_id, exc_info=True)
            raise HTTPException(503, "The conversation store is unavailable. Try again later.") from exc
        if owner == oid:
            # First touch in this process: the conversation is repaired before it is used.
            state.store.register_conversation(conversation_id, oid, dirty=True)
    if owner != oid:
        raise HTTPException(403, "Unknown conversation")


def _requested_backend(request: Request, header: str | None) -> str:
    """The backend the client asked for when it names a real one, else the default."""
    return header if header in BACKEND_NAMES else request.app.state.settings.agent_backend


def _stream(request: Request, job: Job) -> StreamingResponse:
    cid = correlation_id.get()
    return StreamingResponse(
        request.app.state.turns.start(job),
        media_type="text/event-stream",
        headers={**SSE_HEADERS, "X-Correlation-Id": cid},
    )


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @router.post("/chat")
    async def chat(
        request: Request,
        claims: Claims = Depends(authenticate),
        body: ChatRequest = Depends(json_body(ChatRequest)),
        x_agent_backend: str | None = Header(default=None),
    ):
        state = request.app.state
        _check_client_tools(body, state.server_tool_names)
        name = x_agent_backend or state.settings.agent_backend
        try:
            backend = state.registry.get_backend(name)
        except BackendUnavailable as exc:
            raise HTTPException(400, str(exc)) from exc

        stale = None
        if body.conversation_id is not None:
            await _check_owner(state, backend, body.conversation_id, claims.oid)
            if state.turns.is_running(body.conversation_id):
                raise HTTPException(409, "turn_in_progress")
            stale = state.store.remove_for_conversation(body.conversation_id)
        return _stream(
            request,
            Job(
                claims,
                name,
                body.conversation_id,
                new_turn_id(),
                body.message,
                to_client_tools(body.client_tools),
                stale=stale,
            ),
        )

    @router.post("/chat/tool-results")
    async def tool_results(
        request: Request,
        claims: Claims = Depends(authenticate),
        body: ToolResultsRequest = Depends(json_body(ToolResultsRequest)),
        x_agent_backend: str | None = Header(default=None),
    ):
        store = request.app.state.store
        paused = store.get(body.turn_id)
        if paused is None or paused.oid != claims.oid:
            # Unknown, the API restarted, or another user's turn: all get the same answer, so
            # turn ids cannot be probed. Nothing to close, only tell the client.
            return _stream(
                request,
                Job(claims, _requested_backend(request, x_agent_backend), body.conversation_id,
                    body.turn_id, "", turn_expired=True),
            )
        if paused.conversation_id != body.conversation_id:
            raise HTTPException(422, "conversation_id does not match the turn")
        if store.is_expired(paused):
            store.remove(body.turn_id)
            return _stream(
                request,
                Job(claims, paused.backend, paused.conversation_id, paused.turn_id, "",
                    turn_expired=True, expired=paused),
            )
        call_ids = [r.call_id for r in body.results]
        if len(set(call_ids)) != len(call_ids) or set(call_ids) != paused.expected_call_ids:
            raise HTTPException(
                422,
                "results must contain exactly one result for each pending call: "
                + ", ".join(sorted(paused.expected_call_ids)),
            )
        if request.app.state.turns.is_running(paused.conversation_id):
            raise HTTPException(409, "turn_in_progress")
        store.remove(body.turn_id)
        items = [
            {"type": "function_call_output", "call_id": r.call_id, "output": r.output_text()}
            for r in body.results
        ]
        return _stream(
            request,
            Job(
                claims,
                paused.backend,
                paused.conversation_id,
                paused.turn_id,
                items,
                paused.client_tools,
                paused.pending_outputs,
                usage=paused.usage,
            ),
        )

    return router
