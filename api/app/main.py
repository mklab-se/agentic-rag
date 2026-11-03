import logging
import re
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from voltrieve_agent.server_tools import build_server_tools

from app.auth import TokenValidator
from app.backends import BackendRegistry
from app.logging_setup import configure_logging, correlation_id
from app.routes import build_router
from app.settings import Settings
from app.telemetry import configure_telemetry
from app.turns import TurnService, TurnStore

logger = logging.getLogger("app.access")
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_BODY_BYTES = 64 * 1024


class BodyTooLarge(Exception):
    pass


class RequestGuard:
    """Pure ASGI middleware: correlation id, request body limit and the access log.

    Not BaseHTTPMiddleware, which would buffer or break the SSE streams.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        supplied = headers.get("x-correlation-id", "")
        cid = supplied if CORRELATION_ID_PATTERN.fullmatch(supplied) else str(uuid.uuid4())
        token = correlation_id.set(cid)
        start = time.perf_counter()
        status = 500
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                response_headers = [
                    h for h in message["headers"] if h[0].lower() != b"x-correlation-id"
                ]
                response_headers.append((b"x-correlation-id", cid.encode()))
                message = {**message, "headers": response_headers}
            await send(message)

        received = 0

        async def receive_wrapper() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise BodyTooLarge
            return message

        try:
            length = headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_BODY_BYTES:
                raise BodyTooLarge
            await self.app(scope, receive_wrapper, send_wrapper)
        except BodyTooLarge:
            if started:
                raise
            status = 413
            response = JSONResponse({"detail": "Request body too large"}, 413, {"X-Correlation-Id": cid})
            await response(scope, receive, send)
        finally:
            logger.info(
                "request",
                extra={
                    "path": scope["path"],
                    "status": status,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            correlation_id.reset(token)


def create_app(
    settings: Settings,
    validator: TokenValidator | None = None,
    registry: BackendRegistry | None = None,
    store: TurnStore | None = None,
) -> FastAPI:
    configure_logging(settings.log_level)
    configure_telemetry(settings.applicationinsights_connection_string)
    app = FastAPI(title="Voltrieve API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.validator = validator or TokenValidator(settings.tenant_id, settings.api_client_id)
    app.state.registry = registry or BackendRegistry(settings)
    app.state.store = store or TurnStore()
    app.state.turns = TurnService(app.state.store, app.state.registry)
    # The handlers are closures over the clients and never called here, so None is fine.
    app.state.server_tool_names = frozenset(t.name for t in build_server_tools(None, None))

    app.include_router(build_router())
    app.add_middleware(RequestGuard)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Agent-Backend", "X-Correlation-Id"],
        expose_headers=["X-Correlation-Id"],
    )
    return app


app = create_app(Settings())
