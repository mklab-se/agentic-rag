import logging

from opentelemetry import trace

logger = logging.getLogger(__name__)


def configure_telemetry(connection_string: str) -> bool:
    """Send traces, logs and metrics to Application Insights when a connection string is set.

    The Azure Monitor distro instruments FastAPI, which continues the W3C trace context
    (`traceparent`) sent by the caller, so the dealer call shows up inside the API's trace.
    Without a connection string nothing is exported and the app runs as before.
    """
    if not connection_string:
        return False
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=connection_string, enable_live_metrics=False)
    logger.info("Azure Monitor telemetry enabled")
    return True


def annotate_span(**attributes: str | None) -> None:
    """Set attributes on the current span (a no-op when there is none or telemetry is off)."""
    span = trace.get_current_span()
    for key, value in attributes.items():
        if value:
            span.set_attribute(key, value)
