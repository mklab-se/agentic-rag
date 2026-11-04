import json

from voltrieve_agent.tools import ClientTool, ServerTool, ToolSet

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
    assert [d["name"] for d in toolset.definitions()] == ["lookup", "book", "pick_file"]
    assert all(d["type"] == "function" for d in toolset.definitions())
    assert toolset.is_client("pick_file") and not toolset.is_client("lookup")


def test_client_arguments_are_validated_against_the_clients_schema():
    schema = {
        "type": "object",
        "properties": {"times": {"type": "integer", "minimum": 1, "maximum": 10}},
        "required": ["times"],
    }
    toolset = ToolSet([], [ClientTool("make_noise", "Ring", schema)])
    assert toolset.validate_client("make_noise", '{"times": 3}') is None
    assert toolset.validate_client("make_noise", "{bad") .startswith("Error: arguments for 'make_noise' are not valid JSON")
    for bad in ('{}', '{"times": 99}', '{"times": "x"}', '[]'):
        assert toolset.validate_client("make_noise", bad).startswith("Error: invalid arguments for 'make_noise'")
    assert "times" in toolset.validate_client("make_noise", '{"times": 99}')


async def test_role_denied_is_logged_as_warning(user, events, caplog):
    toolset = ToolSet([make_tool([], role="Admin")], [])
    with caplog.at_level("WARNING", logger="voltrieve_agent.tools"):
        await toolset.execute("lookup", '{"city": "x"}', user, events)
    record = next(r for r in caplog.records if "authorization denied" in r.getMessage())
    assert record.levelname == "WARNING"
    assert "lookup" in record.getMessage() and "Admin" in record.getMessage() and user.oid in record.getMessage()
