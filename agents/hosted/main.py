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
the `user` claims in the body are trusted. The Foundry gateway forwards the caller's identity in
`x-ms-original-subject`; ALLOWED_CALLER_OID names the one caller to accept.
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
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
SUBJECT_OID = re.compile(r'(?:^|,)\s*oid="([^"]*)"')
SUBJECT_KEYS = ("oid", "objectId", "object_id", "principalId", "principal_id", "sub", "id")


@dataclass
class Runtime:
    model: ModelClient
    server_tools: list[ServerTool]
    allowed_caller_oid: str = ""


def parse_subject(value: str) -> str | None:
    """The caller's object id from x-ms-original-subject, or None when it cannot be read.

    The Foundry agent server documents the header as a dictionary of quoted strings,
    `oid="...", tid="...", idtype="..."`, and itself answers 400 to anything else. Whether the
    oid is the calling identity is for a live check (the value is logged). Also accepted, in
    case the platform changes: a bare GUID, a JSON object carrying the id under a known key,
    or any text holding exactly one GUID. Anything else is unparseable.
    """
    value = value.strip()
    member = SUBJECT_OID.search(value)
    if member is not None:
        oid = member.group(1).strip()
        return oid.lower() if GUID.fullmatch(oid) else None
    if value.startswith("{"):
        try:
            data = json.loads(value)
        except ValueError:
            data = None
        if isinstance(data, dict):
            for key in SUBJECT_KEYS:
                candidate = data.get(key)
                if isinstance(candidate, str) and GUID.fullmatch(candidate.strip()):
                    return candidate.strip().lower()
            return None
    found = {m.lower() for m in GUID.findall(value)}
    return found.pop() if len(found) == 1 else None


def check_caller(headers: Mapping[str, str], allowed_oid: str) -> bool:
    """True when the caller may invoke the agent. Logs the header, so its format is on record."""
    subject = headers.get(SUBJECT_HEADER)
    logger.info("%s present: %s, value: %r", SUBJECT_HEADER, subject is not None, subject)
    if not allowed_oid:
        return True
    if subject is None:
        logger.warning("Refused: no %s header and ALLOWED_CALLER_OID is set", SUBJECT_HEADER)
        return False
    caller = parse_subject(subject)
    if caller is None:
        logger.warning("Refused: could not read a caller id from %s %r", SUBJECT_HEADER, subject)
        return False
    if caller != allowed_oid.strip().lower():
        logger.warning("Refused: caller %s is not the allowed caller", caller)
        return False
    return True


def parse_turn(body: object) -> TurnInput | tuple[str, list[dict]] | None:
    """Build the TurnInput and pending outputs from the request body, or None if malformed."""
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
        ), pending
    except (KeyError, TypeError, AttributeError):
        return None


def format_event(event_type: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
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
    if not check_caller(request.headers, runtime.allowed_caller_oid):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except ValueError:
        body = None
    parsed = parse_turn(body)
    if parsed is None:
        return JSONResponse({"error": "invalid request body"}, status_code=400)
    turn, _ = parsed
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
    )


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


def create_host():
    from azure.ai.agentserver.invocations import InvocationAgentServerHost

    host = InvocationAgentServerHost()

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
