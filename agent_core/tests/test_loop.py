from types import SimpleNamespace

from voltrieve_agent.loop import TurnInput, run_turn
from voltrieve_agent.model import (
    Completed,
    FunctionCall,
    McpCall,
    ResponsesModelClient,
    TextDelta,
)
from voltrieve_agent.tools import ClientTool, ServerTool, UserContext


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
    assert types(events)[-1] == "done"
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
    assert steps(events) == ["server_tool_called", "server_tool_returned"]


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
    # the tool is not even offered to the model
    assert model.calls[0]["tools"] == []


async def test_invalid_arguments_do_not_reach_handler(user, events):
    called = []

    async def handler(args, u):
        called.append(args)
        return "x"

    model = FakeModel([[FunctionCall("c1", "check_stock", "{}")], [TextDelta("ok")]])
    await run_turn(model, [tool(handler)], turn(user), events)
    assert called == []
    assert model.calls[1]["input"][0]["output"].startswith("Error: invalid arguments")


async def test_iteration_cap(user, events):
    looping = [FunctionCall("c", "check_stock", '{"city": "x"}')]
    model = FakeModel([looping, looping, looping])
    outcome = await run_turn(model, [tool()], turn(user), events, max_iterations=3)
    assert outcome.status == "done"
    error = events.events[-1]
    assert error.type == "error" and error.data["code"] == "too_many_iterations"
    assert len(model.calls) == 3


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
        SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage)),
    ]
    seen = {}

    async def create(**kwargs):
        seen.update(kwargs)

        async def gen():
            for e in raw:
                yield e

        return gen()

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
        Completed({"total_tokens": 9}),
    ]
    assert seen["stream"] is True and seen["model"] == "gpt-x" and seen["conversation"] == "conv"
