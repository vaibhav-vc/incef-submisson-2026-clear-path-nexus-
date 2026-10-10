"""HTTP API: `uvicorn india_rail.api:app --port 8100`."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from india_rail.railguard import ops
from india_rail.railguard.api import STATIC as RAILGUARD_STATIC
from india_rail.railguard.api import pages as railguard_pages
from india_rail.railguard.api import router as railguard_router
from india_rail.security import (
    HardeningMiddleware,
    StrictRequest,
    configuration_problems,
    limit,
    production,
    require,
    validation_error_handler,
)
from india_rail.services import Services


def _warm_up() -> None:
    """Load the national twin and the feed gateway, restore the last checkpoint, then report ready."""

    from india_rail.railguard.api import _gateway, national

    try:
        twin = national()
        try:
            gateway = _gateway()
        except ValueError:
            gateway = None  # feed keys malformed: the feed endpoint reports it; the twin still serves
        ops.OPS.attach(twin, gateway)
        ops.OPS.check_clock()  # CERT-In: the clock against NIC/NPL NTP from the start (no-op when not configured)
    except Exception:
        ops.log.exception("national twin failed to load", extra={"event": "WARM_UP_FAILED"})


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Production start-up: JSON logs, twin warm-up and restore, power and checkpoint supervision."""

    enabled = os.environ.get("RAILGUARD_OPS", "1" if production() else "0") == "1"
    if enabled:
        ops.configure_logging()
        supervisor = ops.reset()
        threading.Thread(target=_warm_up, name="railguard-warm-up", daemon=True).start()
        supervisor.poll_power()
        supervisor.start()
    yield
    if enabled:
        ops.OPS.shutdown()


app = FastAPI(
    lifespan=lifespan,
    title="India Rail AI",
    version="0.1.0",
    description=(
        "Timetable intelligence, run-time prediction and disruption re-planning over the open "
        "Indian Railways timetable. Every plan is a proposal for a human controller."
    ),
    # Interactive docs load third-party scripts and advertise every endpoint: development only.
    docs_url=None if production() else "/docs",
    redoc_url=None,
    openapi_url=None if production() else "/openapi.json",
)


app.add_middleware(HardeningMiddleware)
app.add_middleware(ops.ObservabilityMiddleware, metrics=ops.METRICS)
app.add_exception_handler(RequestValidationError, validation_error_handler)
# Nexus RailGuard: digital-twin controller console, cab advisory and TwinTrack feed.
app.include_router(railguard_router)
app.include_router(railguard_pages)
app.mount("/railguard/static", StaticFiles(directory=RAILGUARD_STATIC), name="railguard-static")
READ = [Depends(require("viewer")), Depends(limit("read"))]
HEAVY = [Depends(require("viewer")), Depends(limit("heavy"))]


@lru_cache(maxsize=1)
def services() -> Services:
    return Services()


def _require(value: Any, what: str) -> Any:
    if value is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return value


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness and configuration status only; no operational data without a token."""

    problems = configuration_problems()
    return {"status": "ok" if not problems else "misconfigured", "security_configured": not problems}


@app.get("/health/live", include_in_schema=False)
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", include_in_schema=False)
def health_ready() -> JSONResponse:
    """For load balancers: 200 only when this instance can serve controllers safely."""

    state = ops.OPS.readiness()
    public = {"ready": state["ready"], "checks": state["checks"], "power": state["power"]["level"],
              "read_only": state["read_only"]}  # fmt: skip
    return JSONResponse(public, status_code=200 if state["ready"] else 503)


@app.get("/metrics", dependencies=READ, include_in_schema=False)
def metrics() -> PlainTextResponse:
    gauges, labelled = ops.OPS.gauges()
    return PlainTextResponse(ops.OPS.metrics.render(gauges, labelled), media_type="text/plain; version=0.0.4")


# ---- named user accounts ---------------------------------------------------------------------------------
LOGIN = [Depends(limit("write"))]
ADMIN = [Depends(require("admin")), Depends(limit("write"))]


def _store():
    from india_rail import accounts

    store = accounts.accounts()
    if store is None:
        raise HTTPException(
            status_code=503, detail="No accounts yet: create the first with python -m india_rail accounts add"
        )
    return store


def _audit(kind: str, actor: str, details: dict[str, Any]) -> None:
    twin = ops.OPS.twin
    if twin is not None:
        with twin.lock:
            twin.audit.record(int(twin.now * 60), kind, actor, details)
    ops.log.info(kind.lower(), extra={"event": kind})


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


class LoginRequest(StrictRequest):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=256)


@app.post("/auth/login", dependencies=LOGIN)
def login(body: LoginRequest) -> dict[str, Any]:
    from india_rail.accounts import AuthError

    try:
        session = _store().login(body.username, body.password)
    except AuthError as exc:
        _audit("LOGIN_FAILED", body.username if len(body.username) <= 40 else "?", {})
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _audit("LOGIN", body.username, {"role": session["role"]})
    return session


@app.post("/auth/logout", dependencies=[Depends(require("viewer"))])
def logout(request: Request) -> dict[str, str]:
    _store().logout(_bearer(request))
    return {"status": "logged out"}


@app.get("/auth/me", dependencies=[Depends(require("viewer"))])
def me(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=404, detail="Not a personal session (shared screen token)")
    return user


class PasswordChange(StrictRequest):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def _session_present(request: Request) -> None:
    """Credentials are checked before the body: no session, no password change (401, not a validation error)."""

    if not _bearer(request):
        raise HTTPException(status_code=401, detail="Sign in first", headers={"WWW-Authenticate": "Bearer"})


@app.post("/auth/password", dependencies=[Depends(_session_present), *LOGIN])
def change_password(body: PasswordChange, request: Request) -> dict[str, str]:
    from india_rail.accounts import AuthError

    store = _store()
    user = store.session(_bearer(request))
    if user is None:
        raise HTTPException(status_code=401, detail="Log in first")
    try:
        store.change_password(user["username"], body.old_password, body.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit("PASSWORD_CHANGED", user["username"], {})
    return {"status": "password changed: log in again"}


class NewUser(StrictRequest):
    username: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,39}$")
    display_name: str = Field(min_length=1, max_length=80, pattern=r"^[\w .'()-]+$")
    role: str = Field(pattern="^(viewer|controller|admin)$")
    initial_password: str = Field(min_length=12, max_length=256)


@app.get("/auth/users", dependencies=ADMIN)
def list_users() -> list[dict[str, Any]]:
    return _store().users()


@app.post("/auth/users", dependencies=ADMIN)
def add_user(body: NewUser, request: Request) -> dict[str, str]:
    try:
        _store().add(body.username, body.display_name, body.role, body.initial_password, must_change=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit("ACCOUNT_CREATED", request.state.user["username"], {"username": body.username, "role": body.role})
    return {"status": "created; the user must change the password at first login"}


@app.post("/auth/users/{username}/{action}", dependencies=ADMIN)
def set_user_state(
    request: Request, username: str = PathParam(pattern=r"^[a-z][a-z0-9._-]{2,39}$"),
    action: str = PathParam(pattern="^(disable|enable)$"),
) -> dict[str, str]:  # fmt: skip
    try:
        _store().set_disabled(username, action == "disable")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown user") from exc
    _audit("ACCOUNT_" + action.upper() + "D", request.state.user["username"], {"username": username})
    return {"status": f"{action}d"}


@app.get("/summary", dependencies=READ)
def summary() -> dict[str, Any]:
    svc = services()
    return {"model_loaded": svc.model is not None, **svc.network.summary()}


@app.get("/trains/search", dependencies=READ)
def search_trains(q: str = Query(min_length=1, max_length=80)) -> list[dict[str, Any]]:
    return services().network.search_trains(q)


@app.get("/trains/{number}", dependencies=READ)
def train(number: str) -> dict[str, Any]:
    net = services().network
    info = _require(net.train(number), "Train")
    return {"train": info, "stops": net.schedule(number)}


@app.get("/trains/{number}/working-schedule", dependencies=READ)
def train_working_schedule(number: str) -> dict[str, Any]:
    """Every stop with day, dwell, distance and section speed, plus the train's metrics and data-quality flags."""

    from india_rail.schedules import working_schedule

    return _require(working_schedule(services().con, number), "Train")


@app.get("/trains/{number}/slack", dependencies=READ)
def train_slack(number: str) -> dict[str, Any]:
    result = services().timetable_slack(number)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/stations/search", dependencies=READ)
def search_stations(q: str = Query(min_length=1, max_length=80)) -> list[dict[str, Any]]:
    return services().network.search_stations(q)


@app.get("/stations/{code}/board", dependencies=READ)
def station_board(code: str, limit: int = Query(40, ge=1, le=200)) -> dict[str, Any]:
    net = services().network
    station = _require(net.station(code), "Station")
    return {"station": station, "trains": net.station_board(code, limit)}


@app.get("/between", dependencies=READ)
def between(origin: str, destination: str, limit: int = Query(25, ge=1, le=100)) -> list[dict[str, Any]]:
    return services().network.trains_between(origin, destination, limit)


@app.get("/sections/busiest", dependencies=READ)
def busiest(limit: int = Query(20, ge=1, le=100), zone: str | None = None) -> list[dict[str, Any]]:
    return services().network.busiest_sections(limit, zone)


@app.get("/path", dependencies=READ)
def path(origin: str, destination: str) -> dict[str, Any]:
    return _require(services().network.fastest_path(origin, destination), "Path")


class DisruptionRequest(StrictRequest):
    train_number: str = Field(min_length=1, max_length=10)
    station_code: str = Field(min_length=1, max_length=10)
    delay_min: int = Field(ge=1, le=720)
    headway_min: int = Field(6, ge=2, le=30)


@app.post("/plan/disruption", dependencies=HEAVY)
def plan_disruption(request: DisruptionRequest) -> dict[str, Any]:
    try:
        return services().plan(request.train_number, request.station_code, request.delay_min, request.headway_min)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AskRequest(StrictRequest):
    question: str = Field(min_length=1, max_length=4000)
    provider: str = Field("auto", pattern="^(auto|offline|ollama|claude)$")


@app.post("/assistant/ask", dependencies=HEAVY)
def ask(request: AskRequest) -> dict[str, str]:
    from india_rail.free_assistant import make_assistant

    # The paid provider is refused unless the server operator opted in, so a
    # caller of a shared deployment can never run up API charges.
    if request.provider == "claude" and os.environ.get("INDIA_RAIL_ALLOW_PAID_ASSISTANT") != "1":
        raise HTTPException(status_code=403, detail="Paid assistant disabled on this server; use auto/offline/ollama")
    # A fresh assistant per request: no conversation state is shared between callers.
    try:
        assistant = make_assistant(services(), request.provider)
        return {"provider": assistant.name, "answer": assistant.ask(request.question)}
    except (ImportError, OSError) as exc:  # Ollama not running, package missing, network error
        raise HTTPException(status_code=503, detail=f"{request.provider} assistant unavailable: {exc}") from exc
