"""Backend C: the SSE relay to the hosted agent, session reuse and failure handling."""

import json

import httpx
import pytest
import respx
from voltrieve_agent.tools import ClientTool, UserContext

from app.backends import BackendRegistry
from app.backends.base import BackendUnavailable, TurnContext
from app.backends.hosted import INVOCATIONS_SCOPE, HostedBackend, build_hosted_backend
from app.main import create_app
from app.settings import Settings
from app.turns import TurnStore
from tests.conftest import parse_sse
from tests.test_loop_backend import FakeOpenAI

ENDPOINT = "https://acct.services.ai.azure.com/api/projects/voltrieve"
INVOKE_URL = f"{ENDPOINT}/agents/voltrieve-hosted/endpoint/protocols/invocations"
TOOL = ClientTool("read_file", "Read", {"type": "object"})


def sse(*events: tuple[str, dict], comment: bool = False) -> bytes:
    text = ": keep-alive\n\n" if comment else ""
    for kind, data in events:
        text += f"event: {kind}\ndata: {json.dumps(data)}\n\n"
    return text.encode()


def outcome(status="done", pending=(), call_ids=(), usage=None):
    return (
        "outcome",
        {
            "status": status,
            "pending_outputs": list(pending),
            "client_call_ids": list(call_ids),
            "usage": usage or {},
        },
    )


def make_backend(client: httpx.AsyncClient, openai=None) -> HostedBackend:
    scopes = []

    async def token(scope: str) -> str:
        scopes.append(scope)
        return "tok"

    backend = HostedBackend(
        openai or FakeOpenAI(), client, token, ENDPOINT, "voltrieve-hosted"
    )
    backend.scopes = scopes
    return backend


def ctx(conversation_id="conv_real", input_="hi", **kwargs) -> TurnContext:
    return TurnContext(
        user=UserContext("oid-anna", "anna@example.com", frozenset({"Chat.User"})),
        conversation_id=conversation_id,
        turn_id="turn_1",
        input=input_,
        correlation_id="corr-1",
        **kwargs,
    )


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@respx.mock
async def test_relays_events_one_to_one_and_returns_the_outcome(http):
    trace = ("trace", {"step": "model_called", "component": "model", "detail": "iteration 1"})
    delta = ("delta", {"text": "Hej"})
    route = respx.post(INVOKE_URL).respond(
        200, content=sse(trace, delta, outcome(usage={"total_tokens": 7}), comment=True)
    )
    backend = make_backend(http)
    emitted = []

    async def emit(event):
        emitted.append((event.type, event.data))

    result = await backend.run_turn(ctx(client_tools=[TOOL]), emit)

    assert emitted == [trace, delta]  # the outcome is consumed, keep-alives ignored
    assert (result.status, result.usage) == ("done", {"total_tokens": 7})
    request = route.calls.last.request
    assert request.url.params["api-version"] == "v1"
    assert "agent_session_id" not in request.url.params
    assert request.headers["authorization"] == "Bearer tok"
    assert backend.scopes == [INVOCATIONS_SCOPE] == ["https://ai.azure.com/.default"]
    assert json.loads(request.content) == {
        "conversation_id": "conv_real",
        "turn_id": "turn_1",
        "input": "hi",
        "client_tools": [{"name": "read_file", "description": "Read", "parameters": {"type": "object"}}],
        "pending_outputs": [],
        "user": {"oid": "oid-anna", "username": "anna@example.com", "roles": ["Chat.User"]},
        "correlation_id": "corr-1",
    }


@respx.mock
async def test_paused_outcome_carries_pending_outputs_and_call_ids(http):
    pending = [{"type": "function_call_output", "call_id": "s1", "output": "3 in stock"}]
    respx.post(INVOKE_URL).respond(
        200, content=sse(outcome("paused", pending, ["call_9"], {"total_tokens": 3}))
    )

    async def emit(event):
        pass

    result = await make_backend(http).run_turn(ctx(), emit)
    assert (result.status, result.pending_outputs, result.client_call_ids) == ("paused", pending, ["call_9"])


@respx.mock
async def test_continuation_resends_tools_and_pending_outputs_and_reuses_the_session(http):
    route = respx.post(INVOKE_URL).respond(
        200, content=sse(outcome()), headers={"x-agent-session-id": "sess-1"}
    )
    backend = make_backend(http)

    async def emit(event):
        pass

    await backend.run_turn(ctx(), emit)
    results = [{"type": "function_call_output", "call_id": "c1", "output": "hi"}]
    pending = [{"type": "function_call_output", "call_id": "s1", "output": "x"}]
    await backend.run_turn(ctx(input_=results, client_tools=[TOOL], pending_outputs=pending), emit)
    await backend.run_turn(ctx(conversation_id="conv_other"), emit)

    first, second, other = (c.request for c in route.calls)
    assert "agent_session_id" not in first.url.params
    assert second.url.params["agent_session_id"] == "sess-1"
    body = json.loads(second.content)
    assert body["input"] == results and body["pending_outputs"] == pending
    assert [t["name"] for t in body["client_tools"]] == ["read_file"]
    assert "agent_session_id" not in other.url.params  # sessions are per conversation


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, text="secret detail from the agent"),
        httpx.Response(500, text="traceback"),
        httpx.Response(200, content=sse(("delta", {"text": "partial"}))),  # no outcome
        httpx.ConnectError("down"),
    ],
)
async def test_failures_become_a_generic_error_event_and_a_failed_outcome(http, response):
    respx.post(INVOKE_URL).mock(side_effect=[response])
    emitted = []

    async def emit(event):
        emitted.append(event)

    result = await make_backend(http).run_turn(ctx(), emit)
    assert result.status == "failed"
    error = [e for e in emitted if e.type == "error"]
    assert len(error) == 1 and error[0].data["code"] == "hosted_agent_error"
    assert "secret" not in json.dumps(error[0].data) and "traceback" not in json.dumps(error[0].data)


async def test_conversation_methods_use_foundry_conversations(http):
    openai = FakeOpenAI()
    backend = make_backend(http, openai)
    assert await backend.create_conversation("oid-anna") == "conv_real"
    assert await backend.get_conversation_owner("conv_real") == "oid-anna"
    await backend.abandon("conv_real", [{"type": "function_call_output", "call_id": "c", "output": "x"}])
    assert len(openai.conversations.items.created) == 1


@respx.mock
async def test_client_tool_round_trip_through_the_api_looks_like_backend_b(validator, auth, http):
    call = {"call_id": "call_9", "name": "read_file", "arguments": '{"path": "a"}'}
    def first(request: httpx.Request) -> httpx.Response:
        turn_id = json.loads(request.content)["turn_id"]  # the agent echoes the turn id it got
        return httpx.Response(
            200,
            content=sse(
                ("client_tool_calls", {"turn_id": turn_id, "calls": [call]}),
                outcome("paused", [], ["call_9"], {"total_tokens": 3}),
            ),
            headers={"x-agent-session-id": "sess-1"},
        )

    second = httpx.Response(
        200, content=sse(("delta", {"text": "It says hi."}), outcome(usage={"total_tokens": 4}))
    )
    respx.post(INVOKE_URL).mock(side_effect=[first, second])
    backend = make_backend(http)
    settings = Settings()
    app = create_app(settings, validator, BackendRegistry(settings, {"hosted": lambda s: backend}), TurnStore())
    tool = {"name": "read_file", "description": "Read", "parameters": {"type": "object"}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        headers = {**auth, "X-Agent-Backend": "hosted"}
        r = await c.post("/chat", headers=headers, json={"message": "read a", "client_tools": [tool]})
        events = parse_sse(r.text)
        paused = events[-1][1]
        assert events[-1][0] == "client_tool_calls"
        assert set(paused) == {"turn_id", "conversation_id", "calls"}
        assert paused["calls"] == [call]
        r = await c.post(
            "/chat/tool-results",
            headers=headers,
            json={
                "conversation_id": paused["conversation_id"],
                "turn_id": paused["turn_id"],
                "results": [{"call_id": "call_9", "output": "hi"}],
            },
        )
        events = parse_sse(r.text)
    assert [d["text"] for t, d in events if t == "delta"] == ["It says hi."]
    assert events[-1][0] == "done" and events[-1][1]["backend"] == "hosted"
    assert events[-1][1]["usage"] == {"total_tokens": 7}


def test_unconfigured_deployment_is_unavailable():
    with pytest.raises(BackendUnavailable):
        build_hosted_backend(Settings(foundry_project_endpoint=""))
