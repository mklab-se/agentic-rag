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


def _routing():
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("routing_check", root / "tests" / "routing" / "check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


class _Trace:
    done = None

    def __init__(self, *events):
        self.events = events

    def trace(self, step):
        return [d for s, d in self.events if s == step]


def test_routing_overlap_tells_parallel_from_sequential():
    routing = _routing()
    together = [{"started_ms": 100, "finished_ms": 900}, {"started_ms": 200, "finished_ms": 800}]
    in_turn = [{"started_ms": 100, "finished_ms": 500}, {"started_ms": 500, "finished_ms": 800}]
    assert routing.overlap(together) is True
    assert routing.overlap(in_turn) is False
    assert routing.overlap([{"started_ms": None, "finished_ms": 1}] * 2) is False


def test_routing_reads_mcp_calls_and_tool_calls_the_same_way():
    routing = _routing()
    mcp = routing.Run("prompt", "q", "both", 1, expected=["docs", "parts"])
    routing.read_trace(mcp, _Trace(
        ("model_called", {}),
        ("mcp_tool_called", {"server": "voltrieve-kb", "started_ms": 10, "finished_ms": 90}),
        ("mcp_tool_called", {"server": "voltrieve-parts-kb", "started_ms": 20, "finished_ms": 80}),
    ))
    loop = routing.Run("loop", "q", "both", 1, expected=["docs", "parts"])
    routing.read_trace(loop, _Trace(
        ("model_called", {}), ("model_called", {}),
        ("tools_parallel_started", {}),
        ("server_tool_called", {"tool": "search_voltrieve_docs", "iteration": 1}),
        ("server_tool_called", {"tool": "search_spare_parts", "iteration": 1}),
        ("tools_parallel_finished", {"one_by_one_ms": 900, "wall_ms": 500}),
    ))
    assert mcp.right and mcp.together and loop.right and loop.together
    assert loop.saved_ms == 400 and loop.steps == 2


def test_routing_counts_a_sequential_pair_as_not_together():
    routing = _routing()
    run = routing.Run("loop", "q", "both", 1, expected=["docs", "parts"])
    routing.read_trace(run, _Trace(
        ("server_tool_called", {"tool": "search_voltrieve_docs", "iteration": 1}),
        ("server_tool_called", {"tool": "search_spare_parts", "iteration": 2}),
    ))
    assert run.right and run.together is False


def test_routing_flags_vain_and_missed_sources():
    routing = _routing()
    run = routing.Run("loop", "q", "docs", 1, expected=["docs"], used=["parts"])
    assert not run.right and run.vain == ["parts"] and run.missed == ["docs"]


def test_routing_questions_resolve_against_the_parts_index():
    routing = _routing()
    questions = routing.yaml.safe_load(routing.QUESTIONS.read_text())["questions"]
    index = json.loads(routing.INDEX.read_text())
    for question in questions:
        routing.message(question, index)
        if question["group"] == "both":
            assert routing.expected_articles(question, index)


def _facts():
    pytest.importorskip("yaml")
    pytest.importorskip("pydantic")
    import voltrieve_facts

    return voltrieve_facts, voltrieve_facts.load_catalog()


def _sek(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def test_trim_price_check_wants_the_total_or_both_parts():
    facts, cat = _facts()
    fjord = cat.by_slug("fjord")
    heath = next(c for c in fjord.colors if c.key == "heath")
    base, color = cat.trim_price(fjord, "Plus", "AWD", "SE"), cat.color_price(heath, "SE")
    expect = {"type": "trim_price", "model": "fjord", "trim": "Plus", "drive": "AWD", "color": "heath", "market": "SE"}
    assert facts.check(expect, f"The Fjord Plus AWD in Heath costs {_sek(base + color)} SEK.")[0]
    assert facts.check(expect, f"{_sek(base)} SEK, plus {_sek(color)} SEK for the Heath paint.")[0]
    assert not facts.check(expect, f"It costs {_sek(base)} SEK.")[0]


def test_pack_check_names_exactly_the_trims_that_include_it():
    facts, cat = _facts()
    expect = {"type": "pack_trims", "model": "fjord", "pack": "Sound"}
    assert facts.check(expect, "The Sound pack is included on the Fjord Prime only.")[0]
    assert not facts.check(expect, "The Sound pack is included on the Fjord Plus.")[0]


def test_financing_check_wants_the_monthly_payment_and_the_rate():
    facts, cat = _facts()
    fjord = cat.by_slug("fjord")
    x = cat.financing_example(cat.trim_price(fjord, "Plus", "RWD", "SE"), "SE")
    expect = {"type": "financing", "model": "fjord", "market": "SE"}
    rate = f"{x.nominal_rate * 100:.2f}"
    assert facts.check(expect, f"{_sek(x.monthly)} SEK per month at a nominal rate of {rate} %.")[0]
    assert not facts.check(expect, f"{_sek(x.monthly)} SEK per month at 3.9 %.")[0]


def test_field_check_wants_every_named_value():
    facts, cat = _facts()
    d = cat.by_slug("fjord").dimensions
    expect = {"type": "fields", "model": "fjord", "fields": ["dimensions.boot_l", "dimensions.boot_folded_l"]}
    assert facts.check(expect, f"{d.boot_l} litres, {_sek(d.boot_folded_l)} litres folded")[0]
    assert not facts.check(expect, f"{d.boot_l} litres")[0]


def test_wheel_check_wants_each_wheel_size_and_name():
    facts, cat = _facts()
    wheels = cat.by_slug("fjord").wheels
    expect = {"type": "wheels", "model": "fjord"}
    assert facts.check(expect, " and ".join(f"{w.inches} inch {w.name}" for w in wheels))[0]
    assert not facts.check(expect, f"{wheels[0].inches} inch {wheels[0].name}")[0]


def test_trim_adds_check_wants_each_added_item_and_pack():
    facts, cat = _facts()
    plus = next(t for t in cat.by_slug("fjord").trims if t.name == "Plus")
    expect = {"type": "trim_adds", "model": "fjord", "trim": "Plus"}
    full = "Fjord Plus adds " + ", ".join(plus.adds + [f"the {p} pack" for p in plus.includes_packs])
    assert facts.check(expect, full)[0]
    assert not facts.check(expect, "Fjord Plus adds " + plus.adds[0])[0]


def test_sales_checks_accept_the_usual_wording():
    facts, _ = _facts()
    adds = {"type": "trim_adds", "model": "fjord", "trim": "Plus"}
    assert facts.check(adds, "Power tailgate with hands-free opening, keyless entry, a 360-degree camera "
                             "and the Winter pack")[0]
    pack = {"type": "pack_trims", "model": "fjord", "pack": "Sound"}
    assert facts.check(pack, "The Sound pack is included on Fjord Prime. It's optional on Fjord Pure and Plus.")[0]


def test_pack_check_fails_an_answer_that_includes_the_wrong_trim():
    facts, _ = _facts()
    pack = {"type": "pack_trims", "model": "fjord", "pack": "Sound"}
    assert not facts.check(pack, "The Sound pack is included on the Fjord Plus and Prime, and is not on the Pure.")[0]
    assert facts.check(pack, "It is standard on the Fjord Prime, and not available as standard on Pure or Plus.")[0]
