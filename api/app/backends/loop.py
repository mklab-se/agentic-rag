"""Backend B: the orchestration loop in agent_core, run inside the API process."""

import logging
from collections.abc import Awaitable, Callable, Sequence

from voltrieve_agent.dealer import DealerClient, make_http_client
from voltrieve_agent.events import Emit
from voltrieve_agent.knowledge import KnowledgeBase
from voltrieve_agent.loop import TurnInput, TurnOutcome, run_turn
from voltrieve_agent.model import ModelClient, ResponsesModelClient
from voltrieve_agent.server_tools import build_server_tools
from voltrieve_agent.tools import ServerTool

from app.backends.base import BackendUnavailable, TurnContext
from app.settings import Settings

logger = logging.getLogger(__name__)


REPAIR_OUTPUT = "the client did not return a result"
REPAIR_SCAN_ITEMS = 100
REPAIR_BATCH = 20


class ConversationBackend:
    """What backends share: the conversation lives in Foundry Conversations."""

    def __init__(self, openai_client, closers: Sequence[Callable[[], Awaitable[None]]] = ()):
        self._openai = openai_client  # AsyncOpenAI; only its conversations API is used here
        self._closers = closers

    async def create_conversation(self, owner_oid: str) -> str:
        conversation = await self._openai.conversations.create(metadata={"owner_oid": owner_oid})
        return conversation.id

    async def get_conversation_owner(self, conversation_id: str) -> str | None:
        try:
            conversation = await self._openai.conversations.retrieve(conversation_id)
        except Exception:
            logger.warning("Could not read conversation %s", conversation_id, exc_info=True)
            return None
        return (getattr(conversation, "metadata", None) or {}).get("owner_oid")

    async def abandon(self, conversation_id: str, outputs: list[dict]) -> None:
        # Adding items does not call the model, so abandoning costs no tokens.
        if outputs:
            await self._openai.conversations.items.create(conversation_id, items=outputs)

    async def repair(self, conversation_id: str) -> None:
        calls: list[str] = []
        answered: set[str] = set()
        page = await self._openai.conversations.items.list(
            conversation_id, limit=REPAIR_SCAN_ITEMS, order="desc"
        )
        async for item in page:
            if item.type == "function_call":
                calls.append(item.call_id)
            elif item.type == "function_call_output":
                answered.add(item.call_id)
            if len(calls) + len(answered) >= REPAIR_SCAN_ITEMS:
                break
        missing = [
            {"type": "function_call_output", "call_id": c, "output": REPAIR_OUTPUT}
            for c in dict.fromkeys(calls)
            if c not in answered
        ]
        for start in range(0, len(missing), REPAIR_BATCH):
            await self._openai.conversations.items.create(
                conversation_id, items=missing[start : start + REPAIR_BATCH]
            )
        if missing:
            logger.info("Repaired %d open calls in %s", len(missing), conversation_id)

    async def close(self) -> None:
        for closer in self._closers:
            try:
                await closer()
            except Exception:
                logger.exception("Closing the loop backend failed")


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
    knowledge = KnowledgeBase(settings.search_endpoint, DefaultAzureCredential())
    model = ResponsesModelClient(openai_client, settings.chat_deployment)
    async def close_all() -> None:
        await http.aclose()
        await openai_client.close()
        await project.close()
        await async_credential.close()

    return LoopBackend(
        model, openai_client, build_server_tools(dealer, knowledge), closers=[close_all]
    )
