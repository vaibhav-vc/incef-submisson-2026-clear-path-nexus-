"""HTTP API: `uvicorn india_rail.api:app --port 8100`."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import Field

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

app = FastAPI(
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
