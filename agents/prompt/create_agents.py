"""Create (a new version of) the two Foundry prompt agents used by backend A.

    uv run create_agents.py

Reads FOUNDRY_PROJECT_ENDPOINT, CHAT_DEPLOYMENT, SEARCH_ENDPOINT, KB_CONNECTION_NAME and
PARTS_KB_CONNECTION_NAME from the environment (`azd env get-values` has them) and authenticates with Entra
(DefaultAzureCredential). Optional: PROMPT_AGENT_CLI and PROMPT_AGENT_WEB override the names.

Both agents carry the instructions, each knowledge base as an MCP tool through its project
connection, and the dealer operations as function tools. The two MCP tools expose the same tool
name, knowledge_base_retrieve, so only the server label and description tell them apart. The CLI agent also carries the CLI's
client tools: a prompt agent cannot be given tools per request, so they must be in its
definition.
"""

import os
import sys

from azure.ai.projects.models import FunctionTool, MCPTool, PromptAgentDefinition, Reasoning
from voltrieve_agent.instructions import PROMPT_AGENT_INSTRUCTIONS
from voltrieve_agent.model import REASONING_EFFORT
from voltrieve_agent.server_tools import (
    DOCS_DESCRIPTION,
    KB_SEARCH_TOOLS,
    PARTS_DESCRIPTION,
    build_server_tools,
)

CLI_AGENT_NAME = "voltrieve-prompt-cli"
WEB_AGENT_NAME = "voltrieve-prompt-web"
KB_NAME = "voltrieve-kb"
PARTS_KB_NAME = "voltrieve-parts-kb"
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
    searches are left out: these agents get the knowledge bases as MCP tools."""
    return [
        _function_tool(t.name, t.description, t.parameters)
        for t in build_server_tools(None, None)  # type: ignore[arg-type]
        if t.name not in KB_SEARCH_TOOLS
    ]


def cli_function_tools() -> list[FunctionTool]:
    return [_function_tool(t["name"], t["description"], t["parameters"]) for t in CLI_TOOLS]


def kb_mcp_tool(search_endpoint: str, kb_name: str, description: str, connection_name: str) -> MCPTool:
    return MCPTool(
        server_label=kb_name,
        server_description=description,
        server_url=f"{search_endpoint.rstrip('/')}/knowledgebases/{kb_name}/mcp?api-version={KB_API_VERSION}",
        require_approval="never",
        allowed_tools=["knowledge_base_retrieve"],
        project_connection_id=connection_name,
    )


def agent_definition(
    chat_deployment: str,
    search_endpoint: str,
    connection_name: str,
    parts_connection_name: str,
    with_cli_tools: bool,
) -> PromptAgentDefinition:
    tools = [
        kb_mcp_tool(search_endpoint, KB_NAME, DOCS_DESCRIPTION, connection_name),
        kb_mcp_tool(search_endpoint, PARTS_KB_NAME, PARTS_DESCRIPTION, parts_connection_name),
        *dealer_function_tools(),
    ]
    if with_cli_tools:
        tools += cli_function_tools()
    return PromptAgentDefinition(
        model=chat_deployment,
        instructions=PROMPT_AGENT_INSTRUCTIONS,
        tools=tools,
        reasoning=Reasoning(effort=REASONING_EFFORT),
    )


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
    parts_connection_name = _require("PARTS_KB_CONNECTION_NAME")
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
            definition = agent_definition(
                chat_deployment, search_endpoint, connection_name, parts_connection_name, with_cli
            )
            version = project.agents.create_version(agent_name=name, definition=definition)
            print(f"{name}: version {version.version} ({len(definition.tools)} tools)")


if __name__ == "__main__":
    main()
