import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
    assert calls == [{"connection_string": "InstrumentationKey=k"}]


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
