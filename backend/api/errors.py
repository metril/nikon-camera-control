"""Single error envelope and request-id middleware."""

from __future__ import annotations

import json
import logging
import uuid
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.api.schemas.common import ErrorResponse
from backend.core.errors import AppError, ErrorCode

log = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: ErrorCode.UNAUTHORIZED,
    403: "FORBIDDEN",
    404: ErrorCode.NOT_FOUND,
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: ErrorCode.VALIDATION_ERROR,
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL",
    501: "NOT_IMPLEMENTED",
    503: "SERVICE_UNAVAILABLE",
}

# Use as ``responses=ERROR_RESPONSES`` on routes so OpenAPI documents the envelope.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": desc}
    for code, desc in {
        401: "Missing or invalid API key",
        404: "Not found",
        409: "Conflict with current state",
        422: "Validation error",
        500: "Internal error",
        503: "Camera unavailable",
    }.items()
}


class RequestIdMiddleware:
    """Pure-ASGI middleware: assigns ``scope['state']['request_id']`` and echoes it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _rid(request: Request) -> str | None:
    state = request.scope.get("state") or {}
    return state.get("request_id")


def _envelope(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = _rid(request)
    body = {
        "error": {
            "code": str(code),
            "message": message,
            "details": details or {},
            "request_id": rid,
        }
    }
    hdrs = dict(headers or {})
    if rid:
        hdrs[REQUEST_ID_HEADER] = rid
    return JSONResponse(body, status_code=status, headers=hdrs)


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101
    return _envelope(
        request, exc.http_status, exc.code, exc.message, exc.details, headers=exc.headers
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _STATUS_CODES.get(exc.status_code)
    if code is None:
        code = "CLIENT_ERROR" if exc.status_code < 500 else "INTERNAL"
    try:
        default = HTTPStatus(exc.status_code).phrase
    except ValueError:
        default = "Error"
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else default
    return _envelope(
        request, exc.status_code, code, message, headers=dict(exc.headers or {}) or None
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = json.loads(json.dumps(jsonable_encoder(exc.errors(), custom_encoder={Exception: str})))
    for e in errors:
        e.pop("input", None)
        e.pop("url", None)
    return _envelope(
        request, 422, ErrorCode.VALIDATION_ERROR, "Request validation failed", {"errors": errors}
    )


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    rid = _rid(request)
    log.error(
        "unhandled error request_id=%s %s %s",
        rid,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _envelope(request, 500, "INTERNAL", "Internal server error")


def install_error_handlers(app: FastAPI) -> None:
    """Register envelope handlers and the request-id middleware on ``app``."""
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    # Exception handler is served by ServerErrorMiddleware (outside the request-id
    # middleware's response path), so it reads the id from scope state instead.
    app.add_exception_handler(Exception, _unhandled)
    app.add_middleware(RequestIdMiddleware)
