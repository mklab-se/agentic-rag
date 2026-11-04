"""The real orchestration loop behind the real API, with a scripted model and a fake openai."""

import httpx
import pytest
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
    def __init__(self, existing=()):
        self.created = []
        self.existing = list(existing)

    async def create(self, conversation_id, items):
        self.created.append((conversation_id, items))

    async def list(self, conversation_id, limit, order):
        async def gen():
            for item in self.existing:
                yield item

        return gen()


class NotFound(Exception):
    status_code = 404


class FakeConversations:
    def __init__(self, existing=()):
        self.items = FakeItems(existing)
        self.metadata = None

    async def create(self, metadata=None):
        self.metadata = metadata
        return type("Conv", (), {"id": "conv_real"})()

    async def retrieve(self, conversation_id):
        if conversation_id != "conv_real":
            raise NotFound()
        return type("Conv", (), {"metadata": self.metadata})()


class FakeOpenAI:
    def __init__(self, existing=()):
        self.conversations = FakeConversations(existing)


def item(kind, call_id):
    return type("Item", (), {"type": kind, "call_id": call_id})()


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
    assert events[-1][1]["usage"] == {"total_tokens": 7}  # the whole turn
    assert openai.conversations.metadata == {"owner_oid": "oid-anna"}
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


async def test_owner_is_read_from_conversation_metadata():
    openai = FakeOpenAI()
    backend = LoopBackend(ScriptedModel(), openai, [])
    await backend.create_conversation("oid-anna")
    assert await backend.get_conversation_owner("conv_real") == "oid-anna"
    assert await backend.get_conversation_owner("conv_missing") is None


async def test_an_outage_is_not_mistaken_for_an_unknown_conversation():
    openai = FakeOpenAI()

    async def down(conversation_id):
        raise ConnectionError("foundry is down")

    openai.conversations.retrieve = down
    with pytest.raises(ConnectionError):
        await LoopBackend(ScriptedModel(), openai, []).get_conversation_owner("conv_real")


async def test_repair_answers_only_calls_without_output_in_batches():
    existing = [item("function_call", f"c{i}") for i in range(45)]
    existing += [item("function_call_output", "c3"), item("message", "ignored")]
    openai = FakeOpenAI(existing)
    backend = LoopBackend(ScriptedModel(), openai, [])
    await backend.repair("conv_real")
    batches = openai.conversations.items.created
    assert [len(b[1]) for b in batches] == [20, 20, 4]
    written = [o["call_id"] for _, b in batches for o in b]
    assert "c3" not in written and len(set(written)) == 44
    assert all(o["type"] == "function_call_output" for _, b in batches for o in b)


async def test_repair_with_nothing_open_writes_nothing():
    openai = FakeOpenAI([item("function_call", "a"), item("function_call_output", "a")])
    await LoopBackend(ScriptedModel(), openai, []).repair("conv_real")
    assert openai.conversations.items.created == []


async def test_close_runs_closers():
    closed = []

    async def closer():
        closed.append(1)

    await LoopBackend(ScriptedModel(), FakeOpenAI(), [], closers=[closer]).close()
    assert closed == [1]


async def test_build_loop_backend_constructs_with_dummy_settings():
    from app.backends.loop import build_loop_backend

    settings = Settings(
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        search_endpoint="https://example.search.windows.net",
        dealer_url="https://dealer.example",
        dealer_client_id="00000000-0000-0000-0000-0000000000dd",
    )
    backend = build_loop_backend(settings)  # no network at construction
    assert isinstance(backend, LoopBackend)
    await backend.close()


def test_build_loop_backend_without_settings_is_unavailable(caplog):
    import pytest

    from app.backends.base import BackendUnavailable
    from app.backends.loop import build_loop_backend

    with pytest.raises(BackendUnavailable) as e, caplog.at_level("WARNING"):
        build_loop_backend(Settings())
    assert "FOUNDRY" not in str(e.value)
    assert "FOUNDRY_PROJECT_ENDPOINT" in caplog.text
