"""Curated answers reach the user word for word, without a second model call."""

import json

import pytest

from voltrieve_agent.curated import CURATED_ANSWERS, FinalAnswer
from voltrieve_agent.loop import TurnInput, run_turn
from voltrieve_agent.model import Completed, FunctionCall, TextDelta
from voltrieve_agent.server_tools import CURATED_TOOL, build_server_tools
from voltrieve_agent.tools import ServerTool, UserContext

USER = UserContext("oid", "user", frozenset())


class FakeModel:
    def __init__(self, scripts, record_error=None):
        self.scripts = list(scripts)
        self.calls = []
        self.recorded = []
        self.record_error = record_error

    async def stream(self, *, instructions, conversation, input, tools):
        self.calls.append(input)
        for item in self.scripts.pop(0):
            yield item

    async def record(self, conversation, items):
        if self.record_error:
            raise self.record_error
        self.recorded.append((conversation, items))


def curated_call(topic="contact", call_id="c1"):
    return FunctionCall(call_id, CURATED_TOOL, json.dumps({"topic": topic}))


async def run(model, tools=None):
    events = []

    async def emit(event):
        events.append(event)

    outcome = await run_turn(
        model,
        tools if tools is not None else build_server_tools(None, None),
        TurnInput(USER, "conv", "turn", "What is your phone number?"),
        emit,
    )
    return outcome, events


def text_of(events):
    return "".join(e.data["text"] for e in events if e.type == "delta")


@pytest.mark.asyncio
async def test_the_stored_text_is_sent_without_a_second_model_call():
    model = FakeModel([[curated_call(), Completed({"input_tokens": 5})]])
    outcome, events = await run(model)
    text = CURATED_ANSWERS["contact"].text
    assert outcome.status == "done"
    assert outcome.usage == {"input_tokens": 5}
    assert text_of(events) == text
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_the_conversation_gets_the_output_and_the_answer():
    model = FakeModel([[curated_call(), Completed()]])
    await run(model)
    text = CURATED_ANSWERS["contact"].text
    assert model.recorded == [
        (
            "conv",
            [
                {"type": "function_call_output", "call_id": "c1", "output": text},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                },
            ],
        )
    ]


@pytest.mark.asyncio
async def test_with_another_tool_the_model_writes_the_answer():
    async def other(args, user):
        return "other output"

    tools = [*build_server_tools(None, None), ServerTool("other", "", {"type": "object"}, other)]
    model = FakeModel(
        [
            [curated_call(), FunctionCall("c2", "other", "{}"), Completed()],
            [TextDelta("Both answered."), Completed()],
        ]
    )
    outcome, events = await run(model, tools)
    assert outcome.status == "done"
    assert text_of(events) == "Both answered."
    assert [i["call_id"] for i in model.calls[1]] == ["c1", "c2"]
    assert model.recorded == []


@pytest.mark.asyncio
async def test_after_another_tool_the_model_still_writes_the_answer():
    async def other(args, user):
        return "other output"

    tools = [*build_server_tools(None, None), ServerTool("other", "", {"type": "object"}, other)]
    model = FakeModel(
        [
            [FunctionCall("c1", "other", "{}"), Completed()],
            [curated_call(call_id="c2"), Completed()],
            [TextDelta("The brake parts are..."), Completed()],
        ]
    )
    outcome, events = await run(model, tools)
    assert outcome.status == "done"
    assert text_of(events) == "The brake parts are..."
    assert len(model.calls) == 3
    assert model.recorded == []


@pytest.mark.asyncio
async def test_an_unknown_topic_goes_back_to_the_model():
    model = FakeModel(
        [[curated_call("no_such_topic"), Completed()], [TextDelta("Sorry."), Completed()]]
    )
    outcome, events = await run(model)
    assert outcome.status == "done"
    assert text_of(events) == "Sorry."
    assert "invalid arguments" in model.calls[1][0]["output"]
    assert model.recorded == []


@pytest.mark.asyncio
async def test_a_failed_write_is_an_error_and_sends_no_text():
    model = FakeModel([[curated_call(), Completed()]], record_error=RuntimeError("down"))
    outcome, events = await run(model)
    assert outcome.status == "failed"
    assert text_of(events) == ""
    assert [e.data["code"] for e in events if e.type == "error"] == ["model_error"]


def test_every_topic_is_described_to_the_model():
    tool = next(t for t in build_server_tools(None, None) if t.name == CURATED_TOOL)
    assert tool.parameters["properties"]["topic"]["enum"] == list(CURATED_ANSWERS)
    for topic in CURATED_ANSWERS:
        assert f"{topic}:" in tool.description


def test_final_answer_is_still_text():
    assert FinalAnswer("x") == "x"
