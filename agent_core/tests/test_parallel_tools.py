"""Server tools of one model response run together, and the model still gets its outputs in order."""

import asyncio
import json

import pytest

from voltrieve_agent.loop import TurnInput, run_turn
from voltrieve_agent.model import Completed, FunctionCall, TextDelta
from voltrieve_agent.tools import ServerTool, UserContext

USER = UserContext("oid", "user", frozenset())
SCHEMA = {"type": "object", "properties": {}}


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.inputs = []

    async def stream(self, *, instructions, conversation, input, tools):
        self.inputs.append(input)
        for item in self.responses.pop(0):
            yield item


class Gate:
    """Lets every tool through only once all of them are running at the same time."""

    def __init__(self, parties):
        self.parties = parties
        self.running = 0
        self.released = asyncio.Event()

    async def wait(self):
        self.running += 1
        if self.running == self.parties:
            self.released.set()
        await asyncio.wait_for(self.released.wait(), 1)


def tool(name, handler, concurrent=True):
    return ServerTool(name, name, SCHEMA, handler, concurrent=concurrent)


def turn():
    return TurnInput(USER, "conv", "turn", "question")


def script(*calls):
    return Scripted(
        [*[FunctionCall(c, c, "{}") for c in calls], Completed({})],
        [TextDelta("answer"), Completed({})],
    )


async def collect(model, tools):
    events = []

    async def emit(event):
        events.append(event)

    outcome = await run_turn(model, tools, turn(), emit)
    return outcome, events


def steps(events):
    return [e.data["step"] for e in events if e.type == "trace"]


async def test_two_searches_really_run_at_the_same_time():
    gate = Gate(2)

    async def search(args, user):
        await gate.wait()
        return "found"

    outcome, events = await collect(script("a", "b"), [tool("a", search), tool("b", search)])
    # One after the other, the first tool would time out waiting for the second.
    assert outcome.status == "done"
    assert steps(events).count("tools_parallel_started") == 1
    assert not [e for e in events if e.type == "error"]


async def test_outputs_keep_the_order_of_the_calls_when_the_last_finishes_first():
    async def slow(args, user):
        await asyncio.sleep(0.05)
        return "slow"

    async def fast(args, user):
        return "fast"

    model = script("slow", "fast")
    await collect(model, [tool("slow", slow), tool("fast", fast)])
    assert [o["call_id"] for o in model.inputs[1]] == ["slow", "fast"]
    assert [o["output"] for o in model.inputs[1]] == ["slow", "fast"]


async def test_one_failing_tool_does_not_lose_the_other_result():
    async def broken(args, user):
        raise RuntimeError("search is down")

    async def fine(args, user):
        return "fine"

    model = script("broken", "fine")
    outcome, _ = await collect(model, [tool("broken", broken), tool("fine", fine)])
    assert outcome.status == "done"
    assert "unavailable" in model.inputs[1][0]["output"]
    assert model.inputs[1][1]["output"] == "fine"


async def test_a_tool_that_changes_something_waits_for_the_reads():
    order = []

    async def read(args, user):
        await asyncio.sleep(0.02)
        order.append("read")
        return "read"

    async def write(args, user):
        order.append("write")
        return "written"

    model = script("write", "read")
    await collect(model, [tool("read", read), tool("write", write, concurrent=False)])
    assert order == ["read", "write"]
    assert [o["call_id"] for o in model.inputs[1]] == ["write", "read"]


async def test_one_call_reports_no_parallel_run():
    async def search(args, user):
        return "found"

    _, events = await collect(script("a"), [tool("a", search)])
    assert "tools_parallel_started" not in steps(events)


async def test_parallel_result_says_what_it_saved():
    async def search(args, user):
        await asyncio.sleep(0.05)
        return "found"

    _, events = await collect(script("a", "b"), [tool("a", search), tool("b", search)])
    done = next(e for e in events if e.type == "trace" and e.data["step"] == "tools_parallel_finished")
    assert done.data["one_by_one_ms"] > done.data["wall_ms"]
    returned = [e for e in events if e.type == "trace" and e.data["step"] == "server_tool_returned"]
    assert all(e.data["duration_ms"] >= 40 for e in returned)


async def test_every_tool_call_is_tagged_with_its_model_step():
    async def search(args, user):
        return json.dumps({})

    _, events = await collect(script("a", "b"), [tool("a", search), tool("b", search)])
    called = [e for e in events if e.type == "trace" and e.data["step"] == "server_tool_called"]
    assert {e.data["iteration"] for e in called} == {1}
