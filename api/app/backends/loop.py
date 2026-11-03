"""Backend C: the orchestration loop in agent_core, run inside the API process."""

from voltrieve_agent.dealer import DealerClient, make_http_client
from voltrieve_agent.events import Emit
from voltrieve_agent.knowledge import KnowledgeBase
from voltrieve_agent.loop import TurnInput, TurnOutcome, run_turn
from voltrieve_agent.model import ModelClient, ResponsesModelClient
from voltrieve_agent.server_tools import build_server_tools
from voltrieve_agent.tools import ServerTool

from app.backends.base import BackendUnavailable, TurnContext
from app.settings import Settings


class LoopBackend:
    def __init__(self, model: ModelClient, openai_client, server_tools: list[ServerTool]):
        self._model = model
        self._openai = openai_client  # AsyncOpenAI; only its conversations API is used here
        self._server_tools = server_tools

    async def create_conversation(self) -> str:
        conversation = await self._openai.conversations.create()
        return conversation.id

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
        return await run_turn(self._model, self._server_tools, turn, emit)

    async def abandon(self, conversation_id: str, outputs: list[dict]) -> None:
        # Adding items does not call the model, so abandoning costs no tokens.
        if outputs:
            await self._openai.conversations.items.create(conversation_id, items=outputs)


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
        raise BackendUnavailable(f"Backend 'loop' is not configured (missing {', '.join(missing)}).")

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

    dealer = DealerClient(settings.dealer_url, dealer_token, make_http_client())
    knowledge = KnowledgeBase(settings.search_endpoint, DefaultAzureCredential())
    model = ResponsesModelClient(openai_client, settings.chat_deployment)
    return LoopBackend(model, openai_client, build_server_tools(dealer, knowledge))
