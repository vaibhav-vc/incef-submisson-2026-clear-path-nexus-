"""Access control, rate limiting and HTTP hardening for the India Rail AI service.

Roles (least privilege):
  viewer      read state, timetable, cab advisories          RAILGUARD_VIEWER_TOKEN
  controller  everything a viewer can, plus decisions        RAILGUARD_CONTROLLER_TOKEN
  feed        report observations only (TwinTrack/TrackSense) RAILGUARD_FEED_TOKEN

RAILGUARD_MODE=production makes every role token mandatory (32+ characters);
until they are configured the service refuses all requests (fails closed).
In the default demo mode a role is open only when its token is unset.

Tokens arrive as `Authorization: Bearer <token>` (or the legacy X-Controller-Token /
X-Feed-Token headers) and are compared in constant time. They are never logged.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

ROLE_ENV = {
    "viewer": "RAILGUARD_VIEWER_TOKEN",
    "controller": "RAILGUARD_CONTROLLER_TOKEN",
    "feed": "RAILGUARD_FEED_TOKEN",
}
MIN_TOKEN_LENGTH = 32
MAX_BODY_BYTES = 64 * 1024
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
)


class StrictRequest(BaseModel):
    """Base for every request body: exact JSON types (no "5" for 5, no true for 1), no unknown fields,
    no NaN or Infinity (which would otherwise poison clocks and scores)."""

    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without echoing the client's input (the default echo can reflect markup or fail on NaN)."""

    errors = [
        {"loc": [str(part) for part in e.get("loc", ())], "msg": str(e.get("msg", ""))[:200], "type": e.get("type")}
        for e in exc.errors()[:20]
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


def production() -> bool:
    return os.environ.get("RAILGUARD_MODE", "demo").lower() == "production"


def configuration_problems() -> list[str]:
    """Why a production deployment is not safe to serve (empty list = OK)."""

    if not production():
        return []
    problems = []
    for role, env in ROLE_ENV.items():
        token = os.environ.get(env, "")
        if len(token) < MIN_TOKEN_LENGTH:
            problems.append(f"{env} must be set to at least {MIN_TOKEN_LENGTH} characters ({role} role)")
    tokens = [os.environ.get(env, "") for env in ROLE_ENV.values()]
    if len(set(tokens)) != len(tokens):
        problems.append("role tokens must all differ")
    if not os.environ.get("RAILGUARD_ALLOWED_HOSTS"):
        problems.append("RAILGUARD_ALLOWED_HOSTS must list the host names this service answers to")
    if not os.environ.get("RAILGUARD_AUDIT_DIR"):
        # the decision record, the shadow trial and cab-link revocations must survive a restart
        problems.append("RAILGUARD_AUDIT_DIR must name the folder where the audit log is kept")
    return problems


def _supplied(request: Request) -> list[str]:
    tokens = []
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tokens.append(auth[7:].strip())
    for header in ("x-controller-token", "x-feed-token", "x-viewer-token"):
        if request.headers.get(header):
            tokens.append(request.headers[header])
    return tokens


def _matches(env: str, supplied: list[str]) -> bool:
    expected = os.environ.get(env, "")
    return bool(expected) and any(hmac.compare_digest(expected.encode(), s.encode()) for s in supplied)


RANK = {"viewer": 0, "controller": 1, "admin": 2}


def _session_user(supplied: list[str]) -> dict | None:
    from india_rail import accounts

    store = accounts.accounts()
    if store is None:
        return None
    for token in supplied:
        user = store.session(token)
        if user:
            return user
    return None


def authorised(request: Request, role: str) -> bool:
    """Shared role tokens (screens and devices) or a named user's session (people). Admin is sessions only;
    with RAILGUARD_REQUIRE_ACCOUNTS=1 decisions are too."""

    from india_rail import accounts

    supplied = _supplied(request)
    if role == "viewer":
        # A controller may read everything; a feed device may not.
        shared = _open("viewer") or _matches(ROLE_ENV["viewer"], supplied) or _matches(ROLE_ENV["controller"], supplied)
    elif role == "controller":
        shared = not accounts.required() and (_open(role) or _matches(ROLE_ENV[role], supplied))
    elif role == "feed":
        return _open(role) or _matches(ROLE_ENV[role], supplied)
    else:
        shared = False
    user = _session_user(supplied) if supplied else None
    if user is not None:
        request.state.user = user
        if user["must_change"] and role != "viewer":
            return False  # a first (administrator-set) password must be changed before any decision
        return RANK[user["role"]] >= RANK[role]
    return shared


def _open(role: str) -> bool:
    return not production() and not os.environ.get(ROLE_ENV[role])


def require(role: str) -> Callable[[Request], None]:
    """FastAPI dependency enforcing a role."""

    def check(request: Request) -> None:
        problems = configuration_problems()
        if problems:
            raise HTTPException(status_code=503, detail="Service security is not configured")
        if not authorised(request, role):
            raise HTTPException(status_code=403, detail="Not authorised for this action")

    check.__name__ = f"require_{role}"
    return check


class RateLimiter:
    """Token bucket per (client, bucket). Bounded memory: least-recently-seen clients are evicted."""

    def __init__(self, max_clients: int = 10_000, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.buckets: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()
        self.max_clients = max_clients
        self.lock = threading.Lock()

    def allow(self, client: str, bucket: str, rate: float, burst: float) -> bool:
        now = self.clock()
        key = (client, bucket)
        with self.lock:
            tokens, last = self.buckets.pop(key, (burst, now))
            tokens = min(burst, tokens + (now - last) * rate)
            allowed = tokens >= 1.0
            self.buckets[key] = (tokens - 1.0 if allowed else tokens, now)
            while len(self.buckets) > self.max_clients:
                self.buckets.popitem(last=False)
            return allowed


LIMITER = RateLimiter()
LIMITS = {"read": (20.0, 60.0), "write": (5.0, 20.0), "heavy": (1.0, 5.0)}  # (per second, burst)


def limit(bucket: str) -> Callable[[Request], None]:
    rate, burst = LIMITS[bucket]

    def check(request: Request) -> None:
        if os.environ.get("RAILGUARD_RATE_LIMIT", "on") == "off":
            return
        client = request.client.host if request.client else "unknown"
        if not LIMITER.allow(client, bucket, rate, burst):
            raise HTTPException(status_code=429, detail="Too many requests")

    check.__name__ = f"limit_{bucket}"
    return check


class HardeningMiddleware:
    """Pure ASGI: body-size cap, host allow-list (production) and security headers on every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            await _reject(send, 413, b"Request body too large")
            return
        if length is None and b"transfer-encoding" in headers:
            await _reject(send, 411, b"Content-Length required")  # no unbounded chunked uploads
            return
        allowed = os.environ.get("RAILGUARD_ALLOWED_HOSTS")
        if allowed:
            host = headers.get(b"host", b"").decode("latin-1").split(":")[0].lower()
            if host not in {h.strip().lower() for h in allowed.split(",")}:
                await _reject(send, 400, b"Invalid host")
                return
        declared = int(length or 0)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > declared:
                    raise ValueError("request body longer than its Content-Length")
            return message

        async def secured_send(message):
            if message["type"] == "http.response.start":
                path = scope.get("path", "")
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
                ]
                if path != "/docs":  # development-only Swagger UI loads its own scripts; disabled in production
                    extra.append((b"content-security-policy", CSP.encode()))
                if not path.startswith("/railguard/static/"):
                    extra.append((b"cache-control", b"no-store"))
                if production():
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, limited_receive, secured_send)


async def _reject(send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
