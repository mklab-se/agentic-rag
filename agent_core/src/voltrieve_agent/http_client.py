"""The HTTP client that calls the dealer service and the hosted agent."""

import httpx


def make_http_client() -> httpx.AsyncClient:
    """An httpx client whose requests carry W3C traceparent through OpenTelemetry."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    client = httpx.AsyncClient(timeout=45.0)  # the dealer scales to zero, so allow for a cold start
    HTTPXClientInstrumentor.instrument_client(client)
    return client
