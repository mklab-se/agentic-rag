import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from voltrieve_agent.dealer import DealerClient
from voltrieve_agent.knowledge import KnowledgeBase
from voltrieve_agent.server_tools import build_server_tools
from voltrieve_agent.tools import ToolSet, UserContext, current_correlation_id

BASE = "https://dealer.test"


class FakeKnowledgeBase:
    def __init__(self):
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        return json.dumps({"chunks": [{"title": "Manual"}]})


@pytest.fixture
async def tools():
    async def token():
        return "tok"

    async with httpx.AsyncClient() as http:
        dealer = DealerClient(BASE, token, http)
        kb = FakeKnowledgeBase()
        yield ToolSet(build_server_tools(dealer, kb), []), kb


@pytest.fixture
def booker():
    return UserContext("oid-anna", "anna@example.com", frozenset({"TestDrive.Book"}))


@respx.mock
async def test_booking_requester_comes_from_user_not_model(tools, booker, events):
    route = respx.post(f"{BASE}/test-drives").respond(201, json={"booking_id": "B1"})
    args = {"model": "atlas", "city": "Stockholm", "date": "2999-01-01", "requester": "mallory"}
    out = await tools[0].execute("book_test_drive", json.dumps(args), booker, events)
    # the schema forbids a model-supplied requester, so the call is rejected outright
    assert out.startswith("Error: invalid arguments") and not route.called
    del args["requester"]
    out = await tools[0].execute("book_test_drive", json.dumps(args), booker, events)
    assert json.loads(out) == {"booking_id": "B1"}
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"model": "atlas", "city": "Stockholm", "date": "2999-01-01", "requester": "oid-anna"}
    assert route.calls.last.request.headers["authorization"] == "Bearer tok"


@respx.mock
async def test_422_becomes_readable_output(tools, booker, events):
    respx.post(f"{BASE}/test-drives").respond(422, json={"detail": "Invalid booking: no such city"})
    args = {"model": "atlas", "city": "Stockholm", "date": "2999-01-01"}
    out = await tools[0].execute("book_test_drive", json.dumps(args), booker, events)
    assert "rejected" in out and "no such city" in out


@respx.mock
async def test_5xx_becomes_readable_output(tools, user, events):
    respx.get(f"{BASE}/stock").respond(503)
    out = await tools[0].execute("check_stock", "{}", user, events)
    assert "unavailable" in out and "503" in out


@respx.mock
async def test_connection_error_becomes_readable_output(tools, user, events):
    respx.get(f"{BASE}/prices").mock(side_effect=httpx.ConnectError("nope"))
    out = await tools[0].execute("get_prices", "{}", user, events)
    assert "could not be reached" in out


@respx.mock
async def test_correlation_id_is_sent(tools, user, events):
    route = respx.get(f"{BASE}/stock").respond(200, json={"rows": []})
    reset = current_correlation_id.set("turn-42")
    try:
        await tools[0].execute("check_stock", '{"model": "atlas", "city": "Stockholm"}', user, events)
    finally:
        current_correlation_id.reset(reset)
    request = route.calls.last.request
    assert request.headers["x-correlation-id"] == "turn-42"
    assert dict(request.url.params) == {"model": "atlas", "city": "Stockholm"}


@respx.mock
async def test_correlation_id_generated_when_absent(tools, user, events):
    route = respx.get(f"{BASE}/prices").respond(200, json={})
    await tools[0].execute("get_prices", '{"market": "EU"}', user, events)
    assert route.calls.last.request.headers["x-correlation-id"]
    assert route.calls.last.request.url.params["market"] == "EU"


async def test_book_test_drive_requires_role(tools, user, events):
    args = '{"model": "atlas", "city": "Stockholm", "date": "2999-01-01"}'
    out = await tools[0].execute("book_test_drive", args, user, events)
    assert out.startswith("Refused")
    assert [e.data["step"] for e in events.events] == ["authorization_denied"]
    names = [d["name"] for d in tools[0].definitions(user)]
    assert "book_test_drive" in names and "search_voltrieve_docs" in names


async def test_search_tool_delegates_to_knowledge_base(tools, user, events):
    out = await tools[0].execute("search_voltrieve_docs", '{"query": "range"}', user, events)
    assert tools[1].queries == ["range"]
    assert json.loads(out)["chunks"][0]["title"] == "Manual"


async def test_knowledge_base_traces_sub_queries_and_titles(monkeypatch, user, events):
    from voltrieve_search.retrieve import Chunk, Reference, RetrieveResult

    result = RetrieveResult(
        chunks=[Chunk("0", "V1 Manual", "Range is 500 km")],
        references=[Reference("0", "k1", 2.0, None)],
        activity=[
            {"type": "modelQueryPlanning", "inputTokens": 10},
            {"type": "searchIndex", "searchIndexArguments": {"search": "v1 range"}},
            {"type": "searchIndex", "searchIndexArguments": {"search": "battery capacity"}},
        ],
    )
    seen = {}

    def fake_retrieve(client, kb_name, question):
        seen.update(kb_name=kb_name, question=question)
        return result

    monkeypatch.setattr("voltrieve_agent.knowledge.retrieve", fake_retrieve)
    credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="t"))
    kb = KnowledgeBase("https://search.test", credential)

    from voltrieve_agent.tools import ServerTool

    async def handler(args, u):
        return await kb.search(args["q"])

    ts = ToolSet(
        [ServerTool("s", "d", {"type": "object", "properties": {"q": {"type": "string"}}}, handler)],
        [],
    )
    out = await ts.execute("s", '{"q": "range?"}', user, events)
    assert seen == {"kb_name": "voltrieve-kb", "question": "range?"}
    assert json.loads(out)["chunks"] == [{"ref_id": "0", "title": "V1 Manual", "content": "Range is 500 km"}]
    (event,) = events.events
    assert event.data["step"] == "knowledge_base_retrieved"
    assert event.data["sub_queries"] == ["v1 range", "battery capacity"]
    assert event.data["references"] == ["V1 Manual"]
