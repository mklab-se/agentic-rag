import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.auth import AuthError, Claims
from app.backends.base import BackendUnavailable
from app.logging_setup import correlation_id
from app.schemas import (
    MAX_CLIENT_TOOLS_BYTES,
    ChatRequest,
    ToolResultsRequest,
    to_client_tools,
)
from app.turns import Job, new_turn_id

SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


async def authenticate(request: Request, authorization: str | None = Header(default=None)) -> Claims:
    try:
        return await request.app.state.validator.validate(authorization)
    except AuthError as exc:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        raise HTTPException(exc.status_code, exc.detail, headers=headers) from exc


def _check_client_tools(body: ChatRequest, server_tool_names: frozenset[str]) -> None:
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
        body: ChatRequest,
        request: Request,
        claims: Claims = Depends(authenticate),
        x_agent_backend: str | None = Header(default=None),
    ):
        state = request.app.state
        _check_client_tools(body, state.server_tool_names)
        name = x_agent_backend or state.settings.agent_backend
        try:
            state.registry.get_backend(name)
        except BackendUnavailable as exc:
            raise HTTPException(400, str(exc)) from exc

        stale = None
        if body.conversation_id is not None:
            # The same answer for unknown and foreign ids, so ids cannot be probed.
            if state.store.conversation_owner(body.conversation_id) != claims.oid:
                raise HTTPException(403, "Unknown conversation")
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
        body: ToolResultsRequest, request: Request, claims: Claims = Depends(authenticate)
    ):
        store = request.app.state.store
        paused = store.get(body.turn_id)
        if paused is None:
            # Unknown, or the API restarted: nothing to close, only tell the client.
            return _stream(
                request,
                Job(claims, request.app.state.settings.agent_backend, body.conversation_id,
                    body.turn_id, "", turn_expired=True),
            )
        if paused.oid != claims.oid:
            raise HTTPException(403, "This turn belongs to another user")
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
            ),
        )

    return router
