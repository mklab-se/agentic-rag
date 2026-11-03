import json

import httpx
import pytest
from typer.testing import CliRunner

from voltrieve_cli import tools
from voltrieve_cli.api import ApiClient, ApiError, parse_sse, run_turn
from voltrieve_cli.render import ChatView
from voltrieve_cli.config import ConfigError, load_settings, parse_env_values
from voltrieve_cli.main import app


def sse(*events):
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events)


def test_parse_sse_basic_and_multiline_and_comments():
    text = ": keepalive\nevent: delta\ndata: {\"text\": \"hi\"}\n\nevent: trace\ndata: {\"a\":\ndata: 1}\n\ndata: plain\n\n"
    events = list(parse_sse(text.splitlines(keepends=True)))
    assert events[0] == ("delta", {"text": "hi"})
    assert events[1] == ("trace", {"a": 1})
    assert events[2] == ("message", {"raw": "plain"})


def test_parse_sse_trailing_event_without_blank_line():
    assert list(parse_sse(["event: done", 'data: {"x": 1}'])) == [("done", {"x": 1})]


def test_make_noise_caps_and_rejects():
    rung = []
    assert "10" in tools.make_noise(500, bell=lambda: rung.append(1))
    assert len(rung) == 10
    rung.clear()
    assert tools.make_noise(3, bell=lambda: rung.append(1)).startswith("Rang")
    assert len(rung) == 3
    for bad in ["abc", None, 2.5, {"a": 1}, True]:
        assert tools.make_noise(bad, bell=lambda: rung.append(1)).startswith("error")
    assert len(rung) == 3


def test_run_tool_accepts_json_string_and_reports_errors():
    assert tools.run_tool("make_noise", '{"times": 2}', bell=lambda: None).startswith("Rang")
    assert tools.run_tool("make_noise", "{not json").startswith("error")
    assert tools.run_tool("nope", {}).startswith("error: unknown")
    assert "T" in tools.run_tool("get_local_time", "")
    shown = []
    tools.run_tool("show_banner", {"text": "hello"}, banner=shown.append)
    assert shown == ["hello"]


def test_declared_tools():
    assert [t["name"] for t in tools.CLIENT_TOOLS] == ["make_noise", "get_local_time", "show_banner"]


def test_config_env_and_azd(monkeypatch):
    env = {"VOLTRIEVE_API_URL": "https://x/", "VOLTRIEVE_TENANT_ID": "t"}
    azd = parse_env_values('VOLTRIEVE_CLI_CLIENT_ID="c"\nVOLTRIEVE_API_CLIENT_ID="a"\n# note\n')
    s = load_settings(env, azd)
    assert (s.api_url, s.cli_client_id, s.scope) == ("https://x", "c", "api://a/.default")
    with pytest.raises(ConfigError):
        load_settings({}, {})


def test_pause_and_continue_flow():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, body, request.headers.get("x-agent-backend")))
        if request.url.path == "/chat":
            return httpx.Response(200, text=sse(
                ("trace", {"step": "model", "component": "api", "detail": "x", "elapsed_ms": 1}),
                ("client_tool_calls", {"conversation_id": "c1", "turn_id": "t1", "calls": [
                    {"call_id": "k1", "name": "make_noise", "arguments": "{\"times\": 99}"},
                    {"call_id": "k2", "name": "boom", "arguments": {}}]})))
        return httpx.Response(200, text=sse(
            ("delta", {"text": "Done "}), ("delta", {"text": "noise"}),
            ("done", {"conversation_id": "c1", "turn_id": "t1", "backend": "loop", "usage": {}})))

    client = ApiClient("http://api", "tok", backend="loop", transport=httpx.MockTransport(handler))
    events, bells = [], []
    outcome = run_turn(client, "beep", None, lambda n, d: events.append(n), bell=lambda: bells.append(1))
    assert len(bells) == 10
    assert outcome.text == "Done noise" and outcome.done["backend"] == "loop"
    assert outcome.conversation_id == "c1"
    assert events.count("tool_ran") == 2
    chat_call, results_call = seen
    assert chat_call[1]["message"] == "beep" and len(chat_call[1]["client_tools"]) == 3
    assert chat_call[2] == "loop"
    assert results_call[0] == "/chat/tool-results"
    r = results_call[1]["results"]
    assert results_call[1]["turn_id"] == "t1" and results_call[1]["conversation_id"] == "c1"
    assert r[0]["call_id"] == "k1" and r[1]["output"].startswith("error")


def test_ask_json_prints_event_lines(monkeypatch):
    def handler(request):
        return httpx.Response(200, text=sse(("delta", {"text": "hi"}),
                                            ("done", {"conversation_id": "c", "turn_id": "t", "backend": "prompt", "usage": {}})))

    real = ApiClient
    monkeypatch.setattr("voltrieve_cli.main._client", lambda b, a: real("http://api", "t", transport=httpx.MockTransport(handler)))
    result = CliRunner().invoke(app, ["ask", "q", "--json"])
    assert result.exit_code == 0
    lines = [json.loads(l) for l in result.stdout.strip().splitlines()]
    assert [l["event"] for l in lines] == ["delta", "done"]


def test_ask_error_event_exits_nonzero(monkeypatch):
    def handler(request):
        return httpx.Response(200, text=sse(("error", {"code": "denied", "message": "no"})))

    monkeypatch.setattr("voltrieve_cli.main._client", lambda b, a: ApiClient("http://api", "t", transport=httpx.MockTransport(handler)))
    assert CliRunner().invoke(app, ["ask", "q", "--json"]).exit_code == 1


def test_chat_view_renders_narrow_and_wide():
    from rich.console import Console
    for width in (60, 140):
        console = Console(width=width, height=30, record=True, force_terminal=False)
        with ChatView(console) as view:
            view.user("hello")
            view.on_event("trace", {"step": "model", "component": "api", "detail": "called", "elapsed_ms": 5})
            view.on_event("delta", {"text": "hi there"})
            view.show_banner("BANNER")
        out = console.export_text()
        assert "hi there" in out and "model" in out and "BANNER" in out


def test_ask_survives_markup_like_text(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if request.url.path == "/chat":
            return httpx.Response(200, text=sse(
                ("trace", {"step": "[/x]", "component": "[b]", "detail": "[/x]"}),
                ("client_tool_calls", {"conversation_id": "c", "turn_id": "t", "calls": [
                    {"call_id": "1", "name": "show_banner", "arguments": {"text": "[/x]"}}]})))
        return httpx.Response(200, text=sse(("delta", {"text": "[/x] ok"}),
                                            ("done", {"conversation_id": "c", "turn_id": "t", "backend": "p", "usage": {}})))

    monkeypatch.setattr("voltrieve_cli.main._client", lambda b, a: ApiClient("http://api", "t", transport=httpx.MockTransport(handler)))
    result = CliRunner().invoke(app, ["ask", "q"])
    assert result.exit_code == 0, result.output
    assert calls["n"] == 2 and "[/x] ok" in result.stdout


def test_http_error_raises_api_error():
    client = ApiClient("http://api", "t", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(ApiError):
        run_turn(client, "q", None, lambda n, d: None)


def test_max_rounds_limit():
    def handler(request):
        return httpx.Response(200, text=sse(("client_tool_calls", {"conversation_id": "c", "turn_id": "t", "calls": [
            {"call_id": "1", "name": "get_local_time", "arguments": {}}]})))

    client = ApiClient("http://api", "t", transport=httpx.MockTransport(handler))
    outcome = run_turn(client, "q", None, lambda n, d: None, max_rounds=3)
    assert outcome.error and "too many" in outcome.error["message"]
    assert len(outcome.tool_runs) == 3


def test_token_provider_called_per_request():
    tokens = iter(["a", "b"])
    seen = []
    client = ApiClient("http://api", lambda: next(tokens),
                       transport=httpx.MockTransport(lambda r: seen.append(r.headers["authorization"]) or httpx.Response(200, text="")))
    list(client.chat("x")); list(client.chat("y"))
    assert seen == ["Bearer a", "Bearer b"]
