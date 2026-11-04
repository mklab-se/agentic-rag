"""Create (a new version of) the two Foundry prompt agents used by backend A.

    uv run create_agents.py

Reads FOUNDRY_PROJECT_ENDPOINT, CHAT_DEPLOYMENT, SEARCH_ENDPOINT and KB_CONNECTION_NAME from
the environment (`azd env get-values` has them) and authenticates with Entra
(DefaultAzureCredential). Optional: PROMPT_AGENT_CLI and PROMPT_AGENT_WEB override the names.

Both agents carry the instructions, the knowledge base as an MCP tool through the project
connection, and the dealer operations as function tools. The CLI agent also carries the CLI's
client tools: a prompt agent cannot be given tools per request, so they must be in its
definition.
"""

import os
import sys

from azure.ai.projects.models import FunctionTool, MCPTool, PromptAgentDefinition
from voltrieve_agent.instructions import AGENT_INSTRUCTIONS
from voltrieve_agent.server_tools import KB_SEARCH_TOOL, build_server_tools

CLI_AGENT_NAME = "voltrieve-prompt-cli"
WEB_AGENT_NAME = "voltrieve-prompt-web"
KB_SERVER_LABEL = "voltrieve-kb"
KB_NAME = "voltrieve-kb"
KB_API_VERSION = "2026-08-01-preview"

MAX_NOISE = 10

# Copy of CLIENT_TOOLS in clients/cli/src/voltrieve_cli/tools.py. The CLI is a separate project,
# so the schemas are repeated here. tests/contract fails when the two differ. The API checks
# request tools against the names (CLI_AGENT_TOOL_NAMES in api/app/backends/prompt.py).
CLI_TOOLS = [
    {
        "name": "make_noise",
        "description": f"Ring the terminal bell on the user's machine. At most {MAX_NOISE} times.",
        "parameters": {
            "type": "object",
            "properties": {"times": {"type": "integer", "minimum": 1, "maximum": MAX_NOISE}},
            "required": ["times"],
        },
    },
    {
        "name": "get_local_time",
        "description": "Get the local time and timezone of the user's machine.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "show_banner",
        "description": "Show a highlighted banner with the given text in the user's terminal.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


def _function_tool(name: str, description: str, parameters: dict) -> FunctionTool:
    # strict=False: the schemas do not meet strict mode (optional properties, formats).
    return FunctionTool(name=name, description=description, parameters=parameters, strict=False)


def dealer_function_tools() -> list[FunctionTool]:
    """The dealer operations, from the same ServerTool definitions the API executes. The
    documentation search is left out: these agents get the knowledge base as an MCP tool."""
    return [
        _function_tool(t.name, t.description, t.parameters)
        for t in build_server_tools(None, None)  # type: ignore[arg-type]
        if t.name != KB_SEARCH_TOOL
    ]


def cli_function_tools() -> list[FunctionTool]:
    return [_function_tool(t["name"], t["description"], t["parameters"]) for t in CLI_TOOLS]


def kb_mcp_tool(search_endpoint: str, connection_name: str) -> MCPTool:
    return MCPTool(
        server_label=KB_SERVER_LABEL,
        server_url=f"{search_endpoint.rstrip('/')}/knowledgebases/{KB_NAME}/mcp?api-version={KB_API_VERSION}",
        require_approval="never",
        allowed_tools=["knowledge_base_retrieve"],
        project_connection_id=connection_name,
    )


def agent_definition(
    chat_deployment: str, search_endpoint: str, connection_name: str, with_cli_tools: bool
) -> PromptAgentDefinition:
    tools = [kb_mcp_tool(search_endpoint, connection_name), *dealer_function_tools()]
    if with_cli_tools:
        tools += cli_function_tools()
    return PromptAgentDefinition(model=chat_deployment, instructions=AGENT_INSTRUCTIONS, tools=tools)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing environment variable {name}. Run `azd env get-values` and export it.")
    return value


def main() -> None:
    endpoint = _require("FOUNDRY_PROJECT_ENDPOINT")
    chat_deployment = _require("CHAT_DEPLOYMENT")
    search_endpoint = _require("SEARCH_ENDPOINT")
    connection_name = _require("KB_CONNECTION_NAME")
    agents = {
        os.environ.get("PROMPT_AGENT_CLI") or CLI_AGENT_NAME: True,
        os.environ.get("PROMPT_AGENT_WEB") or WEB_AGENT_NAME: False,
    }

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint, credential=credential
    ) as project:
        for name, with_cli in agents.items():
            definition = agent_definition(chat_deployment, search_endpoint, connection_name, with_cli)
            version = project.agents.create_version(agent_name=name, definition=definition)
            print(f"{name}: version {version.version} ({len(definition.tools)} tools)")


if __name__ == "__main__":
    main()
