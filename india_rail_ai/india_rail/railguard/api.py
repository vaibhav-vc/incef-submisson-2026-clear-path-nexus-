"""HTTP interface for Nexus Control, Nexus Cab, the TwinTrack feed and the national twin.

Every endpoint declares a role (see india_rail.security) and a rate-limit bucket:
* viewer: read state and cab advisories (cab screens hold only this token);
* controller: recommend, approve, reject, hold, acknowledge, inject demo faults;
* feed: report observations only, never decisions.
No endpoint reaches signals, points, interlocking, ATP or brakes.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import Field

from india_rail.railguard.cab import build_advisory, compact
from india_rail.railguard.engine import RailGuardEngine
from india_rail.railguard.scenarios import SCENARIOS
from india_rail.security import StrictRequest, limit, production, require

STATIC = Path(__file__).parent / "static"
VIEW = [Depends(require("viewer")), Depends(limit("read"))]
VIEW_HEAVY = [Depends(require("viewer")), Depends(limit("heavy"))]
CONTROL = [Depends(require("controller")), Depends(limit("write"))]
CONTROL_HEAVY = [Depends(require("controller")), Depends(limit("heavy"))]
FEED = [Depends(require("feed")), Depends(limit("write"))]


def _demo_network() -> None:
    """The tabletop twin is a made-up ten-section network for demonstrations: production serves real data only."""

    if production():
        raise HTTPException(status_code=404, detail="Demo network disabled in production: real data only")


DEMO = [Depends(_demo_network)]

router = APIRouter(prefix="/railguard", tags=["railguard"])
pages = APIRouter(tags=["railguard-ui"])
ENGINE = RailGuardEngine()

TRAIN = r"^[A-Z0-9]{1,10}$"
RUN = r"^[0-9A-Z]{1,10}@-?[0-3]$"
NUMBER = r"^[0-9A-Z]{1,10}$"
CODE = r"^[A-Z0-9]{1,8}$"
SECTION = r"^[A-Z0-9]{1,8}(-[A-Z0-9]{1,8})?$"
NAME = r"^[\w .@-]{1,80}$"
SNAPSHOT = r"^SNAP-\d{4,9}$"
PRESET = "^(FASTEST|INFRA_PROTECT|LOWEST_RISK|BALANCED)$"


def _run(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---- pages (no data; every data call they make is authorised separately) -------------------------
@pages.get("/control", include_in_schema=False, dependencies=DEMO)
def control_page() -> FileResponse:
    return FileResponse(STATIC / "control.html")


@pages.get("/control/national", include_in_schema=False)
def national_page() -> FileResponse:
    return FileResponse(STATIC / "national.html")


@pages.get("/cab", include_in_schema=False)
def cab_page() -> FileResponse:
    return FileResponse(STATIC / "cab.html")


# ---- tabletop twin: state and scenarios ---------------------------------------------------------
@router.get("/state", dependencies=VIEW + DEMO)
def state() -> dict[str, Any]:
    return ENGINE.state()


@router.get("/scenarios", dependencies=VIEW + DEMO)
def scenarios() -> list[dict[str, str]]:
    return [{"name": name, "title": spec["title"]} for name, spec in SCENARIOS.items()]


@router.post("/scenarios/{name}/load", dependencies=CONTROL + DEMO)
def load_scenario(name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    with ENGINE.lock:
        SCENARIOS[name]["setup"](ENGINE)
    return ENGINE.state()


@router.post("/scenarios/{name}/run", dependencies=CONTROL_HEAVY + DEMO)
def run_scenario(name: str) -> dict[str, Any]:
    """Run the full scripted scenario on a separate twin (the live demo is untouched)."""

    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    return SCENARIOS[name]["run"](RailGuardEngine())


class TickRequest(StrictRequest):
    seconds: int = Field(60, ge=1, le=3600)


@router.post("/tick", dependencies=CONTROL + DEMO)
def tick(request: TickRequest) -> dict[str, Any]:
    ENGINE.tick(request.seconds)
    return ENGINE.state()


# ---- controller decisions -------------------------------------------------------------------------
class RecommendRequest(StrictRequest):
    preset: str | None = Field(None, pattern=PRESET)
    weights: dict[str, float] | None = Field(None, max_length=7)


@router.post("/recommend", dependencies=CONTROL_HEAVY + DEMO)
def recommend(request: RecommendRequest) -> dict[str, Any]:
    _run(ENGINE.set_weights, request.preset, request.weights)
    return ENGINE.recommend()


class ApproveRequest(StrictRequest):
    snapshot_id: str = Field(pattern=SNAPSHOT)
    candidate_id: str = Field(pattern=r"^[CN]\d{1,2}$")
    controller: str = Field(pattern=NAME)


@router.post("/approve", dependencies=CONTROL + DEMO)
def approve(request: ApproveRequest) -> dict[str, Any]:
    return _run(ENGINE.approve, request.snapshot_id, request.candidate_id, request.controller)


class RejectRequest(StrictRequest):
    snapshot_id: str = Field(pattern=SNAPSHOT)
    controller: str = Field(pattern=NAME)
    reason: str = Field("", max_length=300)


@router.post("/reject", dependencies=CONTROL + DEMO)
def reject(request: RejectRequest) -> dict[str, Any]:
    return _run(ENGINE.reject, request.snapshot_id, request.controller, request.reason)


class HoldRequest(StrictRequest):
    controller: str = Field(pattern=NAME)
    reason: str = Field("Controller hold", max_length=300)
    train_id: str | None = Field(None, pattern=TRAIN)


@router.post("/hold", dependencies=CONTROL + DEMO)
def hold(request: HoldRequest) -> dict[str, Any]:
    if request.train_id and request.train_id not in ENGINE.trains:
        raise HTTPException(status_code=404, detail="Unknown train")
    return _run(ENGINE.hold, request.controller, request.reason, request.train_id)


class AckRequest(StrictRequest):
    by: str = Field(pattern=NAME)


@router.post("/threats/{threat_id}/ack", dependencies=CONTROL + DEMO)
def acknowledge(threat_id: str, request: AckRequest) -> dict[str, Any]:
    return _run(ENGINE.acknowledge, threat_id, request.by)


class FaultRequest(StrictRequest):
    kind: str = Field(pattern="^(freeze_feed|unfreeze_feed|sensor_offline|sensor_online|obstacle|clear_obstacle)$")
    train_id: str | None = Field(None, pattern=TRAIN)
    section_id: str | None = Field(None, pattern=SECTION)


@router.post("/fault", dependencies=CONTROL + DEMO)
def fault(request: FaultRequest) -> dict[str, Any]:
    if request.train_id is not None and request.train_id not in ENGINE.trains:
        raise HTTPException(status_code=404, detail="Unknown train")
    if request.section_id is not None and request.section_id not in ENGINE.net.sections:
        raise HTTPException(status_code=404, detail="Unknown section")
    return _run(ENGINE.inject_fault, request.kind, request.train_id, request.section_id)


# ---- TwinTrack and TrackSense feeds (observations only) ---------------------------------------------------
class PositionReport(StrictRequest):
    train_id: str = Field(pattern=TRAIN)
    section_id: str | None = Field(None, pattern=SECTION)
    from_node: str = Field(pattern=CODE)
    offset_km: float = Field(0.0, ge=0, le=1000)
    speed_kmph: float = Field(0.0, ge=0, le=400)
    t: int | None = Field(None, ge=0)
    sequence: int | None = Field(None, ge=0)
    source: str = Field("TWINTRACK_SENSOR", pattern="^(TWINTRACK_SENSOR|GNSS_SIM)$")


@router.post("/twintrack/position", dependencies=FEED + DEMO)
def twintrack_position(report: PositionReport) -> dict[str, Any]:
    body = report.model_dump(exclude_none=True)
    body.setdefault("t", ENGINE.t)
    return ENGINE.ingest_position(body)


class SectionReport(StrictRequest):
    section_id: str = Field(pattern=SECTION)
    condition: float | None = Field(None, ge=0, le=1)
    temp_restriction_kmph: float | None = Field(None, ge=0, le=200)
    weather_alert: str | None = Field(None, pattern="^(HEAT|FLOOD_WATCH|FOG|CLEAR)$")


def _section_changes(report: SectionReport) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if report.condition is not None:
        changes["condition"] = report.condition
    if report.temp_restriction_kmph is not None:
        changes["temp_restriction_kmph"] = report.temp_restriction_kmph or None
    if report.weather_alert is not None:
        changes["weather_alert"] = None if report.weather_alert == "CLEAR" else report.weather_alert
    return changes


def _update_twin_section(report: SectionReport, source: str) -> dict[str, Any]:
    if report.section_id not in ENGINE.net.sections:
        raise HTTPException(status_code=404, detail="Unknown section")
    return _run(ENGINE.update_section, report.section_id, source, **_section_changes(report)).to_dict()


@router.post("/tracksense/section", dependencies=FEED + DEMO)
def tracksense_section(report: SectionReport) -> dict[str, Any]:
    return _update_twin_section(report, "TRACKSENSE_FEED")


@router.post("/console/section", dependencies=CONTROL + DEMO)
def console_section(report: SectionReport) -> dict[str, Any]:
    """The same section input, entered by a controller from the demo console."""

    return _update_twin_section(report, "CONTROLLER_CONSOLE")


class ObstacleReport(StrictRequest):
    section_id: str = Field(pattern=SECTION)
    detected: bool = True


@router.post("/twintrack/obstacle", dependencies=FEED + DEMO)
def twintrack_obstacle(report: ObstacleReport) -> dict[str, Any]:
    """Tabletop obstacle sensor. Raising is automatic; clearing needs a controller (inspection) action."""

    if report.section_id not in ENGINE.net.sections:
        raise HTTPException(status_code=404, detail="Unknown section")
    if not report.detected:
        return {"ok": True, "note": "Sensor clear noted; obstacle is cleared only by a controller inspection action."}
    return _run(ENGINE.inject_fault, "obstacle", None, report.section_id)


# ---- Nexus Cab (read-only) --------------------------------------------------------------------------
@router.get("/cab/{train_id}", dependencies=VIEW + DEMO)
def cab(train_id: str) -> dict[str, Any]:
    if train_id not in ENGINE.trains:
        raise HTTPException(status_code=404, detail="Unknown train")
    with ENGINE.lock:
        return build_advisory(ENGINE, train_id)


@router.get("/cab/{train_id}/compact", response_class=PlainTextResponse, dependencies=VIEW + DEMO)
def cab_compact(train_id: str) -> str:
    return compact(cab(train_id))


# ---- audit --------------------------------------------------------------------------------------------
@router.get("/audit", dependencies=VIEW + DEMO)
def audit_events(limit_events: int = 200) -> dict[str, Any]:
    with ENGINE.lock:
        count = max(1, min(limit_events, 1000))
        return {"chain_ok": ENGINE.audit.verify_chain(), "events": ENGINE.audit.events[-count:]}


@router.get("/audit/{snapshot_id}", dependencies=VIEW + DEMO)
def snapshot(snapshot_id: str) -> dict[str, Any]:
    with ENGINE.lock:
        if snapshot_id not in ENGINE.audit.snapshots:
            raise HTTPException(status_code=404, detail="Unknown snapshot")
        return ENGINE.audit.snapshots[snapshot_id]


@router.get("/audit/{snapshot_id}/replay", dependencies=VIEW_HEAVY + DEMO)
def replay(snapshot_id: str) -> dict[str, Any]:
    with ENGINE.lock:
        if snapshot_id not in ENGINE.audit.snapshots:
            raise HTTPException(status_code=404, detail="Unknown snapshot")
        return ENGINE.replay(snapshot_id)


# ---- national network twin ------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _national():
    from india_rail.railguard.eta import load_default
    from india_rail.railguard.national import NationalTwin

    twin = NationalTwin()
    twin.eta = load_default()  # forecasts learned from real running, when the model and real data are present
    return twin


def national():
    try:
        return _national()
    except (OSError, sqlite3.Error) as exc:  # timetable database not ingested yet
        raise HTTPException(
            status_code=503, detail="National data unavailable: run `python -m india_rail real build`"
        ) from exc
    except RuntimeError as exc:  # production asked to run on anything but real timetable data
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/national/summary", dependencies=VIEW)
def national_summary() -> dict[str, Any]:
    return national().summary()


@router.get("/national/network", dependencies=VIEW_HEAVY)
def national_network() -> dict[str, Any]:
    return national().network_geometry()


@router.get("/national/positions", dependencies=VIEW)
def national_positions() -> list[list[Any]]:
    return national().positions()


@router.get("/national/runs/{number}", dependencies=VIEW)
def national_runs(number: str) -> list[dict[str, Any]]:
    if not number.isalnum() or len(number) > 10:
        raise HTTPException(status_code=422, detail="Invalid train number")
    return national().runs_for(number.upper())


@router.get("/national/plan/{run}", dependencies=VIEW)
def national_plan(run: str = PathParam(pattern=RUN)) -> dict[str, Any]:
    return _run(national().plan_geometry, run)


@router.get("/national/cab/{run}", dependencies=VIEW)
def national_cab(run: str = PathParam(pattern=RUN)) -> dict[str, Any]:
    return _run(national().cab, run)


# ---- every train and station (registry of the current timetable) ----------------------------------------------
def _registry():
    from india_rail.registry import registry

    try:
        return registry()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503, detail="Train registry not built: run python -m india_rail current build"
        ) from exc


@router.get("/national/trains", dependencies=VIEW)
def national_trains(
    q: Annotated[str, Query(max_length=40, pattern=r"^[0-9A-Za-z .()/-]*$")] = "",
    operator: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, Any]:
    """Search every train by number or name (optionally one operator, e.g. 'IRCTC (private operation)')."""

    return {"trains": _registry().search(q, operator, limit)}


@router.get("/national/operators", dependencies=VIEW)
def national_operators() -> dict[str, Any]:
    return _registry().operators()


@router.get("/national/trains/{number}", dependencies=VIEW)
def national_train(number: str = PathParam(pattern=NUMBER)) -> dict[str, Any]:
    """Number, name, type, operator, running days, validity, every stop with times and PIN, route summary."""

    found = _registry().train(number)
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown train")
    return found


@router.get("/national/trains/{number}/route", dependencies=VIEW_HEAVY)
def national_train_route(number: str = PathParam(pattern=NUMBER)) -> dict[str, Any]:
    """GeoJSON of the track the train follows (real mapped track; unmapped sections drawn straight and flagged)."""

    route = _registry().route(number)
    if route is None:
        raise HTTPException(status_code=404, detail="Unknown train or no route")
    return route


@router.get("/national/stations/{code}", dependencies=VIEW)
def national_station(code: str = PathParam(pattern=CODE)) -> dict[str, Any]:
    found = _registry().station(code)
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown station")
    return found


# ---- Dedicated Freight Corridors -----------------------------------------------------------------------------
class FreightDemand(StrictRequest):
    id: str = Field(pattern=r"^[A-Z0-9-]{1,16}$")
    origin_km: float = Field(ge=0, le=2000)
    destination_km: float = Field(ge=0, le=2000)
    ready_min: float = Field(ge=0, le=2880)
    priority: int = Field(3, ge=1, le=5)


class FreightBlock(StrictRequest):
    segment: int = Field(ge=0, le=500)
    start_min: float = Field(ge=0, le=4320)
    end_min: float = Field(ge=0, le=4320)


class FreightPlanRequest(StrictRequest):
    corridor: str = Field(pattern="^(Eastern|Western)$")
    headway_min: float = Field(10.0, ge=4, le=30)
    loops: int = Field(3, ge=1, le=8)
    trains: list[FreightDemand] = Field(min_length=1, max_length=600)
    blocks: list[FreightBlock] = Field(default_factory=list, max_length=50)


def _corridors() -> dict[str, Any]:
    from india_rail.freight import load_corridors

    try:
        return load_corridors()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503, detail="Freight corridors not built: run python -m india_rail freight build"
        ) from exc


# ---- delay-minimisation advisor (research from real running; advice for people, never an action) ------------
ADVISOR_KINDS = "^(sections|stations|late_starts|timetable|trains)$"


def _advisor() -> dict[str, Any]:
    from india_rail.delay_advisor import registry as advisor

    try:
        return advisor()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503, detail="Delay advisor not built: run python -m india_rail advisor build"
        ) from exc


@router.get("/national/advisor", dependencies=VIEW)
def advisor_summary() -> dict[str, Any]:
    """Where delay is made on the network, measured from real running, and how persistent each finding is."""

    adv = _advisor()
    return {k: adv[k] for k in ("what", "method", "summary")}


@router.get("/national/advisor/{kind}", dependencies=VIEW)
def advisor_findings(
    kind: Annotated[str, PathParam(pattern=ADVISOR_KINDS)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    chronic_only: bool = False,
) -> dict[str, Any]:
    rows = _advisor()[kind]
    if chronic_only:
        rows = [r for r in rows if r.get("chronic", True)]
    return {"kind": kind, "findings": rows[:limit]}


@router.get("/national/advisor/train/{number}", dependencies=VIEW)
def advisor_train(number: Annotated[str, PathParam(pattern=NUMBER)]) -> dict[str, Any]:
    from india_rail.delay_advisor import for_train

    _advisor()
    return for_train(number)


@router.get("/freight/corridors", dependencies=VIEW)
def freight_corridors() -> dict[str, Any]:
    """The Eastern and Western DFC as mapped: length, single/double line, segments, published operating figures."""

    return _corridors()


@router.post("/freight/plan", dependencies=CONTROL_HEAVY)
def freight_plan(request: FreightPlanRequest) -> dict[str, Any]:
    """Conflict-free paths for the given freight trains (demand from FOIS). Advice for the DFC control office."""

    from india_rail.freight import FreightPlanner, FreightTrain, plan_to_dict

    corridor = _corridors()["corridors"].get(request.corridor)
    if corridor is None:
        raise HTTPException(status_code=404, detail="Corridor not mapped")
    planner = FreightPlanner(corridor, request.corridor, request.headway_min, request.loops)
    for b in request.blocks:
        if b.end_min <= b.start_min or b.segment >= len(corridor["segments"]):
            raise HTTPException(status_code=422, detail="Invalid block")
        planner.block(b.segment, b.start_min, b.end_min)
    trains = [FreightTrain(t.id, t.origin_km, t.destination_km, t.ready_min, t.priority) for t in request.trains]
    if len({t.id for t in trains}) != len(trains):
        raise HTTPException(status_code=422, detail="Train ids must be unique")
    summary = planner.plan(trains)
    if summary["violations"]:  # the independent check failed: never hand out an unsafe plan
        raise HTTPException(status_code=500, detail="Plan failed its safety check; not issued")
    return {**summary, "authority": "ADVISORY_ONLY", "plans": [plan_to_dict(p) for p in planner.plans.values()]}


@router.get("/national/eta/{run}", dependencies=VIEW)
def national_eta(run: str = PathParam(pattern=RUN)) -> dict[str, Any]:
    """Forecast delay at each later stop (median and P10-P90), learned from real running. Advice only."""

    twin = national()
    if twin.eta is None:
        raise HTTPException(status_code=503, detail="Forecast model not built: run python -m india_rail real validate")
    with twin.lock:
        if run not in twin.runs:
            raise HTTPException(status_code=404, detail="Unknown run")
        return {"run": run, "basis": twin.eta.source, "stops": twin.eta.forecast(twin, run)}


class NationalDisruption(StrictRequest):
    run: str = Field(pattern=RUN)
    station: str = Field(pattern=CODE)
    delay_min: float = Field(ge=1, le=720)


@router.post("/national/disrupt", dependencies=CONTROL)
def national_disrupt(request: NationalDisruption) -> dict[str, Any]:
    return _run(national().disrupt, request.run, request.station, request.delay_min)


class NationalRecommend(StrictRequest):
    run: str | None = Field(None, pattern=RUN)
    preset: str | None = Field(None, pattern=PRESET)
    weights: dict[str, float] | None = Field(None, max_length=7)


@router.post("/national/recommend", dependencies=CONTROL_HEAVY)
def national_recommend(request: NationalRecommend) -> dict[str, Any]:
    twin = national()
    _run(twin.set_weights, request.preset, request.weights)
    return _run(twin.recommend, request.run)


@router.post("/national/approve", dependencies=CONTROL)
def national_approve(request: ApproveRequest) -> dict[str, Any]:
    return _run(national().approve, request.snapshot_id, request.candidate_id, request.controller)


class NationalTick(StrictRequest):
    minutes: float = Field(1.0, gt=0, le=240)


@router.post("/national/tick", dependencies=CONTROL)
def national_tick(request: NationalTick) -> dict[str, Any]:
    twin = national()
    twin.tick(request.minutes)
    return {"now_min": twin.now}


class NationalSection(StrictRequest):
    section_id: str = Field(pattern=SECTION)
    condition: float | None = Field(None, ge=0, le=1)
    obstacle: bool | None = None
    available: bool | None = None
    temp_restriction_kmph: float | None = Field(None, ge=0, le=200)


@router.post("/national/section", dependencies=CONTROL)
def national_section(request: NationalSection) -> dict[str, Any]:
    twin = national()
    if request.section_id not in twin.net.sections:
        raise HTTPException(status_code=404, detail="Unknown section")
    changes = {k: v for k, v in request.model_dump(exclude={"section_id"}).items() if v is not None}
    if "temp_restriction_kmph" in changes:
        changes["temp_restriction_kmph"] = changes["temp_restriction_kmph"] or None
    return _run(twin.update_section, request.section_id, "CONTROLLER_CONSOLE", **changes).to_dict()


@router.post("/national/threats/{threat_id}/ack", dependencies=CONTROL)
def national_ack(threat_id: str, request: AckRequest) -> dict[str, Any]:
    return _run(national().acknowledge, threat_id, request.by)


@router.post("/national/reset", dependencies=CONTROL)
def national_reset() -> dict[str, Any]:
    twin = national()
    with twin.lock:
        twin.reset()
    return twin.summary()


@router.get("/national/audit/{snapshot_id}/replay", dependencies=VIEW_HEAVY)
def national_replay(snapshot_id: str = PathParam(pattern=SNAPSHOT)) -> dict[str, Any]:
    return _run(national().replay, snapshot_id)


class NationalFeed(StrictRequest):
    run: str = Field(pattern=RUN)
    section_id: str = Field(pattern=SECTION)
    offset_km: float = Field(ge=0, le=1000)


@lru_cache(maxsize=1)
def _shadow():
    from india_rail.railguard.shadow import ShadowTrial

    return ShadowTrial(national())


class ShadowDecision(StrictRequest):
    run: str = Field(pattern=RUN)
    action: str = Field(pattern="^(CONTINUE|HOLD|PATH|PRIORITY|REROUTE)$")
    at_min: float | None = Field(None, ge=0, le=10_000)
    controller: str = Field(pattern=NAME)
    hold_min: float | None = Field(None, ge=0, le=720)
    station: str | None = Field(None, pattern=CODE)
    note: str = Field("", max_length=200)


@router.post("/national/shadow/actual", dependencies=CONTROL)
def national_shadow_actual(request: ShadowDecision) -> dict[str, Any]:
    """Shadow trial: log what the controller actually decided (nothing in the twin changes)."""

    from india_rail.railguard.shadow import ActualDecision

    trial = _shadow()
    decision = ActualDecision(
        request.run,
        request.action,
        trial.twin.now if request.at_min is None else request.at_min,
        request.controller,
        request.hold_min,
        request.station,
        request.note,
    )
    return _run(trial.record, decision)


@router.get("/national/shadow/report", dependencies=VIEW)
def national_shadow_report() -> dict[str, Any]:
    return _shadow().report()


@lru_cache(maxsize=1)
def _gateway():
    from india_rail.railguard.livefeed import FeedGateway

    return FeedGateway(national())


@router.post("/national/feed/batch", dependencies=FEED)
def national_feed_batch(envelope: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    """Signed batch from an authorised feed (see india_rail.railguard.livefeed for the envelope)."""

    from india_rail.railguard.livefeed import FeedRejected

    try:
        gateway = _gateway()
    except ValueError as exc:  # malformed RAILGUARD_FEED_KEYS
        raise HTTPException(status_code=503, detail="Live feed keys misconfigured") from exc
    try:
        return gateway.receive(envelope)
    except FeedRejected as exc:
        raise HTTPException(status_code=401, detail=f"Feed batch refused: {exc}") from exc


@router.post("/national/feed/position", dependencies=FEED)
def national_feed(request: NationalFeed) -> dict[str, Any]:
    return _run(national().ingest_position, request.run, request.section_id, request.offset_km)
