import json

from voltrieve_agent.tools import ClientTool, ServerTool, ToolSet, UserContext

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}


def make_tool(calls, role=None):
    async def handler(args, user):
        calls.append((args, user))
        return f"ok {args['city']}"

    return ServerTool("lookup", "Look up", SCHEMA, handler, required_role=role)


async def test_executes_with_valid_arguments(user, events):
    calls = []
    toolset = ToolSet([make_tool(calls)], [])
    out = await toolset.execute("lookup", json.dumps({"city": "Oslo"}), user, events)
    assert out == "ok Oslo"
    assert calls == [({"city": "Oslo"}, user)]


async def test_invalid_arguments_skip_handler(user, events):
    calls = []
    toolset = ToolSet([make_tool(calls)], [])
    out = await toolset.execute("lookup", json.dumps({"town": "Oslo"}), user, events)
    assert out.startswith("Error: invalid arguments")
    assert calls == []


async def test_malformed_json_is_an_error_output(user, events):
    toolset = ToolSet([make_tool([])], [])
    out = await toolset.execute("lookup", "{nope", user, events)
    assert "not valid JSON" in out


async def test_handler_exception_becomes_output(user, events):
    async def boom(args, user):
        raise RuntimeError("down")

    toolset = ToolSet([ServerTool("lookup", "d", SCHEMA, boom)], [])
    out = await toolset.execute("lookup", '{"city": "x"}', user, events)
    assert "failed" in out and "RuntimeError" not in out and "down" not in out


async def test_role_denied_refuses_and_traces(user, events):
    calls = []
    toolset = ToolSet([make_tool(calls, role="Admin")], [])
    out = await toolset.execute("lookup", '{"city": "x"}', user, events)
    assert out.startswith("Refused")
    assert calls == []
    assert [e.data["step"] for e in events.events] == ["authorization_denied"]


async def test_date_format_is_enforced(user, events):
    calls = []

    async def handler(args, u):
        calls.append(args)
        return "ok"

    schema = {"type": "object", "properties": {"d": {"type": "string", "format": "date"}}}
    toolset = ToolSet([ServerTool("t", "d", schema, handler)], [])
    out = await toolset.execute("t", '{"d": "tomorrow"}', user, events)
    assert out.startswith("Error: invalid arguments") and calls == []


async def test_unknown_tool(user, events):
    out = await ToolSet([], []).execute("nope", "{}", user, events)
    assert "unknown tool" in out


def test_definitions_list_every_server_tool_whatever_the_role(user):
    toolset = ToolSet(
        [make_tool([]), ServerTool("book", "d", SCHEMA, None, required_role="Admin")],
        [ClientTool("pick_file", "Pick", {"type": "object", "properties": {}})],
    )
    assert [d["name"] for d in toolset.definitions(user)] == ["lookup", "book", "pick_file"]
    admin = UserContext("o", "u", frozenset({"Admin"}))
    assert [d["name"] for d in toolset.definitions(admin)] == ["lookup", "book", "pick_file"]
    assert all(d["type"] == "function" for d in toolset.definitions(admin))
    assert toolset.is_client("pick_file") and not toolset.is_client("lookup")
