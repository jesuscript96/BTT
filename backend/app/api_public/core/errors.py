"""Error handling for the public API.

CRITICAL (docs/b2d-gateway/01 §1.2): responses NEVER leak internals — no stack
traces, no internal file/function names, no `str(exc)` of unexpected errors.
Every error is mapped to a fixed envelope: {error: {code, message, request_id, details?}}.
The real trace goes to server-side logs keyed by request_id.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("edgecute.api")

# Closed catalog of error codes (docs/b2d-gateway/03 §6).
ERROR_CODES = {
    "unauthorized": 401,
    "invalid_api_key": 401,
    "forbidden": 403,
    "rate_limited": 429,
    "insufficient_credits": 402,
    "universe_too_large": 422,
    "invalid_strategy": 422,
    "invalid_universe": 422,
    "validation_error": 422,
    "not_implemented": 501,
    "job_not_found": 404,
    "job_failed": 500,
    "conflict": 409,
    "internal_error": 500,
}


class ApiError(Exception):
    """Raise anywhere in the API to produce a safe, structured error response."""

    def __init__(
        self,
        code: str,
        message: str,
        status: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        if code not in ERROR_CODES:
            # Defensive: never emit an unknown code.
            code = "internal_error"
        self.code = code
        self.message = message
        self.status = status or ERROR_CODES[code]
        self.details = details or {}
        super().__init__(message)


def _envelope(code: str, message: str, request_id: str, details: dict | None = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        err["details"] = details
    return {"error": err}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "req_unknown")


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    rid = _request_id(request)
    # 5xx are logged with detail; 4xx are client-actionable and logged at info.
    if exc.status >= 500:
        logger.error("api_error code=%s rid=%s: %s", exc.code, rid, exc.message)
    else:
        logger.info("api_error code=%s rid=%s: %s", exc.code, rid, exc.message)
    return JSONResponse(
        status_code=exc.status,
        content=_envelope(exc.code, exc.message, rid, exc.details),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    rid = _request_id(request)
    # Surface field paths so the LLM/dev can self-correct — but no internals.
    details = {
        "fields": [
            {
                "path": ".".join(str(p) for p in e.get("loc", []) if p != "body"),
                "message": e.get("msg", "invalid"),
            }
            for e in exc.errors()
        ]
    }
    return JSONResponse(
        status_code=422,
        content=_envelope("validation_error", "Entrada inválida.", rid, details),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all. NEVER leaks the exception. Logs the real trace server-side."""
    rid = _request_id(request)
    logger.error("internal_error rid=%s", rid, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=_envelope("internal_error", "Error interno.", rid),
    )


def install_error_handlers(app) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
