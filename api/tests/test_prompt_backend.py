"""Backend A with a fake Foundry client: agent selection, relay, unsupported tools, roles."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
from voltrieve_agent.events import AgentEvent
from voltrieve_agent.model import ResponsesModelClient
from voltrieve_agent.server_tools import KB_SEARCH_TOOLS, build_server_tools
from voltrieve_agent.tools import ClientTool, UserContext

from app.backends import BACKEND_NAMES, BackendRegistry
from app.backends.base import TurnContext
from app.backends.prompt import CLI_AGENT_TOOL_NAMES, PromptBackend
from app.main import create_app
from app.settings import Settings
from app.turns import TurnStore
from tests.conftest import parse_sse
from tests.test_loop_backend import FakeConversations

CLI_TOOL = ClientTool("make_noise", "Ring", {"type": "object"})
OTHER_TOOL = ClientTool("read_file", "Read", {"type": "object"})


def done_item(**fields):
    return SimpleNamespace(type="response.output_item.done", item=SimpleNamespace(**fields))


def text(delta):
    return SimpleNamespace(type="response.output_text.delta", delta=delta)


def completed(tokens):
    return SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(usage=SimpleNamespace(model_dump=lambda: {"total_tokens": tokens})),
    )


class FakeStream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def __aiter__(self):
        for e in self.events:
            yield e


class FakeOpenAI:
    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls = []
        self.conversations = FakeConversations()
        self.responses = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.rounds.pop(0))


class FakeDealer:
    def __init__(self):
        self.booked = []

    async def stock(self, model, city):
        return "3 in stock"

    async def book(self, model, city, date, oid):
        self.booked.append((model, city, date, oid))
        return "booked"


def make_backend(openai, dealer=None):
    tools = [t for t in build_server_tools(dealer or FakeDealer(), None) if t.name not in KB_SEARCH_TOOLS]
    return PromptBackend(
        ResponsesModelClient(openai, agent_name="agent-cli"),
        ResponsesModelClient(openai, agent_name="agent-web"),
        openai,
        tools,
    )


def ctx(input_="hi", tools=(), roles=()):
    return TurnContext(
        user=UserContext("oid-anna", "anna", frozenset(roles)),
        conversation_id="conv_real",
        turn_id="t1",
        input=input_,
        client_tools=list(tools),
    )


async def run(backend, context):
    events: list[AgentEvent] = []

    async def emit(event):
        events.append(event)

    return await backend.run_turn(context, emit), events


def agent_of(call):
    return call["extra_body"]["agent_reference"]["name"]


async def test_agent_is_picked_by_client_tools_and_sends_no_tools():
    openai = FakeOpenAI([text("a"), completed(1)], [text("b"), completed(1)])
    backend = make_backend(openai)
    await run(backend, ctx())
    await run(backend, ctx(tools=[CLI_TOOL]))
    assert [agent_of(c) for c in openai.calls] == ["agent-web", "agent-cli"]
    for call in openai.calls:
        assert call["conversation"] == "conv_real" and call["stream"] is True
        assert call["extra_body"]["agent_reference"]["type"] == "agent_reference"
        assert not {"tools", "model", "instructions"} & set(call)


async def test_dealer_tool_runs_in_the_api_and_mcp_call_becomes_trace():
    openai = FakeOpenAI(
        [
            done_item(type="mcp_call", name="knowledge_base_retrieve", server_label="voltrieve-kb", output="chunk"),
            done_item(type="function_call", call_id="c1", name="check_stock", arguments='{"model": "atlas"}'),
            completed(2),
        ],
        [text("3 cars"), completed(3)],
    )
    outcome, events = await run(make_backend(openai), ctx())
    assert outcome.status == "done" and outcome.usage == {"total_tokens": 5}
    steps = [e.data["step"] for e in events if e.type == "trace"]
    assert "mcp_tool_called" in steps and "server_tool_returned" in steps
    mcp = next(e for e in events if e.data.get("step") == "mcp_tool_called")
    assert mcp.data["server"] == "voltrieve-kb" and mcp.data["output_preview"] == "chunk"
    assert openai.calls[1]["input"] == [{"type": "function_call_output", "call_id": "c1", "output": "3 in stock"}]
    assert agent_of(openai.calls[1]) == "agent-web"


async def test_client_tool_call_pauses_and_continuation_reuses_cli_agent():
    openai = FakeOpenAI(
        [done_item(type="function_call", call_id="c9", name="make_noise", arguments='{"times": 2}'), completed(1)],
        [text("done"), completed(1)],
    )
    backend = make_backend(openai)
    outcome, events = await run(backend, ctx(tools=[CLI_TOOL]))
    assert outcome.status == "paused" and outcome.client_call_ids == ["c9"]
    assert events[-1].type == "client_tool_calls"
    assert events[-1].data["calls"][0]["name"] == "make_noise"
    results = [{"type": "function_call_output", "call_id": "c9", "output": "rang"}]
    outcome, _ = await run(backend, ctx(results, tools=[CLI_TOOL]))
    assert outcome.status == "done"
    assert openai.calls[1]["input"] == results and agent_of(openai.calls[1]) == "agent-cli"


async def test_unsupported_client_tool_is_refused_before_any_model_call():
    openai = FakeOpenAI()
    outcome, events = await run(make_backend(openai), ctx(tools=[CLI_TOOL, OTHER_TOOL]))
    assert outcome.status == "failed" and openai.calls == []
    error = events[-1]
    assert error.type == "error" and error.data["code"] == "unsupported_client_tool"
    assert "read_file" in error.data["message"] and "make_noise" not in error.data["message"].split("Not supported:")[1]
    trace_event = next(e for e in events if e.data.get("step") == "unsupported_client_tool")
    assert trace_event.data["tools"] == ["read_file"]


async def test_booking_without_role_is_denied_and_never_reaches_the_dealer():
    dealer = FakeDealer()
    call = done_item(
        type="function_call",
        call_id="c1",
        name="book_test_drive",
        arguments='{"model": "atlas", "city": "Stockholm", "date": "2030-01-01"}',
    )
    openai = FakeOpenAI([call, completed(1)], [text("sorry"), completed(1)])
    outcome, events = await run(make_backend(openai, dealer), ctx())
    assert outcome.status == "done" and dealer.booked == []
    denied = next(e for e in events if e.data.get("step") == "authorization_denied")
    assert denied.data["required_role"] == "TestDrive.Book"
    assert "not allowed" in openai.calls[1]["input"][0]["output"]

    openai = FakeOpenAI([call, completed(1)], [text("ok"), completed(1)])
    await run(make_backend(openai, dealer), ctx(roles=["TestDrive.Book"]))
    assert dealer.booked == [("atlas", "Stockholm", "2030-01-01", "oid-anna")]


async def deltas_for(*chunks):
    openai = FakeOpenAI([*[text(c) for c in chunks], completed(1)])
    _, events = await run(make_backend(openai), ctx())
    return [e.data["text"] for e in events if e.type == "delta"]


async def test_citation_markers_are_rewritten_so_clients_see_plain_text():
    out = await deltas_for("Range is 400 km\u30105:0\u2020voltrieve-fjord-specifications.pdf\u3011. Done.")
    assert "".join(out) == "Range is 400 km (voltrieve-fjord-specifications.pdf). Done."


async def test_a_marker_split_over_deltas_is_held_until_it_closes():
    out = await deltas_for("Text \u30104:", "0\u2020voltrieve-", "atlas-brochure.docx", "\u3011 more")
    assert "".join(out) == "Text  (voltrieve-atlas-brochure.docx) more"
    assert not any("\u3010" in d or "\u2020" in d for d in out)
    # Nothing is held back from the client longer than the marker needs.
    assert out[0] == "Text "


async def test_a_marker_without_a_real_file_name_is_removed():
    out = await deltas_for("Fast\u30104:0\u2020source\u3011 charging\u30101:2\u2020\u3011.")
    assert "".join(out) == "Fast charging."


async def test_an_unterminated_marker_is_released_when_the_turn_ends():
    out = await deltas_for("Almost \u30105:0\u2020voltr")
    assert "".join(out) == "Almost \u30105:0\u2020voltr"


async def test_non_text_events_pass_through_the_citation_filter():
    openai = FakeOpenAI([text("a\u3010x\u2020f.pdf\u3011"), completed(1)])
    _, events = await run(make_backend(openai), ctx())
    assert {"trace"} <= {e.type for e in events}


async def test_unsupported_tool_error_over_http(validator, auth):
    backend = make_backend(FakeOpenAI())
    settings = Settings(agent_backend="prompt")
    app = create_app(settings, validator, BackendRegistry(settings, {"prompt": lambda s: backend}), TurnStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/chat",
            headers=auth,
            json={
                "message": "x",
                "client_tools": [{"name": "read_file", "description": "d", "parameters": {"type": "object"}}],
            },
        )
    events = parse_sse(r.text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "unsupported_client_tool"


def test_prompt_backend_is_listed_and_names_match_the_agent_script():
    from app.backends import BACKEND_FACTORIES

    assert "prompt" in BACKEND_NAMES and "prompt" in BACKEND_FACTORIES
    script = Path(__file__).parents[2] / "agents" / "prompt" / "create_agents.py"
    spec = importlib.util.spec_from_file_location("create_agents", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {t["name"] for t in module.CLI_TOOLS} == CLI_AGENT_TOOL_NAMES
    cli = [t.name for t in module.agent_definition("m", "https://s", "conn", "parts-conn", True).tools if t.type == "function"]
    web = [t.name for t in module.agent_definition("m", "https://s", "conn", "parts-conn", False).tools if t.type == "function"]
    assert not set(KB_SEARCH_TOOLS) & set(cli + web)
    mcp = [t for t in module.agent_definition("m", "https://s", "conn", "parts-conn", False).tools
           if t.type == "mcp"]
    assert [t.server_label for t in mcp] == ["voltrieve-kb", "voltrieve-parts-kb"]
    assert [t.project_connection_id for t in mcp] == ["conn", "parts-conn"]
    assert "/knowledgebases/voltrieve-parts-kb/mcp" in mcp[1].server_url
    assert "article numbers" in mcp[1].server_description
    assert set(cli) - set(web) == CLI_AGENT_TOOL_NAMES
    assert {"check_stock", "get_prices", "book_test_drive"} <= set(web)
