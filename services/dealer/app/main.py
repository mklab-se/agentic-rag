import logging
import time
import re
import uuid

from fastapi import FastAPI, Request

from app.auth import TokenValidator
from app.data import DealerData
from app.logging_setup import configure_logging, correlation_id
from app.routes import DATA_PATH, build_router
from app.settings import Settings
from app.telemetry import annotate_span, configure_telemetry

logger = logging.getLogger("app.access")
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def create_app(settings: Settings, validator: TokenValidator | None = None) -> FastAPI:
    configure_logging(settings.log_level)
    configure_telemetry(settings.applicationinsights_connection_string)
    app = FastAPI(
        title="Voltrieve dealer service", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.validator = validator or TokenValidator(
        settings.tenant_id, settings.dealer_client_id, "Dealer.Access"
    )

    @app.middleware("http")
    async def correlation_and_access_log(request: Request, call_next):
        supplied = request.headers.get("X-Correlation-Id", "")
        cid = supplied if CORRELATION_ID_PATTERN.fullmatch(supplied) else str(uuid.uuid4())
        token = correlation_id.set(cid)
        annotate_span(correlation_id=cid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Correlation-Id"] = cid
            return response
        finally:
            logger.info(
                "request",
                extra={
                    "path": request.url.path,
                    "status": status,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            correlation_id.reset(token)

    app.include_router(build_router(DealerData.load(DATA_PATH)))
    return app


def build_app() -> FastAPI:
    """The uvicorn entry point (`uvicorn --factory app.main:build_app`): nothing is built at
    import."""
    return create_app(Settings())
