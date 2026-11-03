import json

from httpx import ASGITransport, AsyncClient
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import telemetry
from app.main import create_app
from app.settings import Settings

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
TRACEPARENT = f"00-{TRACE_ID}-b7ad6b7169203331-01"


def test_telemetry_is_off_without_connection_string(monkeypatch):
    calls = []
    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", lambda **kw: calls.append(kw))
    assert telemetry.configure_telemetry("") is False
    assert calls == []


def test_app_starts_with_and_without_connection_string(monkeypatch, settings, validator):
    calls = []
    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", lambda **kw: calls.append(kw))
    create_app(settings, validator)
    assert calls == []
    with_telemetry = Settings(applicationinsights_connection_string="InstrumentationKey=k")
    create_app(with_telemetry, validator)
    assert calls == [{"connection_string": "InstrumentationKey=k"}]


async def test_inbound_traceparent_is_honoured_and_correlation_id_recorded(settings, validator):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app(settings, validator)
    # What the Azure Monitor distro does to FastAPI apps, with an in-memory exporter.
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(
                "/healthz", headers={"traceparent": TRACEPARENT, "X-Correlation-Id": "cid-7"}
            )
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
    assert r.status_code == 200
    spans = [s for s in exporter.get_finished_spans() if s.attributes.get("correlation_id")]
    assert spans and all(f"{s.context.trace_id:032x}" == TRACE_ID for s in spans)
    assert spans[0].attributes["correlation_id"] == "cid-7"


async def test_logs_keep_the_correlation_id(settings, validator, capsys):
    app = create_app(settings, validator)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.get("/healthz", headers={"X-Correlation-Id": "cid-9"})
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    access = [e for e in lines if e["message"] == "request"]
    assert access and access[0]["correlation_id"] == "cid-9"
