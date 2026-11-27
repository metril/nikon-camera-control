"""Sign-in routes: app password, sessions and the kiosk device token."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.auth import (
    AuthSessionListOut,
    AuthSessionOut,
    AuthStatusOut,
    KioskCodeIn,
    KioskCodeOut,
    KioskPairIn,
    LoginIn,
    PasswordDeleteIn,
    PasswordSetIn,
    RevokedOut,
)
from backend.api.schemas.common import ErrorResponse, Ok
from backend.core.auth import SESSION_COOKIE, AuthState, LoginLimiter, sha256_hex
from backend.core.errors import AppError, Forbidden, InvalidState, RateLimited, Unauthorized
from backend.core.security import (
    _auth_state,
    _current_hash,
    _key_valid,
    authenticate,
    clear_session_cookie,
    current_auth,
    is_protected,
    require_api_key,
    secure_cookie,
    set_session_cookie,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
OPEN_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Invalid credentials"},
    422: ERROR_RESPONSES[422],
    429: {"model": ErrorResponse, "description": "Too many failed attempts (see Retry-After)"},
    500: ERROR_RESPONSES[500],
}
Authed = Depends(require_api_key)


def _auth(request: Request) -> AuthState:
    auth = _auth_state(request.app.state)
    if auth is None:  # not wired: refuse rather than guess
        raise AppError("Authentication is not available")
    return auth


AuthDep = Annotated[AuthState, Depends(_auth)]


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _status(request: Request, cookie: str | None) -> AuthStatusOut:
    state = request.app.state
    auth = _auth_state(state)
    ctx = authenticate(state, None, cookie)[0] if cookie else None
    if ctx is None:
        ctx = authenticate(state, request.headers.get("x-api-key"), None)[0]
    return AuthStatusOut(
        auth_required=is_protected(state),
        password_set=auth is not None and auth.password.is_set,
        api_key_set=bool(_current_hash(state)),
        authenticated=ctx is not None,
        session_kind=ctx.kind if ctx is not None else None,
    )


def _attempt(auth: AuthState, request: Request, limiter: LoginLimiter | None = None) -> float:
    """Record an attempt up front; 429 when the limiter is exhausted."""
    wait, mark = (limiter or auth.limiter).attempt(_ip(request))
    if wait > 0:
        raise RateLimited(wait)
    return mark


async def _verify_password(auth: AuthState, password: str) -> bool:
    async with auth.hash_slots:  # bound concurrent scrypt work (16 MiB each)
        return await asyncio.to_thread(auth.password.verify, password)


async def _check_current(auth: AuthState, request: Request, current: str | None) -> None:
    """Verify the current password, rate-limited. 403 on a wrong or missing one."""
    mark = _attempt(auth, request)
    if auth.password.state == "locked":
        raise Forbidden("The password file is unusable; remove it on the host to reset")
    if not current or not await _verify_password(auth, current):
        raise Forbidden("Current password is incorrect")
    auth.limiter.forgive(_ip(request), mark)


def _new_session(
    auth: AuthState, request: Request, response: Response, kind: Literal["browser", "kiosk"]
) -> str:
    token = auth.sessions.create(kind, request.headers.get("user-agent"))
    set_session_cookie(response, token, secure=secure_cookie(request))
    return token


@router.get(
    "/status",
    operation_id="get_auth_status",
    response_model=AuthStatusOut,
    responses={500: ERROR_RESPONSES[500]},
)
async def get_auth_status(request: Request) -> AuthStatusOut:
    """Open. What the login screen needs: whether sign-in is required and whether it is done."""
    return _status(request, request.cookies.get(SESSION_COOKIE))


@router.post("/login", operation_id="login", response_model=AuthStatusOut, responses=OPEN_RESPONSES)
async def login(
    body: LoginIn, request: Request, response: Response, auth: AuthDep
) -> AuthStatusOut:
    """Open, rate-limited (429 with Retry-After). Sets the session cookie.

    ``password`` signs in with the app password. ``api_key`` works only while no password is set.
    """
    mark = _attempt(auth, request)
    ok = False
    if body.password is not None:
        ok = auth.password.is_set and await _verify_password(auth, body.password)
    elif auth.password.state == "none":
        ok = _key_valid(body.api_key, _current_hash(request.app.state))
    if not ok:
        raise Unauthorized("Invalid credentials")
    auth.limiter.forgive(_ip(request), mark)
    token = _new_session(auth, request, response, "browser")
    return _status(request, token)


@router.post(
    "/logout",
    operation_id="logout",
    response_model=Ok,
    responses={500: ERROR_RESPONSES[500]},
)
async def logout(request: Request, response: Response, auth: AuthDep) -> Ok:
    """Open. Revokes this browser's session and clears its cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.sessions.revoke_token(token)
    clear_session_cookie(response)
    return Ok()


@router.put(
    "/password",
    operation_id="set_password",
    response_model=AuthStatusOut,
    dependencies=[Authed],
    responses=ERROR_RESPONSES,
)
async def set_password(
    body: PasswordSetIn, request: Request, response: Response, auth: AuthDep
) -> AuthStatusOut:
    """Set or change the app password; signs this browser in and revokes other browser sessions.

    ``current`` is required only when a password is already set (403 when wrong).
    """
    if auth.password.is_set:
        await _check_current(auth, request, body.current)
    async with auth.hash_slots:
        await asyncio.to_thread(auth.password.set, body.new)
    token = _new_session(auth, request, response, "browser")
    auth.sessions.revoke_browsers_except(sha256_hex(token)[:16])
    return _status(request, token)


@router.delete(
    "/password",
    operation_id="delete_password",
    response_model=AuthStatusOut,
    dependencies=[Authed],
    responses=ERROR_RESPONSES,
)
async def delete_password(
    body: PasswordDeleteIn, request: Request, response: Response, auth: AuthDep
) -> AuthStatusOut:
    """Remove the app password (needs the current one). Browser sessions are revoked; with
    no API key either, the app returns to open mode."""
    if not auth.password.is_set:
        raise InvalidState("No password is set")
    await _check_current(auth, request, body.current)
    auth.password.clear()
    auth.sessions.revoke_kind("browser")
    clear_session_cookie(response)
    return _status(request, None)


@router.get(
    "/sessions",
    operation_id="list_auth_sessions",
    response_model=AuthSessionListOut,
    dependencies=[Authed],
    responses=ERROR_RESPONSES,
)
async def list_auth_sessions(request: Request, auth: AuthDep) -> AuthSessionListOut:
    cur = current_auth(request).session_id
    rows = sorted(auth.sessions.list(), key=lambda s: s.last_seen, reverse=True)
    return AuthSessionListOut(
        sessions=[
            AuthSessionOut(
                id=s.id,
                kind=s.kind,
                created=s.created,
                last_seen=s.last_seen,
                user_agent=s.user_agent,
                current=s.id == cur,
            )
            for s in rows
        ]
    )


@router.post(
    "/sessions/revoke-all",
    operation_id="revoke_all_auth_sessions",
    response_model=RevokedOut,
    dependencies=[Authed],
    responses=ERROR_RESPONSES,
)
async def revoke_all_auth_sessions(request: Request, auth: AuthDep) -> RevokedOut:
    """Sign out every other browser. Keeps this session and the kiosk sessions."""
    keep = current_auth(request).session_id
    return RevokedOut(revoked=auth.sessions.revoke_browsers_except(keep))


@router.delete(
    "/sessions/{session_id}",
    operation_id="revoke_auth_session",
    response_model=Ok,
    dependencies=[Authed],
    responses=ERROR_RESPONSES,
)
async def revoke_auth_session(
    session_id: str, request: Request, response: Response, auth: AuthDep
) -> Ok:
    if not auth.sessions.revoke_id(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if current_auth(request).session_id == session_id:
        clear_session_cookie(response)
    return Ok()


@router.post(
    "/kiosk/code",
    operation_id="get_kiosk_pairing_code",
    response_model=KioskCodeOut,
    responses=OPEN_RESPONSES,
)
async def get_kiosk_pairing_code(
    body: KioskCodeIn, request: Request, auth: AuthDep
) -> KioskCodeOut:
    """Open, rate-limited. Trades the kiosk device token for a single-use code (30 s)."""
    mark = _attempt(auth, request, auth.kiosk_limiter)
    if not await asyncio.to_thread(auth.kiosk.verify, body.token):
        raise Unauthorized("Invalid kiosk token")
    auth.kiosk_limiter.forgive(_ip(request), mark)
    return KioskCodeOut(code=auth.kiosk_codes.issue())


@router.post(
    "/kiosk", operation_id="pair_kiosk", response_model=AuthStatusOut, responses=OPEN_RESPONSES
)
async def pair_kiosk(
    body: KioskPairIn, request: Request, response: Response, auth: AuthDep
) -> AuthStatusOut:
    """Open, rate-limited. Redeems a pairing code for a kiosk session cookie."""
    mark = _attempt(auth, request, auth.kiosk_limiter)
    if not auth.kiosk_codes.redeem(body.code):
        raise Unauthorized("Invalid or expired pairing code")
    auth.kiosk_limiter.forgive(_ip(request), mark)
    token = _new_session(auth, request, response, "kiosk")
    return _status(request, token)


@router.post(
    "/kiosk-token/rotate",
    operation_id="rotate_kiosk_token",
    response_model=RevokedOut,
    dependencies=[Authed],
    responses=ERROR_RESPONSES,
)
async def rotate_kiosk_token(auth: AuthDep) -> RevokedOut:
    """Write a new kiosk token file and revoke every kiosk session (the kiosk re-pairs)."""
    try:
        await asyncio.to_thread(auth.kiosk.rotate)
    except OSError:
        log.exception("could not write the kiosk token")
        raise AppError("The kiosk token file could not be written") from None
    return RevokedOut(revoked=auth.sessions.revoke_kind("kiosk"))
