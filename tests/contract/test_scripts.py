"""The helper scripts under scripts/ that have logic worth a test: evidence files and the smoke test."""

import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smoke  # noqa: E402
import voltrieve_client  # noqa: E402
from voltrieve_client import evidence_text, write_evidence  # noqa: E402


def test_evidence_text_replaces_em_dashes_and_strips_absolute_paths():
    root = str(voltrieve_client.ROOT)
    text = f"A \u2014 B. Saved {root}/docs/evidence/x.json and /Users/someone/secret/file.txt, C:\\Users\\bob\\f.txt."
    cleaned = evidence_text(text)
    assert "\u2014" not in cleaned and "A - B." in cleaned
    assert "Saved docs/evidence/x.json" in cleaned
    assert "someone" not in cleaned and "bob" not in cleaned and "/Users" not in cleaned
    assert cleaned.count("<path>") == 2


def test_evidence_text_leaves_model_output_otherwise_verbatim():
    text = "G\u00f6teborg \u2013 2\u00a0100 kg \u30105:0\u2020file.pdf\u3011 **bold**"
    assert evidence_text(text) == text


def test_write_evidence_applies_it(tmp_path):
    path = write_evidence(tmp_path / "out" / "x.txt", "a \u2014 b\n")
    assert path.read_text() == "a - b\n"


def test_the_fact_checks_see_the_answer_a_client_sees():
    pytest.importorskip("yaml")
    import voltrieve_facts

    # A citation marker is no longer stripped: the backends filter it, so the checks do not.
    assert "\u3010" in voltrieve_facts._normal("2100 kg \u30105:0\u2020f.pdf\u3011")


def sse(*events) -> str:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events)


def fake_deployment(indexer_status="success", failing_backend=None, healthy=True):
    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.path == "/healthz":
            return httpx.Response(200 if healthy or url.host != "dealer" else 503, json={"status": "ok"})
        if url.path.endswith("/status"):
            assert request.headers["authorization"] == "Bearer search-token"
            return httpx.Response(200, json={"lastResult": {"status": indexer_status, "itemsFailed": 0}})
        assert url.path == "/chat"
        if request.headers["x-agent-backend"] == failing_backend:
            return httpx.Response(200, text=sse(("error", {"code": "agent_unavailable", "message": "x"})))
        return httpx.Response(200, text=sse(
            ("delta", {"text": "2100 kg"}),
            ("done", {"conversation_id": "c", "turn_id": "t", "backend": "loop", "usage": {}})))

    return handler


def run(handler, backends=("prompt", "loop", "hosted")):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    original = voltrieve_client.httpx.Client
    # Api builds its own client: route it through the same mock transport.
    voltrieve_client.httpx.Client = lambda **kw: original(**{**kw, "transport": transport})
    try:
        return smoke.run_checks(
            "https://api", "https://dealer", "https://search", lambda: "search-token", lambda: "user-token",
            list(backends), http,
        )
    finally:
        voltrieve_client.httpx.Client = original


def test_smoke_checks_health_indexer_and_one_turn_per_backend():
    results = run(fake_deployment())
    assert [name for name, _, _ in results] == [
        "api /healthz", "dealer /healthz", "search indexer", "turn on prompt", "turn on loop", "turn on hosted",
    ]
    assert all(ok for _, ok, _ in results), results


def test_smoke_reports_each_kind_of_failure():
    by_name = {n: ok for n, ok, _ in run(fake_deployment(indexer_status="transientFailure", failing_backend="hosted"))}
    assert by_name["search indexer"] is False
    assert by_name["turn on hosted"] is False
    assert by_name["turn on loop"] is True and by_name["api /healthz"] is True


def test_smoke_survives_an_unreachable_service():
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    results = run(down, backends=("loop",))
    assert [ok for _, ok, _ in results] == [False, False, False, False]
