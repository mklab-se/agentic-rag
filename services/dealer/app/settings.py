from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Dealer service configuration, read from TENANT_ID, DEALER_CLIENT_ID and LOG_LEVEL, and
    optionally APPLICATIONINSIGHTS_CONNECTION_STRING."""

    tenant_id: str
    dealer_client_id: str
    log_level: str = "INFO"
    applicationinsights_connection_string: str = ""
