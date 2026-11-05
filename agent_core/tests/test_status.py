"""Statuses tell the user what is happening, in order, and hold nothing private."""

import json

import pytest

from voltrieve_agent.events import RETRYING, status
from voltrieve_agent.loop import TurnInput, run_turn
from voltrieve_agent.model import (
    Completed,
    FunctionCall,
    McpCall,
    McpStarted,
    Retrying,
    TextDelta,
)
from voltrieve_agent.server_tools import build_server_tools
from voltrieve_agent.tools import ClientTool, ServerTool, UserContext

USER = UserContext("oid", "user", frozenset())


class FakeModel:
    def __init__(self, scripts):
        self.scripts = list(scripts)

    async def stream(self, *, instructions, conversation, input, tools):
        for item in self.scripts.pop(0):
            yield item

    async def record(self, conversation, items):
        pass


async def statuses(model, tools=(), client_tools=()):
    events = []

    async def emit(event):
        events.append(event)

    await run_turn(
        model,
        list(tools),
        TurnInput(USER, "conv", "turn", "secret question", list(client_tools)),
        emit,
    )
    return events, [e.data["code"] for e in events if e.type == "status"]


def named(name, code):
    async def handler(args, user):
        return "ok"

    return ServerTool(name, "", {"type": "object"}, handler, status=(code, code))


@pytest.mark.asyncio
async def test_a_tool_says_what_it_does_and_the_next_call_reads_the_result():
    model = FakeModel([[FunctionCall("c", "lookup", "{}"), Completed()], [TextDelta("Hi"), Completed()]])
    _, codes = await statuses(model, [named("lookup", "looking_up")])
    assert codes == ["looking_up", "reviewing_results"]


@pytest.mark.asyncio
async def test_a_direct_answer_adds_nothing_to_the_opening_status():
    _, codes = await statuses(FakeModel([[TextDelta("Hi"), Completed()]]))
    assert codes == []


@pytest.mark.asyncio
async def test_a_search_in_foundry_is_named_by_its_knowledge_base():
    model = FakeModel(
        [[McpStarted("voltrieve-parts-kb"), McpCall("r", "voltrieve-parts-kb", ""), TextDelta("Hi"), Completed()]]
    )
    _, codes = await statuses(model)
    assert codes == ["searching_parts"]


@pytest.mark.asyncio
async def test_an_unknown_server_still_gives_a_status():
    _, codes = await statuses(FakeModel([[McpStarted("other"), TextDelta("Hi"), Completed()]]))
    assert codes == ["working"]


@pytest.mark.asyncio
async def test_a_rate_limit_is_announced():
    _, codes = await statuses(FakeModel([[Retrying(), TextDelta("Hi"), Completed()]]))
    assert codes == ["retrying"]


@pytest.mark.asyncio
async def test_a_client_tool_waits_for_the_device_before_the_pause():
    tool = ClientTool("beep", "", {"type": "object"})
    model = FakeModel([[FunctionCall("c", "beep", "{}"), Completed()]])
    events, codes = await statuses(model, client_tools=[tool])
    assert codes == ["waiting_for_device"]
    assert [e.type for e in events if e.type != "trace"] == ["status", "client_tool_calls"]


@pytest.mark.asyncio
async def test_no_status_carries_the_question_or_the_arguments():
    model = FakeModel(
        [[FunctionCall("c", "lookup", '{"query":"secret argument"}'), Completed()], [TextDelta("Hi"), Completed()]]
    )
    events, _ = await statuses(model, [named("lookup", "looking_up")])
    text = json.dumps([e.data for e in events if e.type == "status"])
    assert "secret" not in text


def test_every_server_tool_says_something_better_than_the_default():
    tools = [t for t in build_server_tools(None, None) if t.name != "get_current_date"]
    assert all(t.status[0] != "working" for t in tools)


def test_status_wire_shape():
    assert status(RETRYING).data == {"code": "retrying", "message": "Busy, trying again"}
