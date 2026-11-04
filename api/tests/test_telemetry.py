import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from voltrieve_agent.events import AgentEvent, trace
from voltrieve_agent.loop import TurnOutcome

from app import telemetry
from app.backends import BackendRegistry
from app.logging_setup import JsonFormatter
from app.main import create_app
from app.settings import Settings
from app.turns import TurnStore
from tests.conftest import answer, parse_sse


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "tracer", provider.get_tracer("test"))
    return exporter


def test_telemetry_is_off_without_connection_string(monkeypatch):
    calls = []
    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", lambda **kw: calls.append(kw))
    assert telemetry.configure_telemetry("") is False
    assert calls == []


def test_telemetry_starts_with_connection_string(monkeypatch):
    calls = []
    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", lambda **kw: calls.append(kw))
    assert telemetry.configure_telemetry("InstrumentationKey=k") is True
    assert calls == [{"connection_string": "InstrumentationKey=k", "enable_live_metrics": False}]


def test_app_starts_with_and_without_connection_string(monkeypatch, validator, backend):
    calls = []
    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", lambda **kw: calls.append(kw))
    registry = BackendRegistry(Settings(), {"loop": lambda s: backend})
    create_app(Settings(applicationinsights_connection_string=""), validator, registry, TurnStore())
    assert calls == []
    create_app(
        Settings(applicationinsights_connection_string="InstrumentationKey=k"),
        validator,
        registry,
        TurnStore(),
    )
    assert len(calls) == 1


async def test_turn_span_carries_ids_and_correlation_id(client, auth, backend, spans):
    backend.script = [answer("Hi")]
    r = await client.post(
        "/chat", headers={**auth, "X-Correlation-Id": "cid-42"}, json={"message": "hello"}
    )
    done = parse_sse(r.text)[-1][1]
    [span] = [s for s in spans.get_finished_spans() if s.name == "chat.turn"]
    assert dict(span.attributes) == {
        "conversation_id": done["conversation_id"],
        "turn_id": done["turn_id"],
        "backend": "loop",
        "correlation_id": "cid-42",
        "user_oid": "oid-anna",
    }


def test_payload_is_truncated_and_only_logged_at_debug(caplog):
    log = logging.getLogger("payload-test")
    with caplog.at_level(logging.INFO, logger="payload-test"):
        telemetry.debug_payload(log, "turn input", "x" * 2000)
    assert caplog.records == []
    with caplog.at_level(logging.DEBUG, logger="payload-test"):
        telemetry.debug_payload(log, "turn input", "x" * 2000)
    [record] = caplog.records
    message = json.loads(JsonFormatter().format(record))["message"]
    assert len(message) < 600 and "1500 more characters" in message


def tool_round_trip():
    async def run(ctx, emit):
        await emit(trace("model_called", "model", "iteration 1"))
        await emit(
            trace("server_tool_called", "tools", "check_stock", tool="check_stock",
                  arguments='{"city": "Malmo", "secret": "ARG-VALUE"}')
        )
        await emit(
            trace("server_tool_returned", "tools", "check_stock", tool="check_stock",
                  output_preview="OUTPUT-VALUE")
        )
        await emit(AgentEvent("delta", {"text": "Two in stock."}))
        return TurnOutcome("done", [], {})

    return run


class FormattedLines(logging.Handler):
    """Formats each record as it is logged, while the request's log context is still set."""

    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


async def test_every_hop_of_a_tool_round_trip_is_a_log_line(client, auth, backend):
    backend.script = [tool_round_trip()]
    handler = FormattedLines()
    logging.getLogger("app.turns").addHandler(handler)
    try:
        await client.post("/chat", headers={**auth, "X-Correlation-Id": "cid-7"}, json={"message": "hi"})
    finally:
        logging.getLogger("app.turns").removeHandler(handler)
    lines = [line for line in handler.lines if line["message"] == "trace"]
    steps = [(line["step"], line["component"]) for line in lines]
    assert steps == [
        ("token_validated", "auth"),
        ("backend_selected", "api"),
        ("conversation_created", "api"),
        ("model_called", "model"),
        ("server_tool_called", "tools"),
        ("server_tool_returned", "tools"),
    ]
    called = lines[4]
    assert called["detail"] == "check_stock" and called["elapsed_ms"] >= 0
    assert all(
        line["backend"] == "loop" and line["user_oid"] == "oid-anna" and line["correlation_id"] == "cid-7"
        for line in lines
    )
    # Arguments and results stay out of info logs.
    everything = " ".join(json.dumps(line) for line in lines)
    assert "ARG-VALUE" not in everything and "OUTPUT-VALUE" not in everything


async def test_arguments_and_results_are_logged_at_debug_only(client, auth, backend, caplog):
    backend.script = [tool_round_trip()]
    with caplog.at_level(logging.DEBUG, logger="app.turns"):
        await client.post("/chat", headers=auth, json={"message": "hi"})
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)
    assert "ARG-VALUE" in text and "OUTPUT-VALUE" in text


async def test_every_hop_is_a_span_event(client, auth, backend, spans):
    backend.script = [tool_round_trip()]
    await client.post("/chat", headers=auth, json={"message": "hi"})
    [span] = [s for s in spans.get_finished_spans() if s.name == "chat.turn"]
    events = {e.name: dict(e.attributes) for e in span.events}
    assert {"token_validated", "server_tool_called", "server_tool_returned"} <= set(events)
    assert events["server_tool_called"]["component"] == "tools"
    assert events["server_tool_called"]["detail"] == "check_stock"
    assert "ARG-VALUE" not in json.dumps(events)
