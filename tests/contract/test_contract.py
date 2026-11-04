"""One scripted conversation per scenario, run through the real API and each real backend with
a fake model. Every backend must produce the same event shapes (spec sections 8.1 and 14).

The `hosted` backend runs against an in-process stand-in for the agent; see `_hosted`.
"""

import importlib.util
import json
import os
from pathlib import Path

os.environ.setdefault("TENANT_ID", "00000000-0000-0000-0000-0000000000aa")
os.environ.setdefault("API_CLIENT_ID", "00000000-0000-0000-0000-0000000000cc")

import httpx  # noqa: E402
import pytest  # noqa: E402
from app.auth import Claims  # noqa: E402
from app.backends import BackendRegistry  # noqa: E402
from app.backends.loop import LoopBackend  # noqa: E402
from app.backends.prompt import PromptBackend  # noqa: E402
from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.turns import TurnStore  # noqa: E402
from voltrieve_agent.model import Completed, FunctionCall, TextDelta  # noqa: E402
from voltrieve_agent.server_tools import KB_SEARCH_TOOLS, build_server_tools  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative_path: str):
    """Import a script that is not an installed package (agents are separate projects)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAKE_NOISE = {"name": "make_noise", "description": "Ring", "parameters": {"type": "object"}}
BOOK = '{"model": "atlas", "city": "Göteborg", "date": "2030-01-05"}'
BACKENDS = ["loop", "prompt", "hosted"]


class ScriptedModel:
    """Each call of stream() plays the next round. A round that is an Exception is raised."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)

    async def stream(self, *, instructions, conversation, input, tools):
        round_ = self.rounds.pop(0)
        if isinstance(round_, Exception):
            raise round_
        for item in round_:
            yield item


class FakeConversations:
    async def create(self, metadata=None):
        return type("Conv", (), {"id": "conv_contract"})()


class FakeOpenAI:
    conversations = FakeConversations()


def build_backend(name: str, model: ScriptedModel):
    server_tools = build_server_tools(None, None)  # handlers never run: no scenario reaches them
    if name == "loop":
        return LoopBackend(model, FakeOpenAI(), server_tools)
    if name == "prompt":
        # Both agents share one script, since a scenario uses one of them.
        return PromptBackend(model, model, FakeOpenAI(), [t for t in server_tools if t.name not in KB_SEARCH_TOOLS])
    return _hosted(model, server_tools)


def _hosted(model, server_tools):
    """The hosted backend against the real hosted agent code, minus the Foundry gateway.

    The stand-in runs what agents/hosted/main.py runs for a request: `parse_turn` on the body and
    `stream_turn` with the scripted model, which answers with SSE ending in an `outcome` event.
    An httpx.MockTransport carries it, so the real HostedBackend relay runs too.
    """
    from app.backends.hosted import HostedBackend

    hosted = load_module("hosted_main", "agents/hosted/main.py")
    runtime = hosted.Runtime(model, server_tools, allow_any_caller=True)

    async def agent(request: httpx.Request) -> httpx.Response:
        turn = hosted.parse_turn(json.loads(request.content))
        assert turn is not None, "the API sent a body the hosted agent rejects"
        wire = b"".join([chunk async for chunk in hosted.stream_turn(runtime, turn)])
        return httpx.Response(200, content=wire, headers={"x-agent-session-id": "sess-contract"})

    async def token(scope: str) -> str:
        return "token"

    http = httpx.AsyncClient(transport=httpx.MockTransport(agent))
    return HostedBackend(FakeOpenAI(), http, token, "https://foundry.invalid/api/projects/p", "voltrieve-hosted")


def api_for(name: str, model: ScriptedModel, roles: tuple[str, ...]):
    class Validator:
        async def validate(self, authorization):
            return Claims("oid-contract", "contract@example.invalid", list(roles))

    backend = build_backend(name, model)
    settings = Settings(agent_backend=name, log_level="WARNING")
    return create_app(settings, Validator(), BackendRegistry(settings, {name: lambda s: backend}), TurnStore())


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


def shape(events) -> list[str]:
    """Event types with runs of the same type collapsed (the number of deltas varies)."""
    out: list[str] = []
    for kind, _ in events:
        if not out or out[-1] != kind:
            out.append(kind)
    return out


def steps(events) -> list[str]:
    return [d["step"] for k, d in events if k == "trace"]


async def post(client, path, body):
    response = await client.post(path, json=body, headers={"Authorization": "Bearer fake"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


@pytest.fixture
def run_scenario():
    async def go(name, rounds, message, roles=("Chat.User",), client_tools=None, tool_output=None):
        app = api_for(name, ScriptedModel(*rounds), roles)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            first = await post(client, "/chat", {"message": message, "client_tools": client_tools or []})
            second = None
            if first[-1][0] == "client_tool_calls":
                paused = first[-1][1]
                second = await post(client, "/chat/tool-results", {
                    "conversation_id": paused["conversation_id"],
                    "turn_id": paused["turn_id"],
                    "results": [{"call_id": c["call_id"], "output": tool_output} for c in paused["calls"]],
                })
        return first, second

    return go


@pytest.mark.parametrize("name", BACKENDS)
async def test_plain_answer(run_scenario, name):
    first, _ = await run_scenario(
        name, [[TextDelta("Hello "), TextDelta("there"), Completed({"total_tokens": 3})]], "Hi"
    )
    assert shape(first)[0] == "trace" and shape(first)[-1] == "done" and "delta" in shape(first)
    assert "error" not in shape(first)
    assert {"token_validated", "backend_selected", "model_called"} <= set(steps(first))
    assert steps(first)[:2] == ["token_validated", "backend_selected"]
    done = first[-1][1]
    assert set(done) == {"conversation_id", "turn_id", "backend", "usage"}
    assert done["backend"] == name
    assert "".join(d["text"] for k, d in first if k == "delta") == "Hello there"


@pytest.mark.parametrize("name", BACKENDS)
async def test_client_tool_round_trip(run_scenario, name):
    rounds = [
        [FunctionCall("call_1", "make_noise", '{"times": 3}'), Completed({"total_tokens": 2})],
        [TextDelta("Beeped."), Completed({"total_tokens": 2})],
    ]
    first, second = await run_scenario(
        name, rounds, "Beep three times", client_tools=[MAKE_NOISE], tool_output="Rang 3 times"
    )
    assert first[-1][0] == "client_tool_calls" and "done" not in [k for k, _ in first]
    paused = first[-1][1]
    assert set(paused) == {"turn_id", "conversation_id", "calls"}
    assert paused["calls"] == [{"call_id": "call_1", "name": "make_noise", "arguments": '{"times": 3}'}]
    assert "client_tool_requested" in steps(first)
    assert second is not None and shape(second)[-1] == "done"
    assert second[-1][1]["turn_id"] == paused["turn_id"] and second[-1][1]["backend"] == name
    assert "".join(d["text"] for k, d in second if k == "delta") == "Beeped."


@pytest.mark.parametrize("name", BACKENDS)
async def test_authorization_denied_is_traced_and_the_turn_still_ends(run_scenario, name):
    rounds = [
        [FunctionCall("call_1", "book_test_drive", BOOK), Completed({})],
        [TextDelta("Sorry, you are not allowed to book."), Completed({})],
    ]
    first, _ = await run_scenario(name, rounds, "Book me a test drive", roles=("Chat.User",))
    order = steps(first)
    assert order.index("server_tool_called") < order.index("authorization_denied") < order.index("server_tool_returned")
    denied = next(d for k, d in first if k == "trace" and d["step"] == "authorization_denied")
    assert denied["required_role"] == "TestDrive.Book"
    assert first[-1][0] == "done"


@pytest.mark.parametrize("name", BACKENDS)
async def test_model_failure_is_an_error_event_without_detail(run_scenario, name):
    first, _ = await run_scenario(name, [RuntimeError("secret internal detail")], "Hi")
    kind, data = first[-1]
    assert kind == "error" and "done" not in [k for k, _ in first]
    assert set(data) == {"code", "message"}
    assert "secret" not in json.dumps(data)


def test_the_cli_and_the_prompt_agent_declare_the_same_client_tools():
    """The CLI sends its tools with each request; the prompt agent has a copy in its definition
    (a prompt agent cannot take tools per request). The two copies must not drift."""
    cli = load_module("cli_tools", "clients/cli/src/voltrieve_cli/tools.py").CLIENT_TOOLS
    agent = load_module("create_agents", "agents/prompt/create_agents.py").CLI_TOOLS
    assert cli == agent
    from app.backends.prompt import CLI_AGENT_TOOL_NAMES

    assert {t["name"] for t in cli} == CLI_AGENT_TOOL_NAMES
