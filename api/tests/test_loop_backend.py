"""The real orchestration loop behind the real API, with a scripted model and a fake openai."""

import httpx
from voltrieve_agent.model import Completed, FunctionCall, TextDelta

from app.backends import BackendRegistry
from app.backends.loop import LoopBackend
from app.main import create_app
from app.settings import Settings
from app.turns import TurnStore
from tests.conftest import parse_sse

TOOL = {"name": "read_file", "description": "Read", "parameters": {"type": "object"}}


class ScriptedModel:
    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.inputs = []

    async def stream(self, *, instructions, conversation, input, tools):
        self.inputs.append(input)
        for item in self.rounds.pop(0):
            yield item


class FakeItems:
    def __init__(self):
        self.created = []

    async def create(self, conversation_id, items):
        self.created.append((conversation_id, items))


class FakeConversations:
    def __init__(self):
        self.items = FakeItems()

    async def create(self):
        return type("Conv", (), {"id": "conv_real"})()


class FakeOpenAI:
    def __init__(self):
        self.conversations = FakeConversations()


async def test_client_tool_round_trip_through_loop(validator, auth):
    model = ScriptedModel(
        [FunctionCall("call_9", "read_file", '{"path": "a"}'), Completed({"total_tokens": 3})],
        [TextDelta("It says hi."), Completed({"total_tokens": 4})],
    )
    openai = FakeOpenAI()
    backend = LoopBackend(model, openai, [])
    settings = Settings()
    app = create_app(settings, validator, BackendRegistry(settings, {"loop": lambda s: backend}), TurnStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/chat", headers=auth, json={"message": "read a", "client_tools": [TOOL]})
        events = parse_sse(r.text)
        assert [t for t, _ in events][-1] == "client_tool_calls"
        paused = events[-1][1]
        assert set(paused) == {"turn_id", "conversation_id", "calls"}
        assert paused["conversation_id"] == "conv_real"
        assert paused["calls"] == [{"call_id": "call_9", "name": "read_file", "arguments": '{"path": "a"}'}]

        r = await c.post(
            "/chat/tool-results",
            headers=auth,
            json={
                "conversation_id": "conv_real",
                "turn_id": paused["turn_id"],
                "results": [{"call_id": "call_9", "output": "hi"}],
            },
        )
        events = parse_sse(r.text)
    assert [d["text"] for t, d in events if t == "delta"] == ["It says hi."]
    assert events[-1][1]["usage"] == {"total_tokens": 4}
    assert model.inputs[1] == [{"type": "function_call_output", "call_id": "call_9", "output": "hi"}]


async def test_abandon_adds_items_without_model_call():
    model = ScriptedModel()
    openai = FakeOpenAI()
    backend = LoopBackend(model, openai, [])
    outputs = [{"type": "function_call_output", "call_id": "c", "output": "the client did not return a result"}]
    await backend.abandon("conv_1", outputs)
    await backend.abandon("conv_1", [])
    assert openai.conversations.items.created == [("conv_1", outputs)]
    assert model.inputs == []
