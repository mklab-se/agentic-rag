"""Backend C: the Voltrieve agent core as a Foundry hosted agent (Invocations protocol).

The Web API posts one JSON body per model-and-tools round:

    {conversation_id, turn_id, input, client_tools, pending_outputs,
     user: {oid, username, roles}, correlation_id}

and this process answers with server-sent events. It runs `agent_core.run_turn` unchanged and
relays every AgentEvent one to one (event name = type, data = one line of JSON). When the turn
ends it sends one more event, `outcome` {status, pending_outputs, client_call_ids, usage}, which
the Web API consumes instead of forwarding. The agent holds no state between requests: a
continuation resends client_tools and pending_outputs, and the conversation itself lives in
Foundry.

The Web API's managed identity is the only caller allowed to invoke the agent (spec 6.5), so
the `user` claims in the body are trusted. The Foundry gateway replaces `x-ms-original-subject`
with the true caller (verified live: a forged header is answered with 403), and the agent server
parses it. The oid it carries must equal ALLOWED_CALLER_OID. The check fails closed: with
ALLOWED_CALLER_OID empty every request is refused, unless ALLOW_ANY_CALLER=true is set explicitly
(local use only, logged loudly).

Tracing: the agent server host configures Azure Monitor itself from
APPLICATIONINSIGHTS_CONNECTION_STRING (azure.ai.agentserver.core), so nothing is configured here.
"""

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from voltrieve_agent.events import AgentEvent
from voltrieve_agent.loop import TurnInput, run_turn
from voltrieve_agent.model import ModelClient
from voltrieve_agent.tools import ClientTool, ServerTool, UserContext

logger = logging.getLogger("voltrieve.hosted")

SUBJECT_HEADER = "x-ms-original-subject"
KEEPALIVE_SECONDS = 15.0
KEEPALIVE = b": keep-alive\n\n"
OUTCOME_EVENT = "outcome"


@dataclass
class Runtime:
    model: ModelClient
    server_tools: list[ServerTool]
    allowed_caller_oid: str = ""
    allow_any_caller: bool = False


def caller_oid() -> str | None:
    """The oid of the caller as parsed by the agent server from x-ms-original-subject."""
    from azure.ai.agentserver.core import get_request_context

    subject = get_request_context().original_subject
    return subject.oid if subject is not None else None


def check_caller(allowed_oid: str, allow_any: bool = False) -> bool:
    """True when the caller may invoke the agent. Fails closed when nothing is configured."""
    if allow_any:
        return True
    if not allowed_oid.strip():
        logger.error("Refused: ALLOWED_CALLER_OID is not set (set ALLOW_ANY_CALLER=true for local use)")
        return False
    oid = caller_oid()
    logger.debug("%s oid: %r", SUBJECT_HEADER, oid)
    if not oid:
        logger.warning("Refused: no caller oid in %s", SUBJECT_HEADER)
        return False
    if oid.strip().lower() != allowed_oid.strip().lower():
        logger.warning("Refused: caller %s is not the allowed caller", oid)
        return False
    return True


def parse_turn(body: object) -> TurnInput | None:
    """Build the TurnInput from the request body (pending outputs are folded into the input), or None if malformed."""
    if not isinstance(body, dict):
        return None
    try:
        user = body["user"]
        input_ = body["input"]
        if not isinstance(input_, str | list):
            return None
        pending = body.get("pending_outputs") or []
        tools = [
            ClientTool(t["name"], t.get("description", ""), t.get("parameters") or {"type": "object"})
            for t in body.get("client_tools") or []
        ]
        if isinstance(input_, list):
            # The server tool outputs of the paused iteration go in with the client results.
            input_ = [*pending, *input_]
        return TurnInput(
            user=UserContext(
                str(user["oid"]), str(user.get("username", "")), frozenset(user.get("roles") or [])
            ),
            conversation_id=str(body["conversation_id"]),
            turn_id=str(body["turn_id"]),
            input=input_,
            client_tools=tools,
            correlation_id=body.get("correlation_id"),
        )
    except (KeyError, TypeError, AttributeError):
        return None


def format_event(event_type: str, data: dict) -> bytes:
    # ensure_ascii: U+2028, U+2029 and U+0085 would otherwise be taken as line breaks by readers.
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event_type}\ndata: {payload}\n\n".encode()


_tasks: set[asyncio.Task] = set()


async def stream_turn(runtime: Runtime, turn: TurnInput) -> AsyncIterator[bytes]:
    """Run the turn in the background and stream its events, ending with `outcome`.

    The turn is not tied to the response: if the caller disconnects it still runs to its end,
    so the conversation is not left with a function call without output.
    """
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    async def emit(event: AgentEvent) -> None:
        await queue.put((event.type, event.data))

    async def run() -> None:
        try:
            outcome = await run_turn(runtime.model, runtime.server_tools, turn, emit)
            await queue.put(
                (
                    OUTCOME_EVENT,
                    {
                        "status": outcome.status,
                        "pending_outputs": outcome.pending_outputs,
                        "client_call_ids": outcome.client_call_ids,
                        "usage": outcome.usage,
                    },
                )
            )
        except Exception:
            logger.exception("Turn failed")
            await queue.put(
                (
                    "error",
                    {"code": "internal_error", "message": "The request could not be completed."},
                )
            )
            await queue.put(
                (OUTCOME_EVENT, {"status": "failed", "pending_outputs": [], "client_call_ids": [], "usage": {}})
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
        except TimeoutError:
            yield KEEPALIVE
            continue
        if item is None:
            return
        yield format_event(*item)


async def handle(request: Request, runtime: Runtime) -> Response:
    if not check_caller(runtime.allowed_caller_oid, runtime.allow_any_caller):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except ValueError:
        body = None
    turn = parse_turn(body)
    if turn is None:
        return JSONResponse({"error": "invalid request body"}, status_code=400)
    logger.info(
        "turn %s conversation %s session %s",
        turn.turn_id,
        turn.conversation_id,
        request.headers.get("x-agent-session-id"),
    )
    return StreamingResponse(
        stream_turn(runtime, turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_runtime: Runtime | None = None


def build_runtime() -> Runtime:
    """Connect to Foundry, search and the dealer with the agent identity. Called on first use."""
    from azure.ai.projects.aio import AIProjectClient
    from azure.identity import DefaultAzureCredential
    from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
    from voltrieve_agent.dealer import DealerClient, make_http_client
    from voltrieve_agent.knowledge import KnowledgeBase
    from voltrieve_agent.model import ResponsesModelClient
    from voltrieve_agent.server_tools import build_server_tools

    credential = AsyncDefaultAzureCredential()
    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential)
    openai_client = project.get_openai_client()
    dealer_scope = f"api://{os.environ['DEALER_CLIENT_ID']}/.default"

    async def dealer_token() -> str:
        return (await credential.get_token(dealer_scope)).token

    dealer = DealerClient(os.environ["DEALER_URL"], dealer_token, make_http_client())
    knowledge = KnowledgeBase(os.environ["SEARCH_ENDPOINT"], DefaultAzureCredential())
    return Runtime(
        ResponsesModelClient(openai_client, os.environ["MODEL_DEPLOYMENT_NAME"]),
        build_server_tools(dealer, knowledge),
        os.environ.get("ALLOWED_CALLER_OID", ""),
        os.environ.get("ALLOW_ANY_CALLER", "").lower() == "true",
    )


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


def create_host():
    from azure.ai.agentserver.invocations import InvocationAgentServerHost

    host = InvocationAgentServerHost()
    if os.environ.get("ALLOW_ANY_CALLER", "").lower() == "true":
        logger.critical("ALLOW_ANY_CALLER=true: ANY caller may invoke this agent. Local use only.")
    elif not os.environ.get("ALLOWED_CALLER_OID", "").strip():
        logger.error("ALLOWED_CALLER_OID is empty: every request will be refused")

    @host.invoke_handler
    async def invoke(request: Request) -> Response:
        try:
            runtime = get_runtime()
        except Exception:
            logger.exception("The agent could not connect to its dependencies")
            return JSONResponse({"error": "agent not configured"}, status_code=503)
        return await handle(request, runtime)

    return host


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_host().run()
