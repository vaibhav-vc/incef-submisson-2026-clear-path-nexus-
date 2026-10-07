"""HTTP API: `uvicorn india_rail.api:app --port 8100`."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from india_rail.services import Services

app = FastAPI(
    title="India Rail AI",
    version="0.1.0",
    description=(
        "Timetable intelligence, run-time prediction and disruption re-planning over the open "
        "Indian Railways timetable. Every plan is a proposal for a human controller."
    ),
)


@lru_cache(maxsize=1)
def services() -> Services:
    return Services()


def _require(value: Any, what: str) -> Any:
    if value is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return value


@app.get("/health")
def health() -> dict[str, Any]:
    svc = services()
    return {"status": "ok", "model_loaded": svc.model is not None, **svc.network.summary()}


@app.get("/trains/search")
def search_trains(q: str = Query(min_length=1, max_length=80)) -> list[dict[str, Any]]:
    return services().network.search_trains(q)


@app.get("/trains/{number}")
def train(number: str) -> dict[str, Any]:
    net = services().network
    info = _require(net.train(number), "Train")
    return {"train": info, "stops": net.schedule(number)}


@app.get("/trains/{number}/slack")
def train_slack(number: str) -> dict[str, Any]:
    result = services().timetable_slack(number)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/stations/search")
def search_stations(q: str = Query(min_length=1, max_length=80)) -> list[dict[str, Any]]:
    return services().network.search_stations(q)


@app.get("/stations/{code}/board")
def station_board(code: str, limit: int = Query(40, ge=1, le=200)) -> dict[str, Any]:
    net = services().network
    station = _require(net.station(code), "Station")
    return {"station": station, "trains": net.station_board(code, limit)}


@app.get("/between")
def between(origin: str, destination: str, limit: int = Query(25, ge=1, le=100)) -> list[dict[str, Any]]:
    return services().network.trains_between(origin, destination, limit)


@app.get("/sections/busiest")
def busiest(limit: int = Query(20, ge=1, le=100), zone: str | None = None) -> list[dict[str, Any]]:
    return services().network.busiest_sections(limit, zone)


@app.get("/path")
def path(origin: str, destination: str) -> dict[str, Any]:
    return _require(services().network.fastest_path(origin, destination), "Path")


class DisruptionRequest(BaseModel):
    train_number: str = Field(min_length=1, max_length=10)
    station_code: str = Field(min_length=1, max_length=10)
    delay_min: int = Field(ge=1, le=720)
    headway_min: int = Field(6, ge=2, le=30)


@app.post("/plan/disruption")
def plan_disruption(request: DisruptionRequest) -> dict[str, Any]:
    try:
        return services().plan(request.train_number, request.station_code, request.delay_min, request.headway_min)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@app.post("/assistant/ask")
def ask(request: AskRequest) -> dict[str, str]:
    if os.environ.get("INDIA_RAIL_ASSISTANT_ENABLED", "1") != "1":
        raise HTTPException(status_code=503, detail="Assistant disabled")
    try:
        from india_rail.assistant import RailAssistant
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Install the anthropic package to use the assistant") from exc
    # A fresh assistant per request: no conversation state is shared between callers.
    return {"answer": RailAssistant(services()).ask(request.question)}
