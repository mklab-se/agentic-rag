"""Backend B: the orchestration loop in agent_core, run inside the API process."""

import logging
from collections.abc import Awaitable, Callable, Sequence
from functools import partial

from voltrieve_agent.dealer import DealerClient
from voltrieve_agent.events import Emit
from voltrieve_agent.http_client import make_http_client
from voltrieve_agent.knowledge import KnowledgeBase, parts_knowledge_base
from voltrieve_agent.loop import TurnInput, TurnOutcome, run_turn
from voltrieve_agent.model import ModelClient, ResponsesModelClient
from voltrieve_agent.server_tools import build_server_tools
from voltrieve_agent.tools import ServerTool

from app.backends.base import BackendUnavailable, ConversationBackend, TurnContext, close_all
from app.settings import Settings

logger = logging.getLogger(__name__)


class LoopBackend(ConversationBackend):
    def __init__(
        self,
        model: ModelClient,
        openai_client,
        server_tools: list[ServerTool],
        closers: Sequence[Callable[[], Awaitable[None]]] = (),
    ):
        super().__init__(openai_client, closers)
        self._model = model
        self._server_tools = server_tools

    def _model_for(self, ctx: TurnContext) -> ModelClient:
        return self._model

    async def run_turn(self, ctx: TurnContext, emit: Emit) -> TurnOutcome:
        input_ = ctx.input
        if isinstance(input_, list):
            input_ = [*ctx.pending_outputs, *input_]
        turn = TurnInput(
            user=ctx.user,
            conversation_id=ctx.conversation_id,
            turn_id=ctx.turn_id,
            input=input_,
            client_tools=ctx.client_tools,
            correlation_id=ctx.correlation_id,
        )
        return await run_turn(self._model_for(ctx), self._server_tools, turn, emit)


def build_loop_backend(settings: Settings) -> LoopBackend:
    """Connect to Foundry, search and the dealer. Called on first use, never at import."""
    missing = [
        name
        for name, value in {
            "FOUNDRY_PROJECT_ENDPOINT": settings.foundry_project_endpoint,
            "SEARCH_ENDPOINT": settings.search_endpoint,
            "DEALER_URL": settings.dealer_url,
            "DEALER_CLIENT_ID": settings.dealer_client_id,
        }.items()
        if not value
    ]
    if missing:
        # Which settings are missing is an operator matter: log it, do not tell the caller.
        logger.warning("Backend 'loop' is not configured, missing: %s", ", ".join(missing))
        raise BackendUnavailable("Backend 'loop' is not configured in this deployment.")

    from azure.ai.projects.aio import AIProjectClient
    from azure.identity import DefaultAzureCredential
    from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

    # These live for the whole process. Async credentials serve Foundry and the dealer
    # token; the search client runs in a worker thread and needs a synchronous one.
    async_credential = AsyncDefaultAzureCredential()
    project = AIProjectClient(endpoint=settings.foundry_project_endpoint, credential=async_credential)
    openai_client = project.get_openai_client()  # AsyncOpenAI on the project's endpoint

    dealer_scope = f"api://{settings.dealer_client_id}/.default"

    async def dealer_token() -> str:
        return (await async_credential.get_token(dealer_scope)).token

    http = make_http_client()
    dealer = DealerClient(settings.dealer_url, dealer_token, http)
    search_credential = DefaultAzureCredential()
    knowledge = KnowledgeBase(settings.search_endpoint, search_credential)
    parts = parts_knowledge_base(settings.search_endpoint, search_credential)
    model = ResponsesModelClient(openai_client, settings.chat_deployment)
    return LoopBackend(
        model,
        openai_client,
        build_server_tools(dealer, knowledge, parts),
        closers=[partial(close_all, http, openai_client, project, async_credential)],
    )
