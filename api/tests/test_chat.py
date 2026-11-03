import json

import pytest

from tests.conftest import answer, pause, parse_sse

TOOL = {"name": "read_file", "description": "Read", "parameters": {"type": "object"}}


async def chat(client, auth, body=None, **headers):
    return await client.post(
        "/chat", json=body or {"message": "hi"}, headers={**auth, **headers}
    )


async def test_healthz_needs_no_auth(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_no_token_is_401(client):
    r = await client.post("/chat", json={"message": "hi"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


async def test_no_role_is_403(client, make_token):
    r = await chat(client, {"Authorization": f"Bearer {make_token(roles=[])}"})
    assert r.status_code == 403


async def test_no_scope_is_403(client, make_token):
    r = await chat(client, {"Authorization": f"Bearer {make_token(scp='')}"})
    assert r.status_code == 403


async def test_sse_framing_and_order(client, auth, backend):
    backend.script = [answer("Hello", {"total_tokens": 7})]
    r = await chat(client, auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    types = [t for t, _ in events]
    assert types == ["trace", "trace", "trace", "trace", "delta", "done"]
    steps = [d["step"] for t, d in events if t == "trace"]
    assert steps[:2] == ["token_validated", "backend_selected"]
    token_trace = events[0][1]
    assert token_trace["roles"] == ["Chat.User"] and "elapsed_ms" in token_trace
    assert events[1][1]["backend"] == "loop"
    done = events[-1][1]
    assert done["conversation_id"] == "conv_1" and done["backend"] == "loop"
    assert done["usage"] == {"total_tokens": 7}
    assert done["turn_id"] == backend.contexts[0].turn_id
    for t, d in events:
        if t == "trace":
            assert {"step", "component", "detail", "elapsed_ms"} <= d.keys()


async def test_second_turn_reuses_conversation(client, auth, backend):
    backend.script = [answer(), answer()]
    first = parse_sse((await chat(client, auth)).text)[-1][1]
    second = parse_sse(
        (await chat(client, auth, {"message": "again", "conversation_id": first["conversation_id"]})).text
    )[-1][1]
    assert second["conversation_id"] == first["conversation_id"] and backend.created == 1


async def test_foreign_or_unknown_conversation_is_403(client, auth, backend, make_token):
    backend.script = [answer()]
    conv = parse_sse((await chat(client, auth)).text)[-1][1]["conversation_id"]
    other = {"Authorization": f"Bearer {make_token(oid='oid-bob')}"}
    assert (await chat(client, other, {"message": "x", "conversation_id": conv})).status_code == 403
    assert (await chat(client, auth, {"message": "x", "conversation_id": "conv_nope"})).status_code == 403


async def test_pause_then_continue(client, auth, backend):
    backend.script = [
        pause(("c1", "c2"), pending=[{"type": "function_call_output", "call_id": "s1", "output": "o"}]),
        answer("Done"),
    ]
    r = await chat(client, auth, {"message": "go", "client_tools": [TOOL]})
    events = parse_sse(r.text)
    assert events[-1][0] == "client_tool_calls"
    paused = events[-1][1]
    assert paused["conversation_id"] == "conv_1" and paused["turn_id"]
    assert [c["call_id"] for c in paused["calls"]] == ["c1", "c2"]
    assert "done" not in [t for t, _ in events]

    r2 = await client.post(
        "/chat/tool-results",
        headers=auth,
        json={
            "conversation_id": paused["conversation_id"],
            "turn_id": paused["turn_id"],
            "results": [
                {"call_id": "c2", "output": {"x": 1}},
                {"call_id": "c1", "output": "text"},
            ],
        },
    )
    events2 = parse_sse(r2.text)
    assert events2[-1][0] == "done" and events2[-1][1]["turn_id"] == paused["turn_id"]
    ctx = backend.contexts[1]
    assert ctx.turn_id == paused["turn_id"]
    assert [i["call_id"] for i in ctx.input] == ["c2", "c1"]
    assert ctx.input[0]["output"] == '{"x": 1}'
    assert ctx.pending_outputs[0]["call_id"] == "s1"
    assert [t.name for t in ctx.client_tools] == ["read_file"]


def results_body(paused, *call_ids):
    return {
        "conversation_id": paused["conversation_id"],
        "turn_id": paused["turn_id"],
        "results": [{"call_id": c, "output": "x"} for c in call_ids],
    }


async def paused_turn(client, auth, backend, **kw):
    backend.script.append(pause(**kw))
    return parse_sse((await chat(client, auth, {"message": "go", "client_tools": [TOOL]})).text)[-1][1]


async def test_mismatched_call_ids_are_422_and_turn_survives(client, auth, backend):
    paused = await paused_turn(client, auth, backend)
    for ids in [("other",), ("call_1", "extra"), ("call_1", "call_1")]:
        r = await client.post("/chat/tool-results", headers=auth, json=results_body(paused, *ids))
        assert r.status_code == 422
    backend.script.append(answer())
    r = await client.post("/chat/tool-results", headers=auth, json=results_body(paused, "call_1"))
    assert parse_sse(r.text)[-1][0] == "done"


async def test_foreign_oid_on_continue_is_403(client, auth, backend, make_token):
    paused = await paused_turn(client, auth, backend)
    other = {"Authorization": f"Bearer {make_token(oid='oid-bob')}"}
    r = await client.post("/chat/tool-results", headers=other, json=results_body(paused, "call_1"))
    assert r.status_code == 403 and len(backend.contexts) == 1


async def test_unknown_turn_is_turn_expired_stream(client, auth):
    r = await client.post(
        "/chat/tool-results",
        headers=auth,
        json={"conversation_id": "conv_1", "turn_id": "nope", "results": [{"call_id": "a", "output": "x"}]},
    )
    events = parse_sse(r.text)
    assert r.status_code == 200 and events[-1] == (
        "error",
        {"code": "turn_expired", "message": "This turn is no longer available. Send the message again."},
    )
    assert events[0][1]["step"] == "token_validated"


async def test_expired_turn_is_closed_and_reported(client, auth, backend, clock):
    paused = await paused_turn(
        client, auth, backend, pending=[{"type": "function_call_output", "call_id": "s", "output": "o"}]
    )
    clock.now += 15 * 60 + 1
    r = await client.post("/chat/tool-results", headers=auth, json=results_body(paused, "call_1"))
    assert parse_sse(r.text)[-1][1]["code"] == "turn_expired"
    conv, outputs = backend.abandoned[0]
    assert conv == "conv_1"
    assert [o["call_id"] for o in outputs] == ["s", "call_1"]
    assert outputs[1]["output"] == "the client did not return a result"
    assert len(backend.contexts) == 1


async def test_new_message_on_paused_conversation_closes_it_first(client, auth, backend):
    paused = await paused_turn(
        client, auth, backend, pending=[{"type": "function_call_output", "call_id": "s", "output": "o"}]
    )
    backend.script.append(answer())
    r = await chat(client, auth, {"message": "never mind", "conversation_id": paused["conversation_id"]})
    events = parse_sse(r.text)
    assert events[-1][0] == "done"
    assert [o["call_id"] for o in backend.abandoned[0][1]] == ["s", "call_1"]
    # The old turn is gone.
    r = await client.post("/chat/tool-results", headers=auth, json=results_body(paused, "call_1"))
    assert parse_sse(r.text)[-1][1]["code"] == "turn_expired"


async def test_expired_pause_closed_when_conversation_touched(client, auth, backend, clock):
    paused = await paused_turn(client, auth, backend)
    clock.now += 3600
    backend.script.append(answer())
    await chat(client, auth, {"message": "hello again", "conversation_id": paused["conversation_id"]})
    assert backend.abandoned and backend.abandoned[0][0] == "conv_1"


async def test_backend_exception_gives_generic_error(client, auth, backend):
    async def boom(ctx, emit):
        raise RuntimeError("secret internal detail")

    backend.script = [boom]
    events = parse_sse((await chat(client, auth)).text)
    assert events[-1] == ("error", {"code": "internal_error", "message": "The request could not be completed."})
    assert "secret" not in json.dumps(events)


async def test_disconnect_does_not_stop_the_turn(app, auth, backend):
    import asyncio

    release = asyncio.Event()

    async def slow(ctx, emit):
        await release.wait()
        return await pause()(ctx, emit)

    backend.script = [slow]
    from app.turns import Job
    from app.auth import Claims

    stream = app.state.turns.start(
        Job(Claims("oid-anna", "a", "cli", ["Chat.User"]), "loop", None, "t1", "hi", [])
    )
    await anext(stream)  # first event, then the client goes away
    await stream.aclose()
    release.set()
    for _ in range(50):
        if app.state.store.get("t1"):
            break
        await asyncio.sleep(0.01)
    assert app.state.store.get("t1") is not None


@pytest.mark.parametrize(
    "tools",
    [
        [{**TOOL, "name": "search_voltrieve_docs"}],
        [{**TOOL, "name": "bad name!"}],
        [TOOL, TOOL],
        [{**TOOL, "name": f"t{i}"} for i in range(17)],
        [{**TOOL, "description": "x" * 1500, "name": f"t{i}"} for i in range(12)],
        [{**TOOL, "parameters": {"type": "nonsense"}}],
    ],
)
async def test_bad_client_tools_are_422(client, auth, backend, tools):
    r = await chat(client, auth, {"message": "hi", "client_tools": tools})
    assert r.status_code == 422 and not backend.contexts


async def test_oversized_body_is_413(client, auth):
    r = await chat(client, auth, {"message": "x" * 70_000})
    assert r.status_code == 413


async def test_unknown_and_unconfigured_backend_is_400(client, auth):
    r = await client.post(
        "/chat", json={"message": "hi"}, headers={**auth, "X-Agent-Backend": "nonsense"}
    )
    assert r.status_code == 400 and "Unknown backend" in r.json()["detail"]
    r = await client.post(
        "/chat", json={"message": "hi"}, headers={**auth, "X-Agent-Backend": "prompt"}
    )
    assert r.status_code == 400 and "not configured" in r.json()["detail"]


async def test_cors(client):
    ok = await client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-agent-backend",
        },
    )
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = await client.options(
        "/chat",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


async def test_correlation_id(client, auth, backend):
    backend.script = [answer(), answer()]
    r = await chat(client, auth, **{"X-Correlation-Id": "abc.123"})
    assert r.headers["x-correlation-id"] == "abc.123"
    assert backend.contexts[0].correlation_id == "abc.123"
    r = await chat(client, auth, **{"X-Correlation-Id": "bad id!\t"})
    generated = r.headers["x-correlation-id"]
    assert generated != "bad id!" and len(generated) == 36
    assert backend.contexts[1].correlation_id == generated
    assert (await client.get("/healthz")).headers["x-correlation-id"]
