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


def test_honk_plays_and_caps():
    played = []

    def play():
        played.append(1)
        return True

    assert tools.honk(2, play=play) == "Honked 2 time(s)."
    assert tools.honk(50, play=play) == f"Honked {tools.MAX_HONKS} time(s)."
    assert len(played) == 2 + tools.MAX_HONKS
    assert tools.honk("loud", play=play).startswith("error")


def test_honk_falls_back_when_the_computer_has_no_sound(monkeypatch):
    rung = []
    monkeypatch.setattr(tools, "_bell", lambda: rung.append(1))
    assert "cannot play sound" in tools.honk(1, play=lambda: False)
    assert rung == [1]


def test_the_horn_is_a_short_sound():
    assert len(tools._horn_samples()) == int(tools.HONK_SECONDS * tools.SAMPLE_RATE) * 2


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
    assert [t["name"] for t in tools.CLIENT_TOOLS] == ["make_noise", "honk", "get_local_time", "show_banner", "set_gauge"]


def test_config_env_and_azd(monkeypatch):
    env = {"VOLTRIEVE_API_URL": "https://x/", "VOLTRIEVE_TENANT_ID": "t"}
    azd = parse_env_values('CLI_CLIENT_ID="c"\nAPI_CLIENT_ID="a"\n# note\n')
    s = load_settings(env, azd)
    assert (s.api_url, s.cli_client_id, s.scope) == ("https://x", "c", "api://a/access_as_user")
    with pytest.raises(ConfigError):
        load_settings({}, {})


def test_config_reads_the_azd_names_so_nothing_is_exported_under_azd():
    azd = parse_env_values(
        'API_URL="https://api.example/"\nTENANT_ID="t"\nCLI_CLIENT_ID="c"\nAPI_CLIENT_ID="a"\nOTHER="x"\n'
    )
    s = load_settings({}, azd)
    assert (s.api_url, s.tenant_id, s.cli_client_id, s.api_client_id) == ("https://api.example", "t", "c", "a")
    # A VOLTRIEVE_* variable still wins over the azd value.
    assert load_settings({"VOLTRIEVE_API_URL": "http://localhost:8000"}, azd).api_url == "http://localhost:8000"


def test_config_error_names_the_variables_to_set():
    with pytest.raises(ConfigError, match="VOLTRIEVE_API_URL"):
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
    assert chat_call[1]["message"] == "beep" and len(chat_call[1]["client_tools"]) == 5
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
    assert [l["event"] for l in lines] == ["turn_started", "delta", "done"]


def test_ask_error_event_exits_nonzero(monkeypatch):
    def handler(request):
        return httpx.Response(200, text=sse(("error", {"code": "denied", "message": "no"})))

    monkeypatch.setattr("voltrieve_cli.main._client", lambda b, a: ApiClient("http://api", "t", transport=httpx.MockTransport(handler)))
    assert CliRunner().invoke(app, ["ask", "q", "--json"]).exit_code == 1


def test_chat_view_renders_narrow_and_wide():
    from rich.console import Console
    for width in (60, 140):
        console = Console(width=width, height=30, record=True, force_terminal=False)
        with ChatView(console, show_trace=True) as view:
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


def test_one_correlation_id_covers_every_request_of_a_turn():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-correlation-id"))
        if request.url.path == "/chat":
            return httpx.Response(200, text=sse(("client_tool_calls", {"conversation_id": "c", "turn_id": "t", "calls": [
                {"call_id": "1", "name": "get_local_time", "arguments": {}}]})))
        return httpx.Response(200, text=sse(("done", {"conversation_id": "c", "turn_id": "t", "backend": "loop", "usage": {}})))

    client = ApiClient("http://api", "tok", transport=httpx.MockTransport(handler))
    events = []
    first = run_turn(client, "q", None, lambda n, d: events.append((n, d)))
    second = run_turn(client, "again", "c", lambda n, d: None)
    assert len(seen) == 4 and seen[0] == seen[1] == first.correlation_id
    assert seen[2] == seen[3] == second.correlation_id and second.correlation_id != first.correlation_id
    assert len(first.correlation_id) >= 32
    assert events[0] == ("turn_started", {"correlation_id": first.correlation_id})


def test_network_failures_become_api_errors_in_both_commands(monkeypatch):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    def breaks_midway(request):
        class Broken(httpx.SyncByteStream):
            def __iter__(self):
                yield b"event: delta\ndata: {\"text\": \"hi\"}\n\n"
                raise httpx.ReadError("connection reset")

        return httpx.Response(200, stream=Broken())

    for handler in (down, breaks_midway):
        client = ApiClient("http://api", "t", transport=httpx.MockTransport(handler))
        with pytest.raises(ApiError, match="failed"):
            run_turn(client, "q", None, lambda n, d: None)

        monkeypatch.setattr("voltrieve_cli.main._client",
                            lambda b, a, h=handler: ApiClient("http://api", "t", transport=httpx.MockTransport(h)))
        asked = CliRunner().invoke(app, ["ask", "q"])
        assert asked.exit_code == 1 and "Traceback" not in asked.output
        chat = CliRunner().invoke(app, ["chat"], input="hello\n\n")
        assert chat.exit_code == 0 and "Traceback" not in chat.output and "failed" in chat.output


def test_control_characters_from_the_model_never_reach_the_terminal(monkeypatch):
    from voltrieve_cli.render import clean

    assert clean("a\x1b[2Jb\x07c\r\nd\te\x9bf\x7f") == "a[2Jbc\nd\tef"

    def handler(request):
        return httpx.Response(200, text=sse(("delta", {"text": "safe\x1b]0;pwned\x07 text"}),
                                            ("error", {"code": "x\x1b", "message": "m\x1b[31m"}),
                                            ("done", {"conversation_id": "c", "turn_id": "t", "backend": "p", "usage": {}})))

    monkeypatch.setattr("voltrieve_cli.main._client",
                        lambda b, a: ApiClient("http://api", "t", transport=httpx.MockTransport(handler)))
    result = CliRunner().invoke(app, ["ask", "q"])
    assert "\x1b" not in result.output and "\x07" not in result.output
    assert "safe]0;pwned text" in result.stdout


def test_chat_view_cleans_control_characters_and_shows_the_correlation_id():
    from rich.console import Console

    console = Console(width=140, height=30, record=True, force_terminal=False)
    with ChatView(console, show_trace=True) as view:
        view.user("hello")
        view.on_event("turn_started", {"correlation_id": "abc-123"})
        view.on_event("delta", {"text": "hi\x1b[2J there"})
        view.on_event("trace", {"step": "s\x1b", "component": "api", "detail": "d\x07", "elapsed_ms": 1})
        view.show_banner("ban\x1bner")
    out = console.export_text()
    assert "abc-123" in out and "hi[2J there" in out and "banner" in out
    assert "\x1b" not in out and "\x07" not in out


class FakeMsal:
    """Stands in for msal.PublicClientApplication."""

    def __init__(self, accounts=()):
        self.accounts = list(accounts)
        self.interactive = []
        self.silent = []
        self.removed = []

    def get_accounts(self):
        return list(self.accounts)

    def acquire_token_silent(self, scopes, account):
        self.silent.append((scopes, account))
        return {"access_token": "cached"}

    def acquire_token_interactive(self, scopes, **kwargs):
        self.interactive.append((scopes, kwargs))
        return {"access_token": "fresh"}

    def remove_account(self, account):
        self.removed.append(account)
        self.accounts.remove(account)


SETTINGS = load_settings({"VOLTRIEVE_API_URL": "http://a", "VOLTRIEVE_TENANT_ID": "t",
                          "VOLTRIEVE_CLI_CLIENT_ID": "c", "VOLTRIEVE_API_CLIENT_ID": "api"}, {})


def test_login_always_shows_the_account_picker_and_skips_the_cache(monkeypatch):
    from voltrieve_cli import auth

    fake = FakeMsal(accounts=[{"username": "old@example.com"}])
    monkeypatch.setattr(auth, "_build_app", lambda settings: fake)
    auth.login(SETTINGS)
    assert fake.silent == []
    assert fake.interactive == [(["api://api/access_as_user"], {"prompt": "select_account"})]
    # Ordinary commands still use the cache.
    assert auth.get_token(SETTINGS, interactive=False) == "cached"


def test_logout_forgets_every_cached_account(monkeypatch):
    from voltrieve_cli import auth

    fake = FakeMsal(accounts=[{"username": "a"}, {"username": "b"}])
    monkeypatch.setattr(auth, "_build_app", lambda settings: fake)
    monkeypatch.setattr("voltrieve_cli.main.load_settings", lambda: SETTINGS)
    result = CliRunner().invoke(app, ["logout"])
    assert result.exit_code == 0 and "Signed out" in result.output
    assert len(fake.removed) == 2 and fake.get_accounts() == []
    assert "Nothing to sign out of" in CliRunner().invoke(app, ["logout"]).output


def test_login_command_uses_the_fresh_sign_in(monkeypatch):
    from voltrieve_cli import auth

    fake = FakeMsal(accounts=[{"username": "old"}])
    monkeypatch.setattr(auth, "_build_app", lambda settings: fake)
    monkeypatch.setattr("voltrieve_cli.main.load_settings", lambda: SETTINGS)
    result = CliRunner().invoke(app, ["login"])
    assert result.exit_code == 0 and "Signed in" in result.output and fake.interactive
