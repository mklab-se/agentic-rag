from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """API configuration, read from environment variables of the same (upper case) names."""

    tenant_id: str
    api_client_id: str
    agent_backend: str = "loop"
    cors_origins: str = ""  # comma separated list of allowed origins
    log_level: str = "INFO"
    applicationinsights_connection_string: str = ""

    # Needed by the loop backend; read lazily, so the API starts without them.
    foundry_project_endpoint: str = ""
    chat_deployment: str = "gpt-5.4-mini"
    search_endpoint: str = ""
    dealer_url: str = ""
    dealer_client_id: str = ""

    # Backend A: the project connection to the knowledge base MCP endpoint (used when the agents
    # are created) and the names of the two prompt agents the API drives.
    kb_connection_name: str = "voltrieve-kb-mcp"
    prompt_agent_cli: str = "voltrieve-prompt-cli"
    prompt_agent_web: str = "voltrieve-prompt-web"

    # Backend C: the name of the Foundry hosted agent (agents/hosted/deploy.py creates it).
    hosted_agent_name: str = "voltrieve-hosted"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
