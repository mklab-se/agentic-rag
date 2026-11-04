"""The hosted agent's handler with a fake model: event relay, outcome, caller check."""

import json

import httpx
import pytest
from voltrieve_agent.model import Completed, FunctionCall, TextDelta
from voltrieve_agent.tools import ServerTool

import main
from main import Runtime

OID = "11111111-2222-3333-4444-555555555555"

BODY = {
    "conversation_id": "conv_1",
    "turn_id": "turn_1",
    "input": "hello",
    "client_tools": [],
    "pending_outputs": [],
    "user": {"oid": "oid-anna", "username": "anna@example.com", "roles": ["TestDrive.Book"]},
    "correlation_id": "corr-1",
}


class ScriptedModel:
    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls = []

    async def stream(self, *, instructions, conversation, input, tools):
        self.calls.append({"conversation": conversation, "input": input, "tools": tools})
        for item in self.rounds.pop(0):
            yield item


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        lines = block.split("\n")
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


def client_for(runtime: Runtime) -> httpx.AsyncClient:
    host = main.create_host()
    main._runtime = runtime
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=host), base_url="http://agent")


@pytest.fixture(autouse=True)
def reset_runtime():
    yield
    main._runtime = None


async def invoke(runtime: Runtime, body=BODY, headers=None):
    async with client_for(runtime) as c:
        return await c.post("/invocations", json=body, headers=headers or {})


async def test_streams_events_then_outcome():
    model = ScriptedModel([TextDelta("Hi"), Completed({"total_tokens": 5})])
    r = await invoke(Runtime(model, [], allow_any_caller=True))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    types = [t for t, _ in events]
    assert types[-1] == "outcome" and "done" not in types
    assert [d["text"] for t, d in events if t == "delta"] == ["Hi"]
    assert events[-1][1] == {
        "status": "done",
        "pending_outputs": [],
        "client_call_ids": [],
        "usage": {"total_tokens": 5},
    }
    assert model.calls[0]["conversation"] == "conv_1"


async def test_client_tools_of_the_request_reach_the_model_and_pause_the_turn():
    tool = {"name": "read_file", "description": "Read", "parameters": {"type": "object"}}
    model = ScriptedModel([FunctionCall("call_1", "read_file", "{}"), Completed({})])
    r = await invoke(Runtime(model, [], allow_any_caller=True), {**BODY, "client_tools": [tool]})
    events = parse_sse(r.text)
    assert "read_file" in [t["name"] for t in model.calls[0]["tools"]]
    paused = [d for t, d in events if t == "client_tool_calls"]
    assert paused[0]["calls"] == [{"call_id": "call_1", "name": "read_file", "arguments": "{}"}]
    assert events[-1][1]["status"] == "paused"
    assert events[-1][1]["client_call_ids"] == ["call_1"]


async def test_continuation_sends_pending_outputs_before_client_results():
    pending = [{"type": "function_call_output", "call_id": "s1", "output": "stock 3"}]
    results = [{"type": "function_call_output", "call_id": "c1", "output": "hi"}]
    model = ScriptedModel([TextDelta("ok"), Completed({})])
    await invoke(Runtime(model, [], allow_any_caller=True), {**BODY, "input": results, "pending_outputs": pending})
    assert model.calls[0]["input"] == [*pending, *results]


async def test_user_roles_gate_server_tools():
    seen = []

    async def book(args, user):
        seen.append(user)
        return "booked"

    tool = ServerTool("book", "Book", {"type": "object"}, book, required_role="TestDrive.Book")
    model = ScriptedModel(
        [FunctionCall("c1", "book", "{}"), Completed({})], [TextDelta("done"), Completed({})]
    )
    body = {**BODY, "user": {**BODY["user"], "roles": []}}
    r = await invoke(Runtime(model, [tool], allow_any_caller=True), body)
    assert seen == []
    assert any(d["step"] == "authorization_denied" for t, d in parse_sse(r.text) if t == "trace")

    model = ScriptedModel(
        [FunctionCall("c1", "book", "{}"), Completed({})], [TextDelta("done"), Completed({})]
    )
    await invoke(Runtime(model, [tool], allow_any_caller=True), BODY)
    assert seen[0].oid == "oid-anna" and "TestDrive.Book" in seen[0].roles


async def test_model_failure_is_an_error_event_and_a_failed_outcome():
    class Broken:
        def stream(self, **kwargs):
            raise RuntimeError("boom")

    events = parse_sse((await invoke(Runtime(Broken(), [], allow_any_caller=True))).text)
    assert [t for t, _ in events if t == "error"] == ["error"]
    assert events[-1][1]["status"] == "failed"


@pytest.mark.parametrize("body", [{"input": "x"}, {**BODY, "input": 3}, {**BODY, "user": {}}])
async def test_malformed_body_is_400(body):
    r = await invoke(Runtime(ScriptedModel(), [], allow_any_caller=True), body)
    assert r.status_code == 400


def subject(oid):
    return {"x-ms-original-subject": f'oid="{oid}", tid="t", idtype="servicePrincipal"'}


async def test_caller_check_refuses_other_callers_and_allows_the_api():
    runtime = Runtime(ScriptedModel([TextDelta("a"), Completed({})]), [], OID)
    assert (await invoke(runtime)).status_code == 403
    assert (await invoke(runtime, headers=subject("not-a-guid"))).status_code == 403
    other = "99999999-2222-3333-4444-555555555555"
    assert (await invoke(runtime, headers=subject(other))).status_code == 403
    ok = await invoke(runtime, headers=subject(OID.upper()))
    assert ok.status_code == 200


async def test_check_fails_closed_without_an_allowed_caller():
    model = ScriptedModel([TextDelta("a"), Completed({})])
    assert (await invoke(Runtime(model, []), headers=subject(OID))).status_code == 403
    assert (await invoke(Runtime(model, [], ""), headers=subject(OID))).status_code == 403
    assert (await invoke(Runtime(model, [], "   "))).status_code == 403


async def test_allow_any_caller_is_an_explicit_opt_in():
    model = ScriptedModel([TextDelta("a"), Completed({})])
    assert (await invoke(Runtime(model, [], allow_any_caller=True))).status_code == 200


async def test_line_separators_in_text_survive_as_escapes():
    text = "a\u2028b\u2029c\u0085d"
    r = await invoke(Runtime(ScriptedModel([TextDelta(text), Completed({})]), [], allow_any_caller=True))
    for ch in "\u2028\u2029\u0085":
        assert ch not in r.text
    assert [d["text"] for t, d in parse_sse(r.text) if t == "delta"] == [text]
