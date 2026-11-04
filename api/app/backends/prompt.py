"""Backend A: Foundry prompt agents, driven through the Responses API with an agent reference.

The agent definitions (instructions, knowledge base MCP tool, function tools) live in the
Foundry project, created by agents/prompt/create_agents.py. The orchestration loop in
agent_core is reused: a model client that sends only an agent reference replaces the one that
sends model, instructions and tools. Dealer tools run here through the same ServerTools, so
roles apply; client tools pause the turn exactly as in the loop backend.
"""

import logging
from functools import partial

from voltrieve_agent.dealer import DealerClient
from voltrieve_agent.events import AgentEvent, Emit, trace
from voltrieve_agent.http_client import make_http_client
from voltrieve_agent.loop import TurnOutcome
from voltrieve_agent.model import ModelClient, ResponsesModelClient
from voltrieve_agent.server_tools import KB_SEARCH_TOOL, build_server_tools
from voltrieve_agent.tools import ServerTool

from app.backends.base import BackendUnavailable, TurnContext, close_all
from app.backends.loop import LoopBackend
from app.settings import Settings

logger = logging.getLogger(__name__)

# The client tools the CLI agent is defined with. This must match CLI_TOOLS in
# agents/prompt/create_agents.py (a test checks it): the CLI is a separate project, so the
# agent definition carries its own copy of the schemas.
CLI_AGENT_TOOL_NAMES = frozenset({"make_noise", "get_local_time", "show_banner"})

CITATION_OPEN = "\u3010"  # the marks Foundry puts around a citation: 【5:0†file.pdf】
CITATION_CLOSE = "\u3011"
CITATION_SEPARATOR = "\u2020"
# A marker longer than this is not a marker: let it through as text.
MAX_CITATION_LENGTH = 200


def _citation_text(marker: str) -> str:
    """` (file.pdf)` for a citation marker, or nothing when it names no real file."""
    _, _, name = marker.partition(CITATION_SEPARATOR)
    name = name.strip()
    return "" if name.lower() in ("", "source") else f" ({name})"


class CitationFilter:
    """Wraps `emit` so the text deltas carry no Foundry citation markers.

    The other backends cite by document title in plain text, and clients must not be able to
    tell the backends apart. A marker can be split over several deltas, so the text from the
    opening mark to the closing one is held back until it is complete. Call `flush` when the
    turn ends to release a marker that never closed.
    """

    def __init__(self, emit: Emit):
        self._emit = emit
        self._held = ""

    async def __call__(self, event: AgentEvent) -> None:
        if event.type != "delta":
            await self._emit(event)
            return
        text = self._held + str(event.data.get("text", ""))
        self._held = ""
        out = []
        while text:
            start = text.find(CITATION_OPEN)
            if start == -1:
                out.append(text)
                break
            out.append(text[:start])
            end = text.find(CITATION_CLOSE, start)
            if end == -1:
                rest = text[start:]
                if len(rest) > MAX_CITATION_LENGTH:
                    out.append(rest)
                else:
                    self._held = rest
                break
            out.append(_citation_text(text[start + 1 : end]))
            text = text[end + 1 :]
        if any(out):
            await self._emit(AgentEvent("delta", {**event.data, "text": "".join(out)}))

    async def flush(self) -> None:
        held, self._held = self._held, ""
        if held:
            await self._emit(AgentEvent("delta", {"text": held}))


class PromptBackend(LoopBackend):
    def __init__(
        self,
        cli_model: ModelClient,
        web_model: ModelClient,
        openai_client,
        server_tools: list[ServerTool],
        closers=(),
    ):
        super().__init__(web_model, openai_client, server_tools, closers)
        self._cli_model = cli_model

    def _model_for(self, ctx: TurnContext) -> ModelClient:
        return self._cli_model if ctx.client_tools else self._model

    async def run_turn(self, ctx: TurnContext, emit: Emit) -> TurnOutcome:
        unsupported = sorted({t.name for t in ctx.client_tools} - CLI_AGENT_TOOL_NAMES)
        if unsupported:
            names = ", ".join(unsupported)
            await emit(
                trace(
                    "unsupported_client_tool",
                    "api",
                    f"not in the agent definition: {names}",
                    tools=unsupported,
                )
            )
            await emit(
                AgentEvent(
                    "error",
                    {
                        "code": "unsupported_client_tool",
                        "message": "The prompt agent only supports the client tools in its "
                        f"definition ({', '.join(sorted(CLI_AGENT_TOOL_NAMES))}). "
                        f"Not supported: {names}.",
                    },
                )
            )
            return TurnOutcome("failed")
        citations = CitationFilter(emit)
        try:
            return await super().run_turn(ctx, citations)
        finally:
            await citations.flush()


def build_prompt_backend(settings: Settings) -> PromptBackend:
    """Connect to Foundry and the dealer. Called on first use, never at import."""
    missing = [
        name
        for name, value in {
            "FOUNDRY_PROJECT_ENDPOINT": settings.foundry_project_endpoint,
            "DEALER_URL": settings.dealer_url,
            "DEALER_CLIENT_ID": settings.dealer_client_id,
        }.items()
        if not value
    ]
    if missing:
        logger.warning("Backend 'prompt' is not configured, missing: %s", ", ".join(missing))
        raise BackendUnavailable("Backend 'prompt' is not configured in this deployment.")

    from azure.ai.projects.aio import AIProjectClient
    from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

    credential = AsyncDefaultAzureCredential()
    project = AIProjectClient(endpoint=settings.foundry_project_endpoint, credential=credential)
    openai_client = project.get_openai_client()

    dealer_scope = f"api://{settings.dealer_client_id}/.default"

    async def dealer_token() -> str:
        return (await credential.get_token(dealer_scope)).token

    http = make_http_client()
    dealer = DealerClient(settings.dealer_url, dealer_token, http)
    server_tools = [t for t in build_server_tools(dealer, None) if t.name != KB_SEARCH_TOOL]

    return PromptBackend(
        ResponsesModelClient(openai_client, agent_name=settings.prompt_agent_cli),
        ResponsesModelClient(openai_client, agent_name=settings.prompt_agent_web),
        openai_client,
        server_tools,
        closers=[partial(close_all, http, openai_client, project, credential)],
    )
