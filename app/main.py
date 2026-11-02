"""FastAPI application factory: routers, body admission, request tracing and error envelopes."""

import json
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api.booking import router as booking_router
from app.api.chat import router as chat_router
from app.api.routes import router
from app.core.admission import RequestBodyLimitMiddleware
from app.core.clock import utc_now
from app.core.config import Settings
from app.core.errors import ApiError, error_response
from app.db.session import build_engine
from app.schemas.foundation import ErrorResponse

logger = logging.getLogger("clinic.requests")
# Container and load-balancer probes call liveness every few seconds; logging each one
# would bury real traffic. Every other route, readiness included, is still logged.
UNLOGGED_ROUTES = frozenset({"/api/v1/health/live"})
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    clock: Callable[[], datetime] = utc_now,
    provider_factory: Callable | None = None,
) -> FastAPI:
    settings = settings or Settings()
    owned_engine = engine is None
    engine = engine or build_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if owned_engine:
            engine.dispose()

    docs = settings.api_docs_enabled
    application = FastAPI(
        title="Clinic Scheduling Agent API",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        responses={413: {"model": ErrorResponse}},
    )
    # Register before the tracing middleware so even admission failures receive
    # the normal sanitized log record and correlated response/header trace ID.
    application.add_middleware(RequestBodyLimitMiddleware)
    application.state.settings = settings
    application.state.engine = engine
    application.state.clock = clock
    application.state.provider_factory = provider_factory

    @application.middleware("http")
    async def trace_request(request: Request, call_next):
        request.state.trace_id = str(uuid4())
        started = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Trace-ID"] = getattr(
                request.state, "response_trace_id", request.state.trace_id
            )
            return response
        except Exception:
            # Catch before Starlette's outer error middleware can re-raise into
            # server traceback logging. Never include the exception or input.
            return error_response(request, 500, "INTERNAL_ERROR", "An internal error occurred.")
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            if path not in UNLOGGED_ROUTES or status >= 500:
                logger.info(
                    json.dumps(
                        {
                            "event": "http_request",
                            "timestamp": utc_now().isoformat(),
                            "trace_id": request.state.trace_id,
                            "response_trace_id": getattr(
                                request.state, "response_trace_id", request.state.trace_id
                            ),
                            "outcome": getattr(request.state, "outcome_code", None),
                            "method": request.method,
                            "route": path,
                            "status": status,
                            "duration_ms": round((perf_counter() - started) * 1000, 2),
                        }
                    )
                )

    @application.exception_handler(ApiError)
    async def domain_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message, exc.retryable)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        # Never serialize Pydantic's input values or echo malformed request contents.
        return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed.")

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request, _exc):
        return error_response(request, 503, "SERVICE_UNAVAILABLE", "Database unavailable.", True)

    @application.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return error_response(request, exc.status_code, code, "Request could not be handled.")

    @application.exception_handler(Exception)
    async def unexpected_error(request, _exc):
        return error_response(request, 500, "INTERNAL_ERROR", "An internal error occurred.")

    application.include_router(router)
    application.include_router(booking_router)
    application.include_router(chat_router)
    return application


app = create_app()
