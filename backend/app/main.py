"""The FastAPI app (SPEC-07). Run with `uvicorn backend.app.main:app --port 8000`.

Everything is under `/api`; OpenAPI docs are at `/docs`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.app.config import get_settings
from backend.app.llm import LLMUnavailableError
from backend.app.memory import MemoryUnavailableError
from backend.app.routers import data, decisions, demo, insights, runs
from backend.app.routers.common import (
    CONFLICT,
    LLM_UNAVAILABLE,
    MEMORY_OFFLINE,
    NOT_FOUND,
    VALIDATION_ERROR,
    ApiError,
)
from backend.app.services import Services

logger = logging.getLogger(__name__)

UI_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
"""The Vite dev server (SPEC-08)."""

_CODES = {404: NOT_FOUND, 409: CONFLICT, 422: VALIDATION_ERROR}


def create_app(services: Services | None = None) -> FastAPI:
    """`services` is for tests; by default they are built from `.env` at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc = services or Services.from_settings(get_settings())
        svc.start()
        app.state.services = svc
        try:
            yield
        finally:
            svc.close()

    app = FastAPI(
        title="Recon API",
        description="GST input tax credit reconciliation that learns from the accountant.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=UI_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    for module in (data, runs, decisions, insights, demo):
        app.include_router(module.router, prefix="/api")
    _add_error_handlers(app)
    return app


def _envelope(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only locations and messages: echoing the input could echo something sensitive.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return _envelope(422, VALIDATION_ERROR, problems or "invalid request")

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return _envelope(exc.status_code, _CODES.get(exc.status_code, "HTTP_ERROR"), exc.detail)

    @app.exception_handler(MemoryUnavailableError)
    async def memory_down(_: Request, exc: MemoryUnavailableError) -> JSONResponse:
        return _envelope(503, MEMORY_OFFLINE, "Hindsight is unreachable")

    @app.exception_handler(LLMUnavailableError)
    async def llm_down(_: Request, exc: LLMUnavailableError) -> JSONResponse:
        return _envelope(503, LLM_UNAVAILABLE, "the language model is unavailable")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return _envelope(500, "INTERNAL_ERROR", "unexpected server error; see the server log")


app = create_app()
