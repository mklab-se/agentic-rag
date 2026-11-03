import logging

logger = logging.getLogger(__name__)


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
