import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("voltrieve.api")

PAYLOAD_LIMIT = 500


def configure_telemetry(connection_string: str) -> bool:
    """Send traces, logs and metrics to Application Insights when a connection string is set.

    The Azure Monitor distro also instruments FastAPI and httpx, so W3C trace context flows
    from the client request to the dealer service and the model call.
    """
    if not connection_string:
        return False
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=connection_string)
    logger.info("Azure Monitor telemetry enabled")
    return True


def annotate_span(**attributes: str | None) -> None:
    """Set attributes on the current span (a no-op when there is none or telemetry is off)."""
    span = trace.get_current_span()
    for key, value in attributes.items():
        if value:
            span.set_attribute(key, value)


@contextmanager
def turn_span(**attributes: str | None) -> Iterator[trace.Span]:
    """A span around one chat turn, with conversation_id, turn_id, backend and correlation_id."""
    with tracer.start_as_current_span("chat.turn") as span:
        annotate_span(**attributes)
        yield span


def truncate(value: object, limit: int = PAYLOAD_LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else f"{text[:limit]}... [{len(text) - limit} more characters]"


def debug_payload(log: logging.Logger, label: str, payload: object) -> None:
    """Log a prompt or tool payload at debug level only, truncated. Never pass credentials."""
    if log.isEnabledFor(logging.DEBUG):
        log.debug("%s: %s", label, truncate(payload))
