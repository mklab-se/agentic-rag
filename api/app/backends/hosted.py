"""Backend C: the agent core hosted in Foundry, reached over the Invocations protocol.

Only `run_turn` is remote. The conversation (creation, ownership, repair, abandon) stays in
Foundry Conversations and is handled here exactly as in the loop backend. The hosted agent is
stateless: every call carries the new input or the client results, the client tools, the server
tool outputs of a paused iteration and the user's claims (spec 6.5). The agent answers with the
same events the loop emits, then one `outcome` event that is consumed here, not forwarded.

The Foundry session id of the agent is kept per conversation and passed back as a query
parameter, so a conversation keeps landing on the same agent session. Losing it (a restart
of the API) only costs a new session, as the agent holds no state.
"""

import json
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx
from voltrieve_agent.events import AgentEvent, Emit
from voltrieve_agent.loop import TurnOutcome

from app.backends.base import BackendUnavailable, TurnContext
from app.backends.loop import LoopBackend
from app.settings import Settings

logger = logging.getLogger(__name__)

INVOCATIONS_SCOPE = "https://ai.azure.com/.default"
INVOCATIONS_API_VERSION = "v1"
SESSION_HEADER = "x-agent-session-id"
OUTCOME_EVENT = "outcome"
MAX_SESSIONS = 1000
# A cold agent session can take a while to start; once it answers, keep-alives keep data flowing.
INVOKE_TIMEOUT = httpx.Timeout(30.0, read=300.0)

TokenProvider = Callable[[str], Awaitable[str]]


class HostedAgentError(Exception):
    """The call to the hosted agent failed. The message is for the log, never for the caller."""


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict]]:
    """Server-sent events as (event, data) pairs. Comments and unnamed events are skipped."""
    event, data = "", []
    async for line in lines:
        if line == "":
            if event and data:
                try:
                    yield event, json.loads("\n".join(data))
                except ValueError:
                    logger.warning("Dropped an SSE event with invalid JSON: %s", event)
            event, data = "", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))


class HostedBackend(LoopBackend):
    def __init__(
        self,
        openai_client,
        http: httpx.AsyncClient,
        token_provider: TokenProvider,
        project_endpoint: str,
        agent_name: str,
        closers: Sequence[Callable[[], Awaitable[None]]] = (),
    ):
        # No model and no server tools here: those run inside the hosted agent.
        super().__init__(None, openai_client, [], closers)  # type: ignore[arg-type]
        self._http = http
        self._token = token_provider
        self._url = f"{project_endpoint.rstrip('/')}/agents/{agent_name}/endpoint/protocols/invocations"
        self._sessions: OrderedDict[str, str] = OrderedDict()

    def _remember_session(self, conversation_id: str, session_id: str) -> None:
        self._sessions[conversation_id] = session_id
        self._sessions.move_to_end(conversation_id)
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.popitem(last=False)

    @staticmethod
    def _body(ctx: TurnContext) -> dict[str, Any]:
        return {
            "conversation_id": ctx.conversation_id,
            "turn_id": ctx.turn_id,
            "input": ctx.input,
            "client_tools": [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in ctx.client_tools
            ],
            "pending_outputs": ctx.pending_outputs,
            "user": {
                "oid": ctx.user.oid,
                "username": ctx.user.username,
                "roles": sorted(ctx.user.roles),
            },
            "correlation_id": ctx.correlation_id,
        }

    async def run_turn(self, ctx: TurnContext, emit: Emit) -> TurnOutcome:
        try:
            return await self._invoke(ctx, emit)
        except Exception:
            logger.exception("The hosted agent call failed")
            await emit(
                AgentEvent(
                    "error",
                    {
                        "code": "hosted_agent_error",
                        "message": "The hosted agent could not complete the answer.",
                    },
                )
            )
            return TurnOutcome("failed")

    async def _invoke(self, ctx: TurnContext, emit: Emit) -> TurnOutcome:
        params = {"api-version": INVOCATIONS_API_VERSION}
        session_id = self._sessions.get(ctx.conversation_id)
        if session_id:
            params["agent_session_id"] = session_id
        headers = {
            "Authorization": f"Bearer {await self._token(INVOCATIONS_SCOPE)}",
            "Accept": "text/event-stream",
        }
        request = self._http.build_request(
            "POST", self._url, params=params, headers=headers, json=self._body(ctx),
            timeout=INVOKE_TIMEOUT,
        )
        response = await self._http.send(request, stream=True)
        try:
            if response.status_code != 200:
                body = (await response.aread())[:500].decode(errors="replace")
                raise HostedAgentError(f"HTTP {response.status_code}: {body}")
            new_session = response.headers.get(SESSION_HEADER)
            if new_session:
                self._remember_session(ctx.conversation_id, new_session)
            outcome: dict | None = None
            async for kind, data in parse_sse(response.aiter_lines()):
                if kind == OUTCOME_EVENT:
                    outcome = data
                else:
                    await emit(AgentEvent(kind, data))
        finally:
            await response.aclose()
        if outcome is None:
            raise HostedAgentError("the event stream ended without an outcome")
        return TurnOutcome(
            outcome["status"],
            outcome.get("pending_outputs") or [],
            outcome.get("usage") or {},
            outcome.get("client_call_ids") or [],
        )


def build_hosted_backend(settings: Settings) -> HostedBackend:
    """Connect to Foundry. Called on first use, never at import."""
    if not settings.foundry_project_endpoint:
        logger.warning("Backend 'hosted' is not configured, missing: FOUNDRY_PROJECT_ENDPOINT")
        raise BackendUnavailable("Backend 'hosted' is not configured in this deployment.")

    from azure.ai.projects.aio import AIProjectClient
    from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

    credential = AsyncDefaultAzureCredential()
    project = AIProjectClient(endpoint=settings.foundry_project_endpoint, credential=credential)
    openai_client = project.get_openai_client()
    http = httpx.AsyncClient()

    async def token(scope: str) -> str:
        return (await credential.get_token(scope)).token

    async def close_all() -> None:
        await http.aclose()
        await openai_client.close()
        await project.close()
        await credential.close()

    return HostedBackend(
        openai_client,
        http,
        token,
        settings.foundry_project_endpoint,
        settings.hosted_agent_name,
        closers=[close_all],
    )
