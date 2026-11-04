import pytest
from types import SimpleNamespace

import openai

from voltrieve_agent.loop import TurnInput, run_turn
from voltrieve_agent.model import (
    Completed,
    Failed,
    FunctionCall,
    McpCall,
    ResponsesModelClient,
    TextDelta,
)
from voltrieve_agent.tools import ClientTool, ServerTool, current_correlation_id


class FakeModel:
    """Yields one scripted list of stream items per call and records the calls."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    async def stream(self, *, instructions, conversation, input, tools):
        self.calls.append({"conversation": conversation, "input": input, "tools": tools})
        for item in self.scripts.pop(0):
            yield item


SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}


def tool(handler=None, role=None, name="check_stock"):
    async def default(args, user):
        return f"stock {args['city']}"

    return ServerTool(name, "d", SCHEMA, handler or default, required_role=role)


def turn(user, client_tools=()):
    return TurnInput(user, "conv-1", "turn-1", "hello", list(client_tools))


def types(events):
    return [e.type for e in events.events]


def steps(events):
    return [e.data["step"] for e in events.events if e.type == "trace"]


async def test_plain_answer(user, events):
    model = FakeModel([[TextDelta("Hi "), TextDelta("there"), Completed({"total_tokens": 5})]])
    outcome = await run_turn(model, [], turn(user), events)
    assert outcome.status == "done" and outcome.usage == {"total_tokens": 5}
    assert [e.data.get("text") for e in events.events if e.type == "delta"] == ["Hi ", "there"]
    assert "done" not in types(events)
    assert steps(events) == ["model_called", "model_returned"]
    assert model.calls[0]["conversation"] == "conv-1" and model.calls[0]["input"] == "hello"


async def test_server_tool_round_trip(user, events):
    model = FakeModel(
        [
            [FunctionCall("c1", "check_stock", '{"city": "Oslo"}'), Completed({"total_tokens": 3})],
            [TextDelta("Done"), Completed({"total_tokens": 4})],
        ]
    )
    outcome = await run_turn(model, [tool()], turn(user), events)
    assert outcome.status == "done" and outcome.usage == {"total_tokens": 7}
    assert model.calls[1]["input"] == [
        {"type": "function_call_output", "call_id": "c1", "output": "stock Oslo"}
    ]
    assert steps(events) == [
        "model_called",
        "model_returned",
        "server_tool_called",
        "server_tool_returned",
        "model_called",
        "model_returned",
    ]


async def test_client_tool_pauses_and_keeps_server_outputs(user, events):
    model = FakeModel(
        [
            [
                FunctionCall("c1", "check_stock", '{"city": "Oslo"}'),
                FunctionCall("c2", "pick_file", "{}"),
            ]
        ]
    )
    client = ClientTool("pick_file", "Pick", {"type": "object", "properties": {}})
    outcome = await run_turn(model, [tool()], turn(user, [client]), events)
    assert outcome.status == "paused"
    assert outcome.pending_outputs == [
        {"type": "function_call_output", "call_id": "c1", "output": "stock Oslo"}
    ]
    event = next(e for e in events.events if e.type == "client_tool_calls")
    assert event.data["turn_id"] == "turn-1"
    assert event.data["calls"] == [{"call_id": "c2", "name": "pick_file", "arguments": "{}"}]
    assert "done" not in types(events) and len(model.calls) == 1
    assert outcome.client_call_ids == ["c2"]
    assert "client_tool_requested" in steps(events)


async def test_unknown_tool_gets_error_output(user, events):
    model = FakeModel([[FunctionCall("c1", "nope", "{}")], [TextDelta("ok")]])
    await run_turn(model, [], turn(user), events)
    output = model.calls[1]["input"][0]["output"]
    assert "unknown tool" in output


async def test_role_denied_refuses_with_trace(user, events):
    called = []

    async def handler(args, u):
        called.append(args)
        return "booked"

    model = FakeModel([[FunctionCall("c1", "check_stock", '{"city": "x"}')], [TextDelta("no")]])
    await run_turn(model, [tool(handler, role="TestDrive.Book")], turn(user), events)
    assert called == []
    assert "authorization_denied" in steps(events)
    assert model.calls[1]["input"][0]["output"].startswith("Refused")
    # the tool is offered, and the denial is enforced and visible at execution
    assert [t["name"] for t in model.calls[0]["tools"]] == ["check_stock"]


async def test_invalid_arguments_do_not_reach_handler(user, events):
    called = []

    async def handler(args, u):
        called.append(args)
        return "x"

    model = FakeModel([[FunctionCall("c1", "check_stock", "{}")], [TextDelta("ok")]])
    await run_turn(model, [tool(handler)], turn(user), events)
    assert called == []
    assert model.calls[1]["input"][0]["output"].startswith("Error: invalid arguments")


async def test_iteration_cap_sends_every_output_then_fails(user, events):
    def script(n):
        return [FunctionCall(f"c{n}", "check_stock", '{"city": "x"}')]

    model = FakeModel([script(1), script(2), script(3), [TextDelta("ignored")]])
    outcome = await run_turn(model, [tool()], turn(user), events, max_iterations=3)
    assert outcome.status == "failed"
    error = events.events[-1]
    assert error.type == "error" and error.data["code"] == "too_many_iterations"
    assert len(model.calls) == 4
    assert model.calls[3]["tools"] == []
    sent = [o["call_id"] for c in model.calls[1:] for o in c["input"]]
    assert sent == ["c1", "c2", "c3"]


async def test_failed_item_emits_safe_error_and_runs_no_calls(user, events):
    called = []

    async def handler(args, u):
        called.append(args)
        return "x"

    model = FakeModel(
        [[FunctionCall("c1", "check_stock", '{"city": "x"}'), Failed("model_failed", "secret raw")]]
    )
    outcome = await run_turn(model, [tool(handler)], turn(user), events)
    assert outcome.status == "failed" and called == []
    error = events.events[-1]
    assert error.type == "error" and error.data["code"] == "model_failed"
    assert "secret raw" not in error.data["message"]


async def test_model_exception_becomes_model_error(user, events):
    class Boom:
        async def stream(self, **kwargs):
            raise RuntimeError("token leaked here")
            yield  # pragma: no cover

    outcome = await run_turn(Boom(), [], turn(user), events)
    assert outcome.status == "failed"
    error = events.events[-1]
    assert error.data["code"] == "model_error" and "token" not in error.data["message"]


async def test_correlation_id_reaches_dealer_header(user, events):
    seen = []

    async def handler(args, u):
        seen.append(current_correlation_id.get())
        return "x"

    call = [FunctionCall("c1", "check_stock", '{"city": "x"}')]
    t = turn(user)
    t.correlation_id = "corr-9"
    await run_turn(FakeModel([call, []]), [tool(handler)], t, events)
    await run_turn(FakeModel([call, []]), [tool(handler)], turn(user), events)
    assert seen == ["corr-9", "turn-1"]
    assert current_correlation_id.get() is None


async def test_pause_then_continue(user, events):
    client = ClientTool("pick_file", "Pick", {"type": "object", "properties": {}})
    first = FakeModel(
        [
            [
                FunctionCall("c1", "check_stock", '{"city": "Oslo"}'),
                FunctionCall("c2", "pick_file", "{}"),
            ]
        ]
    )
    paused = await run_turn(first, [tool()], turn(user, [client]), events)
    assert paused.status == "paused"
    continuation = paused.pending_outputs + [
        {"type": "function_call_output", "call_id": "c2", "output": "report.pdf"}
    ]
    second = FakeModel([[TextDelta("Thanks"), Completed({"total_tokens": 2})]])
    t = TurnInput(user, "conv-1", "turn-2", continuation, [client])
    outcome = await run_turn(second, [tool()], t, events)
    assert outcome.status == "done"
    assert second.calls[0]["input"] == continuation
    assert {o["call_id"] for o in continuation} == {"c1", "c2"}


async def test_mcp_call_becomes_trace(user, events):
    model = FakeModel([[McpCall("search", "kb", "preview"), TextDelta("a")]])
    await run_turn(model, [], turn(user), events)
    assert "mcp_tool_called" in steps(events)


async def test_responses_client_maps_stream_events():
    usage = SimpleNamespace(model_dump=lambda: {"total_tokens": 9})
    raw = [
        SimpleNamespace(type="response.created"),
        SimpleNamespace(type="response.output_text.delta", delta="Hel"),
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(type="function_call", call_id="c1", name="f", arguments="{}"),
        ),
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="mcp_call", name="search", server_label="kb", output="x" * 900
            ),
        ),
        SimpleNamespace(
            type="response.output_item.done", item=SimpleNamespace(type="message")
        ),
        SimpleNamespace(type="response.refusal.delta", delta="No."),
        SimpleNamespace(
            type="response.failed",
            response=SimpleNamespace(error=SimpleNamespace(message="boom")),
        ),
        SimpleNamespace(
            type="response.incomplete",
            response=SimpleNamespace(incomplete_details=SimpleNamespace(reason="max_tokens")),
        ),
        SimpleNamespace(type="error", message="bad"),
        SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage)),
    ]
    seen = {}

    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            seen["closed"] = True

        async def __aiter__(self):
            for e in raw:
                yield e

    async def create(**kwargs):
        seen.update(kwargs)

        return FakeStream()

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    model = ResponsesModelClient(client, "gpt-x")
    items = [
        i
        async for i in model.stream(
            instructions="i", conversation="conv", input="hi", tools=[{"type": "function"}]
        )
    ]
    assert items == [
        TextDelta("Hel"),
        FunctionCall("c1", "f", "{}"),
        McpCall("search", "kb", "x" * 500),
        TextDelta("No."),
        Failed("model_failed", "boom"),
        Failed("model_incomplete", "max_tokens"),
        Failed("model_error", "bad"),
        Completed({"total_tokens": 9}),
    ]
    assert seen["closed"] and seen["stream"] is True and seen["model"] == "gpt-x" and seen["conversation"] == "conv"


async def test_responses_model_client_with_agent_sends_only_the_reference():
    seen = {}

    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def __aiter__(self):
            return
            yield

    async def create(**kwargs):
        seen.update(kwargs)
        return FakeStream()

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    model = ResponsesModelClient(client, agent_name="agent-x")
    [i async for i in model.stream(instructions="i", conversation="conv", input="hi", tools=[{"type": "function"}])]
    assert seen == {
        "conversation": "conv",
        "input": "hi",
        "extra_body": {"agent_reference": {"name": "agent-x", "type": "agent_reference"}},
        "stream": True,
    }


def test_responses_client_needs_a_model_or_an_agent():
    with pytest.raises(ValueError):
        ResponsesModelClient(object())


def test_mcp_call_error_text_is_surfaced_when_there_is_no_output():
    from voltrieve_agent.model import _map_event

    failed = SimpleNamespace(
        type="response.output_item.done",
        item=SimpleNamespace(
            type="mcp_call", name="search", server_label="kb", output=None, error="403 forbidden"
        ),
    )
    assert _map_event(failed) == McpCall("search", "kb", "403 forbidden")


async def test_client_call_with_arguments_its_schema_rejects_is_answered_not_forwarded(user, events):
    schema = {"type": "object", "properties": {"times": {"type": "integer", "maximum": 10}}, "required": ["times"]}
    client = ClientTool("make_noise", "Ring", schema)
    model = FakeModel(
        [
            [FunctionCall("c1", "make_noise", '{"times": 99}'), FunctionCall("c2", "make_noise", '{"times": 2}')],
            [TextDelta("ok")],
        ]
    )
    outcome = await run_turn(model, [], turn(user, [client]), events)
    forwarded = next(e for e in events.events if e.type == "client_tool_calls")
    assert [c["call_id"] for c in forwarded.data["calls"]] == ["c2"]
    assert outcome.status == "paused" and outcome.client_call_ids == ["c2"]
    assert outcome.pending_outputs[0]["call_id"] == "c1"
    assert outcome.pending_outputs[0]["output"].startswith("Error: invalid arguments for 'make_noise'")
    assert "client_tool_rejected" in steps(events)


async def test_when_every_client_call_is_rejected_the_model_gets_the_errors_and_the_turn_goes_on(user, events):
    client = ClientTool("make_noise", "Ring", {"type": "object", "required": ["times"]})
    model = FakeModel([[FunctionCall("c1", "make_noise", "{}")], [TextDelta("sorry")]])
    outcome = await run_turn(model, [], turn(user, [client]), events)
    assert outcome.status == "done" and "client_tool_calls" not in types(events)
    assert model.calls[1]["input"][0]["output"].startswith("Error: invalid arguments")


async def test_usage_is_summed_including_nested_detail(user, events):
    model = FakeModel(
        [
            [FunctionCall("c1", "check_stock", '{"city": "x"}'),
             Completed({"input_tokens": 10, "input_tokens_details": {"cached_tokens": 4}})],
            [TextDelta("ok"),
             Completed({"input_tokens": 5, "input_tokens_details": {"cached_tokens": 1}, "total_tokens": 7})],
        ]
    )
    outcome = await run_turn(model, [tool()], turn(user), events)
    assert outcome.usage == {
        "input_tokens": 15, "input_tokens_details": {"cached_tokens": 5}, "total_tokens": 7
    }


async def test_a_failing_emit_is_not_reported_as_a_model_error(user):
    async def broken_emit(event):
        if event.type == "delta":
            raise RuntimeError("the client went away")

    with pytest.raises(RuntimeError, match="went away"):
        await run_turn(FakeModel([[TextDelta("hi")]]), [], turn(user), broken_emit)


async def test_the_model_stream_is_closed_when_the_loop_stops_reading_it(user, events):
    closed = []

    class Tracked:
        async def stream(self, **kwargs):
            try:
                yield Failed("model_failed", "x")
                yield TextDelta("never read")
            finally:
                closed.append(True)

    outcome = await run_turn(Tracked(), [], turn(user), events)
    assert outcome.status == "failed" and closed == [True]


class _Events:
    """An async stream of canned events that can end by raising."""

    def __init__(self, events, error=None):
        self.events, self.error = events, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for event in self.events:
            yield event
        if self.error:
            raise self.error


def _openai_client(*streams):
    pending = list(streams)

    async def create(**kwargs):
        return pending.pop(0)

    return SimpleNamespace(responses=SimpleNamespace(create=create))


def _rate_limited():
    return openai.APIError("Model deployment rate limit exceeded.", request=None, body=None)


async def _collect(client):
    kwargs = dict(instructions="i", conversation="c", input="hi", tools=[])
    return [item async for item in client.stream(**kwargs)]


async def test_rate_limit_before_output_is_retried():
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    delta = SimpleNamespace(type="response.output_text.delta", delta="Hi")
    client = ResponsesModelClient(
        _openai_client(_Events([], _rate_limited()), _Events([delta])), model="m", sleep=sleep
    )
    assert [i.text for i in await _collect(client)] == ["Hi"]
    assert waits == [20.0]


async def test_rate_limit_after_output_is_not_retried():
    delta = SimpleNamespace(type="response.output_text.delta", delta="Hi")
    client = ResponsesModelClient(_openai_client(_Events([delta], _rate_limited())), model="m")
    with pytest.raises(openai.APIError):
        await _collect(client)


async def test_mcp_calls_report_when_they_ran():
    from voltrieve_agent.model import ResponsesModelClient

    raw = [
        SimpleNamespace(
            type="response.output_item.added", item=SimpleNamespace(type="mcp_call", id="m1")
        ),
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="mcp_call", id="m1", name="knowledge_base_retrieve",
                server_label="voltrieve-parts-kb", output="x", arguments='{"q":"disc"}',
            ),
        ),
    ]

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def __aiter__(self):
            async def events():
                for event in raw:
                    yield event

            return events()

    class Responses:
        async def create(self, **kwargs):
            return Stream()

    client = ResponsesModelClient(SimpleNamespace(responses=Responses()), "m", agent_name="a")
    items = [i async for i in client.stream(instructions="", conversation="c", input="q", tools=[])]
    assert items[0].server == "voltrieve-parts-kb" and items[0].arguments == '{"q":"disc"}'
    assert items[0].started_ms is not None and items[0].finished_ms >= items[0].started_ms
