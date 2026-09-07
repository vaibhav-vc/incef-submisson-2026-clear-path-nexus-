from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user
from app.models.provenance import ProvenanceRecord, RouteDecisionSnapshot
from app.models.route import GeneratedRoute, LineSegment, Station, TrainSchedule
from app.schemas.route import (
    AlternateRoute,
    JourneyDispatchRequest,
    JourneyDispatchResponse,
    RouteApprovalResponse,
    RouteDispatchResponse,
    RouteEvaluateRequest,
    RouteEvaluateResponse,
    RouteHistoryResponse,
    RouteSuggestRequest,
    RouteSuggestResponse,
    ScoreBreakdown,
    SegmentPathResponse,
    StationResponse,
    ThreatSimulationRequest,
    ThreatSimulationResponse,
    TrackSegmentDetail,
    TrainPosition,
)
from app.services.congestion import resolve_congestion
from app.services.evidence_gate import DecisionState, load_stored_evidence_assessment
from app.services.port_sync import compute_port_sync, fetch_port_schedule
from app.services.provenance import capture_route_decision
from app.services.reliability import (
    apply_threat_simulation,
    calculate_route_reliability,
    effective_weights,
)
from app.services.router_engine import (
    build_track_detail,
    compute_congestion_score,
    compute_historical_score,
    estimate_transit_hours,
    find_all_route_segments,
    find_route_segments,
    predict_transit_delay_minutes,
    resolve_train_position,
    segment_length_km,
    validate_cargo_clearance,
)
from app.schemas.schedule import TrainScheduleCreate, TrainScheduleResponse, TrainScheduleUpdate
from app.services.scheduling import assess_schedule
from app.services.space_weather import space_weather_service

router = APIRouter()


async def _require_ready_route_evidence(
    db: AsyncSession, route_id: UUID, user_id: str
) -> RouteDecisionSnapshot:
    assessment = await load_stored_evidence_assessment(db, route_id, user_id)
    if assessment.decision_state is not DecisionState.READY:
        reasons = ", ".join(assessment.reason_codes) or "EVIDENCE_GATE_FAILED"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Route decision is {assessment.decision_state.value}; dispatch requires READY "
                f"stored evidence ({reasons})"
            ),
        )
    snapshot = await db.scalar(
        select(RouteDecisionSnapshot).where(
            RouteDecisionSnapshot.route_id == route_id,
            RouteDecisionSnapshot.user_id == user_id,
        )
    )
    if snapshot is None or not snapshot.evidence_root_checksum:
        raise HTTPException(status_code=409, detail="Signed evidence root is unavailable")
    return snapshot


def _require_current_approval(
    route: GeneratedRoute,
    snapshot: RouteDecisionSnapshot,
) -> None:
    if (
        route.approved_at is None
        or not route.approved_by_user_id
        or not route.approved_by_role
        or route.approval_evidence_checksum != snapshot.evidence_root_checksum
    ):
        raise HTTPException(
            status_code=409,
            detail="Current signed evidence requires an authorized human approval receipt",
        )


def _as_aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamps_match(left: datetime, right: datetime, *, tolerance_minutes: int = 5) -> bool:
    normalized_left = _as_aware_datetime(left)
    normalized_right = _as_aware_datetime(right)
    return bool(
        normalized_left
        and normalized_right
        and abs(normalized_left - normalized_right) <= timedelta(minutes=tolerance_minutes)
    )


async def _require_schedule_matches_evidence(
    db: AsyncSession,
    schedule: TrainSchedule,
    snapshot: RouteDecisionSnapshot,
) -> None:
    """Bind dispatch timing to the port-alignment inputs sealed by EvidenceGate."""

    record = await db.scalar(
        select(ProvenanceRecord).where(
            ProvenanceRecord.decision_snapshot_id == snapshot.id,
            ProvenanceRecord.decision_input_role == "PORT_ALIGNMENT",
            ProvenanceRecord.used_in_decision.is_(True),
        )
    )
    if record is None:
        raise HTTPException(
            status_code=409,
            detail="Signed port-alignment evidence is unavailable for this schedule",
        )

    summary = record.value_summary if isinstance(record.value_summary, dict) else {}
    evaluated_at = _as_aware_datetime(summary.get("evaluated_at"))
    arrival_hours = summary.get("train_arrival_hours")
    try:
        expected_arrival = (
            evaluated_at + timedelta(hours=float(arrival_hours))
            if evaluated_at is not None and arrival_hours is not None
            else None
        )
    except (TypeError, ValueError, OverflowError):
        expected_arrival = None
    if expected_arrival is None or not _timestamps_match(
        schedule.scheduled_arrival, expected_arrival
    ):
        raise HTTPException(
            status_code=409,
            detail="Schedule arrival does not match the timing sealed by EvidenceGate",
        )

    window = summary.get("loading_window")
    if window is None:
        if schedule.berth_window_start is not None or schedule.berth_window_end is not None:
            raise HTTPException(
                status_code=409,
                detail="Schedule berth window is not present in the signed evidence",
            )
        return
    if not isinstance(window, dict):
        raise HTTPException(status_code=409, detail="Signed berth-window evidence is malformed")

    expected_start = _as_aware_datetime(window.get("start"))
    expected_end = _as_aware_datetime(window.get("end"))
    if (
        expected_start is None
        or expected_end is None
        or schedule.berth_window_start is None
        or schedule.berth_window_end is None
        or not _timestamps_match(schedule.berth_window_start, expected_start)
        or not _timestamps_match(schedule.berth_window_end, expected_end)
    ):
        raise HTTPException(
            status_code=409,
            detail="Schedule berth window does not match the window sealed by EvidenceGate",
        )


def _route_weather_samples(segments: list[LineSegment]) -> list[tuple[float, float]]:
    """Sample origin, spaced corridor points, and destination with a five-call ceiling."""
    if not segments:
        return []
    total_km = sum(
        segment_length_km([[lat, lon] for lon, lat in to_shape(segment.geom_path).coords])
        for segment in segments
    )
    sample_count = 3 if total_km < 500 else 5
    points: list[tuple[float, float]] = []
    for index in range(sample_count):
        fraction = index / (sample_count - 1)
        segment_index = min(len(segments) - 1, int(fraction * len(segments)))
        local_fraction = (fraction * len(segments)) - segment_index
        if segment_index == len(segments) - 1 and fraction == 1:
            local_fraction = 1.0
        point = to_shape(segments[segment_index].geom_path).interpolate(
            local_fraction, normalized=True
        )
        rounded = (round(point.y, 4), round(point.x, 4))
        if rounded not in points:
            points.append(rounded)
    return points


async def _fetch_sampled_weather_readings(
    segments: list[LineSegment],
) -> tuple[list[tuple[float, float]], list[dict]]:
    coordinates = _route_weather_samples(segments)
    readings = await asyncio.gather(
        *(
            space_weather_service.fetch_route_environmental_risks(lat, lon)
            for lat, lon in coordinates
        )
    )
    return coordinates, readings


def _score_sampled_weather(
    coordinates: list[tuple[float, float]], readings: list[dict], kp_data: dict
) -> tuple[dict, float | None, list[str]]:
    scored = [space_weather_service.weather_to_score(reading, kp_data) for reading in readings]
    if not scored:
        return {"status": "unavailable", "source": "provider-unavailable"}, None, [
            "Weather sampling unavailable — verify corridor conditions before dispatch"
        ]
    if any(score is None for score, _alerts in scored):
        alerts = list(dict.fromkeys(alert for _, sample_alerts in scored for alert in sample_alerts))
        weather_data = dict(readings[0])
        weather_data["_decision_input_status"] = "unavailable"
        weather_data["_route_samples"] = [
            {
                "latitude": lat,
                "longitude": lon,
                "score": None if scored[index][0] is None else round(float(scored[index][0]), 1),
                "source_state": reading.get("_provenance", {}).get(
                    "raw_source_state", "UNAVAILABLE"
                ),
                "observed_at": reading.get("_provenance", {}).get("observed_at"),
            }
            for index, ((lat, lon), reading) in enumerate(zip(coordinates, readings, strict=False))
        ]
        return weather_data, None, alerts
    worst_index = min(range(len(scored)), key=lambda index: float(scored[index][0]))
    weather_data = dict(readings[worst_index])
    weather_data["_route_samples"] = [
        {
            "latitude": lat,
            "longitude": lon,
            "score": round(float(scored[index][0]), 1),
            "source_state": reading.get("_provenance", {}).get("raw_source_state", "UNAVAILABLE"),
            "observed_at": reading.get("_provenance", {}).get("observed_at"),
        }
        for index, ((lat, lon), reading) in enumerate(zip(coordinates, readings))
    ]
    alerts = list(dict.fromkeys(alert for _, sample_alerts in scored for alert in sample_alerts))
    # Conservative deterministic aggregation: the weakest sampled point governs the route factor.
    return weather_data, float(scored[worst_index][0]), alerts


@router.get("/stations", response_model=list[StationResponse])
async def list_stations(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[StationResponse]:
    result = await db.execute(select(Station))
    stations = result.scalars().all()
    out: list[StationResponse] = []
    for s in stations:
        point = to_shape(s.coordinates)
        out.append(StationResponse(id=s.id, name=s.name, code=s.code, lat=point.y, lon=point.x))
    return out


@router.post("/evaluate", response_model=RouteEvaluateResponse)
async def evaluate_route(
    payload: RouteEvaluateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> RouteEvaluateResponse:
    src_result = await db.execute(
        select(Station).where(Station.code == payload.source_code.upper())
    )
    dst_result = await db.execute(select(Station).where(Station.code == payload.dest_code.upper()))
    source = src_result.scalar_one_or_none()
    dest = dst_result.scalar_one_or_none()

    if not source or not dest:
        raise HTTPException(status_code=404, detail="Source or destination station not found")

    seg_result = await db.execute(
        select(LineSegment).options(
            selectinload(LineSegment.source_station),
            selectinload(LineSegment.dest_station),
        )
    )
    all_segments = list(seg_result.scalars().all())
    route_segments = find_route_segments(all_segments, source.id, dest.id)

    if not route_segments:
        raise HTTPException(status_code=404, detail="No route found between stations")

    clearance = validate_cargo_clearance(
        payload.cargo.height,
        payload.cargo.width,
        payload.cargo.weight,
        route_segments,
    )
    clearance_failed = clearance["status"] == "HARD_BLOCKED"

    kp_data, port_schedule, congestion, sampled_weather = await asyncio.gather(
        space_weather_service.fetch_kp_index(),
        fetch_port_schedule(payload.port_id, payload.vessel_id, payload.operator_loading_window()),
        resolve_congestion(route_segments, dest_code=payload.dest_code),
        _fetch_sampled_weather_readings(route_segments),
    )
    weather_data, weather_score, env_alerts = _score_sampled_weather(
        *sampled_weather, kp_data
    )

    port_sync = compute_port_sync(payload.train_arrival_hours, port_schedule)
    port_score = port_sync.score
    if port_sync.warning:
        env_alerts.append(port_sync.warning)

    congestion_score = congestion.score
    env_alerts.extend(congestion.alerts)
    historical_score = compute_historical_score(route_segments)

    reliability = calculate_route_reliability(
        weather_score,
        port_score,
        congestion_score,
        historical_score,
        clearance_failed,
        port_available=port_sync.available,
        weather_available=weather_score is not None,
    )

    estimated = estimate_transit_hours(route_segments) if not clearance_failed else None
    if weather_score is not None:
        delay_info = predict_transit_delay_minutes(
            route_segments, 100 - congestion_score, 100 - weather_score
        )
        if delay_info["delay_minutes"] > 60:
            env_alerts.append(
                f"Predicted delay overhead: {delay_info['delay_minutes']} min ({delay_info['confidence']})"
            )

    segment_responses: list[SegmentPathResponse] = []
    for seg in route_segments:
        coords = [[c[1], c[0]] for c in to_shape(seg.geom_path).coords]
        status = (
            "HARD_BLOCKED"
            if clearance_failed and seg.id == clearance.get("blocking_segment_id")
            else clearance["status"]
        )
        segment_responses.append(SegmentPathResponse(id=seg.id, status=status, coordinates=coords))

    record = GeneratedRoute(
        user_id=user.id,
        dispatch_status="DRAFT",
        cargo_height_requested=payload.cargo.height,
        cargo_width_requested=payload.cargo.width,
        cargo_weight_requested=payload.cargo.weight,
        source_station_code=payload.source_code.upper(),
        dest_station_code=payload.dest_code.upper(),
        status=clearance["status"],
        reliability_score=reliability,
        estimated_hours=estimated,
        blocking_segment_id=clearance.get("blocking_segment_id"),
    )
    db.add(record)
    await db.flush()
    applied_weights = effective_weights(
        port_sync.available, weather_available=weather_score is not None
    )
    provenance_summary = await capture_route_decision(
        db,
        route=record,
        user_id=user.id,
        request_id=getattr(request.state, "request_id", None),
        cargo=payload.cargo.model_dump(),
        segments=route_segments,
        clearance=clearance,
        weather_data=weather_data,
        kp_data=kp_data,
        weather_score=weather_score,
        port_sync=port_sync,
        congestion=congestion,
        historical_score=historical_score,
        reliability=reliability,
        estimated_hours=estimated,
        applied_weights=applied_weights,
        alerts=env_alerts,
    )
    evidence_assessment = await load_stored_evidence_assessment(db, record.id, user.id)
    await db.commit()
    await db.refresh(record)

    return RouteEvaluateResponse(
        route_id=record.id,
        status=clearance["status"],
        decision_state=evidence_assessment.decision_state.value,
        reliability_score=reliability,
        blocking_segment_id=clearance.get("blocking_segment_id"),
        estimated_hours=estimated,
        score_breakdown=ScoreBreakdown(
            weather=round(weather_score, 1) if weather_score is not None else None,
            port=round(port_score, 1) if port_sync.available else None,
            congestion=round(congestion_score, 1),
            historical=round(historical_score, 1),
            port_data_source=port_sync.source,
            port_counted=port_sync.available,
            applied_weights=applied_weights,
            congestion_source=congestion.source,
            congestion_static=congestion.static_score,
            congestion_live_rail=congestion.live_rail_score,
            port_congestion_pct=congestion.port_congestion_pct,
        ),
        segments=segment_responses,
        environmental_alerts=env_alerts,
        provenance_summary=provenance_summary,
    )


@router.post("/simulate", response_model=ThreatSimulationResponse)
async def simulate_threat(
    payload: ThreatSimulationRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ThreatSimulationResponse:
    route = await db.scalar(
        select(GeneratedRoute).where(
            GeneratedRoute.id == payload.route_id,
            GeneratedRoute.user_id == user.id,
        )
    )
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    base = route.reliability_score
    simulated, alerts = apply_threat_simulation(
        base, payload.storm_severity, payload.solar_kp_index, payload.port_congestion
    )
    degradation = round((base - simulated) / base * 100, 1) if base else 0
    return ThreatSimulationResponse(
        original_score=base,
        simulated_score=simulated,
        degradation_pct=degradation,
        alerts=alerts,
    )


@router.post("/suggest", response_model=RouteSuggestResponse)
async def suggest_route_from_position(
    payload: RouteSuggestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> RouteSuggestResponse:
    stations_result = await db.execute(select(Station))
    stations = list(stations_result.scalars().all())

    dst_result = await db.execute(
        select(Station).where(Station.code == payload.destination_code.upper())
    )
    dest = dst_result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Destination station not found")

    seg_result = await db.execute(
        select(LineSegment).options(
            selectinload(LineSegment.source_station),
            selectinload(LineSegment.dest_station),
        )
    )
    all_segments = list(seg_result.scalars().all())

    resolved = resolve_train_position(
        payload.location.mode,
        stations,
        all_segments,
        station_code=payload.location.station_code,
        lat=payload.location.lat,
        lon=payload.location.lon,
    )
    if not resolved:
        raise HTTPException(status_code=400, detail="Could not resolve train location on network")

    if resolved.routing_start_id == dest.id:
        raise HTTPException(status_code=400, detail="Train has already reached destination")

    route_segments = find_route_segments(all_segments, resolved.routing_start_id, dest.id)
    if not route_segments and not resolved.partial_coords:
        raise HTTPException(status_code=404, detail="No remaining route to destination")

    full_route: list[tuple[LineSegment, list[list[float]], str]] = []
    if resolved.partial_coords:
        seg = next(s for s in all_segments if s.id == resolved.current_segment_id)
        full_route.append((seg, resolved.partial_coords, "CURRENT"))

    for seg in route_segments:
        if full_route and full_route[0][0].id == seg.id:
            continue
        coords = [[c[1], c[0]] for c in to_shape(seg.geom_path).coords]
        full_route.append((seg, coords, "UPCOMING"))

    if full_route and not resolved.partial_coords:
        seg, coords, _ = full_route[0]
        full_route[0] = (seg, coords, "CURRENT")

    remaining_segments = [item[0] for item in full_route]
    clearance = validate_cargo_clearance(
        payload.cargo.height,
        payload.cargo.width,
        payload.cargo.weight,
        remaining_segments,
    )
    clearance_failed = clearance["status"] == "HARD_BLOCKED"

    kp_data, port_schedule, congestion, sampled_weather = await asyncio.gather(
        space_weather_service.fetch_kp_index(),
        fetch_port_schedule(payload.port_id, payload.vessel_id, payload.operator_loading_window()),
        resolve_congestion(remaining_segments, dest_code=payload.destination_code),
        _fetch_sampled_weather_readings(remaining_segments),
    )
    weather_data, weather_score, env_alerts = _score_sampled_weather(
        *sampled_weather, kp_data
    )

    port_sync = compute_port_sync(payload.train_arrival_hours, port_schedule)
    port_score = port_sync.score
    if port_sync.warning:
        env_alerts.append(port_sync.warning)
    if resolved.offset_km > 5:
        env_alerts.append(
            f"Position snapped {resolved.offset_km} km from nearest track — verify GPS lock"
        )

    congestion_score = congestion.score
    env_alerts.extend(congestion.alerts)
    historical_score = compute_historical_score(remaining_segments)
    reliability = calculate_route_reliability(
        weather_score,
        port_score,
        congestion_score,
        historical_score,
        clearance_failed,
        port_available=port_sync.available,
        weather_available=weather_score is not None,
    )

    remaining_km = sum(segment_length_km(coords) for _, coords, _ in full_route)
    estimated = (
        round(
            remaining_km / 45
            + sum(float(s.historical_delay_hours) for s in remaining_segments),
            2,
        )
        if not clearance_failed
        else None
    )

    track_details: list[TrackSegmentDetail] = []
    segment_responses: list[SegmentPathResponse] = []
    for seg, coords, phase in full_route:
        detail = build_track_detail(
            seg,
            coords,
            phase,
            payload.cargo.height,
            payload.cargo.width,
            payload.cargo.weight,
            clearance.get("blocking_segment_id"),
            resolved.snap_fraction,
            resolved.current_segment_id,
        )
        track_details.append(TrackSegmentDetail(**detail))
        status = (
            "HARD_BLOCKED"
            if clearance_failed and seg.id == clearance.get("blocking_segment_id")
            else clearance["status"]
        )
        segment_responses.append(
            SegmentPathResponse(
                id=seg.id,
                status=status,
                coordinates=coords,
                phase=phase,
                label=detail["label"],
            )
        )

    alternates: list[AlternateRoute] = []
    alternate_candidates: list[tuple[list[LineSegment], float, float, float, float]] = []
    for path in find_all_route_segments(all_segments, resolved.routing_start_id, dest.id):
        alt_clearance = validate_cargo_clearance(
            payload.cargo.height,
            payload.cargo.width,
            payload.cargo.weight,
            path,
        )
        if alt_clearance["status"] == "HARD_BLOCKED":
            continue
        alt_congestion = compute_congestion_score(path)
        alt_historical = compute_historical_score(path)

        alt_mid_seg = path[len(path) // 2]
        alt_mid_point = to_shape(alt_mid_seg.geom_path).interpolate(0.5, normalized=True)
        alternate_candidates.append(
            (path, alt_congestion, alt_historical, alt_mid_point.y, alt_mid_point.x)
        )

    alternate_weather = await asyncio.gather(
        *(
            space_weather_service.fetch_route_environmental_risks(lat, lon)
            for _, _, _, lat, lon in alternate_candidates
        )
    )
    for (path, alt_congestion, alt_historical, _, _), alt_weather_data in zip(
        alternate_candidates, alternate_weather, strict=True
    ):
        alt_weather_score, _ = space_weather_service.weather_to_score(alt_weather_data, kp_data)

        alt_reliability = calculate_route_reliability(
            alt_weather_score,
            port_score,
            alt_congestion,
            alt_historical,
            False,
            port_available=port_sync.available,
            weather_available=alt_weather_score is not None,
        )
        label = " → ".join([path[0].source_station.code] + [s.dest_station.code for s in path])
        alternates.append(
            AlternateRoute(
                label=label,
                reliability_score=alt_reliability,
                segment_ids=[s.id for s in path],
                estimated_hours=estimate_transit_hours(path),
                weather_score=alt_weather_score,
            )
        )
    alternates.sort(key=lambda a: a.reliability_score, reverse=True)

    next_station = full_route[0][0].dest_station.code if full_route else None

    record = GeneratedRoute(
        user_id=user.id,
        dispatch_status="DRAFT",
        cargo_height_requested=payload.cargo.height,
        cargo_width_requested=payload.cargo.width,
        cargo_weight_requested=payload.cargo.weight,
        source_station_code=resolved.routing_start_code,
        dest_station_code=payload.destination_code.upper(),
        status=clearance["status"],
        reliability_score=reliability,
        estimated_hours=estimated,
        blocking_segment_id=clearance.get("blocking_segment_id"),
    )
    db.add(record)
    await db.flush()
    applied_weights = effective_weights(
        port_sync.available, weather_available=weather_score is not None
    )
    provenance_summary = await capture_route_decision(
        db,
        route=record,
        user_id=user.id,
        request_id=getattr(request.state, "request_id", None),
        cargo=payload.cargo.model_dump(),
        segments=remaining_segments,
        clearance=clearance,
        weather_data=weather_data,
        kp_data=kp_data,
        weather_score=weather_score,
        port_sync=port_sync,
        congestion=congestion,
        historical_score=historical_score,
        reliability=reliability,
        estimated_hours=estimated,
        applied_weights=applied_weights,
        alerts=env_alerts,
    )
    evidence_assessment = await load_stored_evidence_assessment(db, record.id, user.id)
    await db.commit()
    await db.refresh(record)

    return RouteSuggestResponse(
        route_id=record.id,
        status=clearance["status"],
        decision_state=evidence_assessment.decision_state.value,
        reliability_score=reliability,
        blocking_segment_id=clearance.get("blocking_segment_id"),
        estimated_hours=estimated,
        score_breakdown=ScoreBreakdown(
            weather=round(weather_score, 1) if weather_score is not None else None,
            port=round(port_score, 1) if port_sync.available else None,
            congestion=round(congestion_score, 1),
            historical=round(historical_score, 1),
            port_data_source=port_sync.source,
            port_counted=port_sync.available,
            applied_weights=applied_weights,
            congestion_source=congestion.source,
            congestion_static=congestion.static_score,
            congestion_live_rail=congestion.live_rail_score,
            port_congestion_pct=congestion.port_congestion_pct,
        ),
        segments=segment_responses,
        environmental_alerts=env_alerts,
        train_position=TrainPosition(
            lat=resolved.lat,
            lon=resolved.lon,
            mode=payload.location.mode,
            snapped_track=resolved.snapped_track,
            offset_km=resolved.offset_km,
            station_code=resolved.station_code,
        ),
        remaining_km=round(remaining_km, 1),
        eta_hours=estimated,
        track_details=track_details,
        alternate_routes=alternates[:2],
        next_station=next_station,
        provenance_summary=provenance_summary,
    )


@router.get("/routes", response_model=list[RouteHistoryResponse])
async def list_route_history(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[RouteHistoryResponse]:
    result = await db.execute(
        select(GeneratedRoute)
        .where(GeneratedRoute.user_id == user.id)
        .order_by(GeneratedRoute.created_at.desc())
        .limit(100)
    )
    return [RouteHistoryResponse.model_validate(route) for route in result.scalars().all()]


@router.post("/routes/{route_id}/approve", response_model=RouteApprovalResponse)
async def approve_route(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> RouteApprovalResponse:
    """Bind an authenticated human approval to the current signed evidence root."""

    allowed_roles = {role.casefold() for role in settings.APPROVAL_ALLOWED_ROLES}
    if user.role.casefold() not in allowed_roles:
        raise HTTPException(status_code=403, detail="User role is not authorized to approve routes")
    route = await db.scalar(
        select(GeneratedRoute)
        .where(GeneratedRoute.id == route_id, GeneratedRoute.user_id == user.id)
        .with_for_update()
    )
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    if route.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Route failed physical clearance")
    approval_fields = (
        route.approved_by_user_id,
        route.approved_by_role,
        route.approved_at,
        route.approval_evidence_checksum,
    )
    if any(value is not None for value in approval_fields):
        if not all(value is not None for value in approval_fields):
            raise HTTPException(status_code=409, detail="Stored approval receipt is incomplete")
        if route.dispatch_status == "DISPATCHED":
            return RouteApprovalResponse(
                route_id=route.id,
                approved_by_user_id=route.approved_by_user_id,
                approved_by_role=route.approved_by_role,
                approved_at=route.approved_at,
                evidence_root_checksum=route.approval_evidence_checksum,
            )
    snapshot = await _require_ready_route_evidence(db, route.id, user.id)
    if all(value is not None for value in approval_fields):
        if route.approval_evidence_checksum != snapshot.evidence_root_checksum:
            raise HTTPException(
                status_code=409,
                detail="Stored approval is bound to a different evidence root",
            )
        return RouteApprovalResponse(
            route_id=route.id,
            approved_by_user_id=route.approved_by_user_id,
            approved_by_role=route.approved_by_role,
            approved_at=route.approved_at,
            evidence_root_checksum=route.approval_evidence_checksum,
        )
    approved_at = datetime.now(timezone.utc)
    route.approved_by_user_id = user.id
    route.approved_by_role = user.role
    route.approved_at = approved_at
    route.approval_evidence_checksum = snapshot.evidence_root_checksum
    await db.commit()
    return RouteApprovalResponse(
        route_id=route.id,
        approved_by_user_id=user.id,
        approved_by_role=user.role,
        approved_at=approved_at,
        evidence_root_checksum=snapshot.evidence_root_checksum,
    )


@router.post("/routes/{route_id}/dispatch", response_model=RouteDispatchResponse)
async def dispatch_route(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> RouteDispatchResponse:
    result = await db.execute(
        select(GeneratedRoute)
        .where(
            GeneratedRoute.id == route_id,
            GeneratedRoute.user_id == user.id,
        )
        .with_for_update()
    )
    route = result.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    if route.dispatch_status == "DISPATCHED":
        if route.dispatched_at is None:
            raise HTTPException(status_code=409, detail="Stored dispatch receipt is incomplete")
        return RouteDispatchResponse(
            route_id=route.id,
            dispatch_status=route.dispatch_status,
            dispatched_at=route.dispatched_at,
        )
    if route.status != "APPROVED":
        raise HTTPException(
            status_code=409, detail="Only clearance-approved routes can be dispatched"
        )
    snapshot = await _require_ready_route_evidence(db, route.id, user.id)
    _require_current_approval(route, snapshot)
    route.dispatch_status = "DISPATCHED"
    route.dispatched_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(route)
    return RouteDispatchResponse(
        route_id=route.id,
        dispatch_status=route.dispatch_status,
        dispatched_at=route.dispatched_at,
    )


@router.post("/routes/dispatch-journey", response_model=JourneyDispatchResponse)
async def dispatch_journey(
    payload: JourneyDispatchRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> JourneyDispatchResponse:
    """Validate and dispatch every journey leg in one database transaction."""

    result = await db.execute(
        select(GeneratedRoute)
        .where(
            GeneratedRoute.id.in_(payload.route_ids),
            GeneratedRoute.user_id == user.id,
        )
        .with_for_update()
    )
    routes_by_id = {route.id: route for route in result.scalars().all()}
    if len(routes_by_id) != len(payload.route_ids):
        raise HTTPException(status_code=404, detail="Journey route not found")
    routes = [routes_by_id[route_id] for route_id in payload.route_ids]
    already_dispatched = [route for route in routes if route.dispatch_status == "DISPATCHED"]
    if already_dispatched:
        if len(already_dispatched) != len(routes) or any(
            route.dispatched_at is None for route in routes
        ):
            raise HTTPException(
                status_code=409,
                detail="Journey has mixed or incomplete dispatch state; audit timestamps were preserved",
            )
        timestamps = {route.dispatched_at for route in routes}
        if len(timestamps) != 1:
            raise HTTPException(
                status_code=409,
                detail="Journey dispatch receipts have inconsistent timestamps",
            )
        original_dispatched_at = next(iter(timestamps))
        return JourneyDispatchResponse(
            dispatched_at=original_dispatched_at,
            routes=[
                RouteDispatchResponse(
                    route_id=route.id,
                    dispatch_status="DISPATCHED",
                    dispatched_at=route.dispatched_at,
                )
                for route in routes
            ],
        )
    for route in routes:
        if route.status != "APPROVED":
            raise HTTPException(status_code=409, detail="Journey contains a blocked route")
        snapshot = await _require_ready_route_evidence(db, route.id, user.id)
        _require_current_approval(route, snapshot)

    dispatched_at = datetime.now(timezone.utc)
    responses: list[RouteDispatchResponse] = []
    for route in routes:
        route.dispatch_status = "DISPATCHED"
        route.dispatched_at = dispatched_at
        responses.append(
            RouteDispatchResponse(
                route_id=route.id,
                dispatch_status="DISPATCHED",
                dispatched_at=dispatched_at,
            )
        )
    await db.commit()
    return JourneyDispatchResponse(dispatched_at=dispatched_at, routes=responses)


async def _user_schedule_or_404(db: AsyncSession, schedule_id: UUID, user_id: str) -> TrainSchedule:
    result = await db.execute(
        select(TrainSchedule)
        .where(
            TrainSchedule.id == schedule_id,
            TrainSchedule.user_id == user_id,
        )
        .with_for_update()
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


async def _reassess_schedule(db: AsyncSession, schedule: TrainSchedule) -> None:
    result = await db.execute(
        select(TrainSchedule).where(TrainSchedule.user_id == schedule.user_id)
    )
    others = list(result.scalars().all())
    status, reason = assess_schedule(schedule, others)
    schedule.conflict_status = status
    schedule.conflict_reason = reason
    if schedule.schedule_status not in {"DISPATCHED", "CANCELLED"}:
        schedule.schedule_status = "READY" if status == "CLEAR" else "PLANNED"


@router.get("/schedules", response_model=list[TrainScheduleResponse])
async def list_schedules(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[TrainScheduleResponse]:
    result = await db.execute(
        select(TrainSchedule)
        .where(TrainSchedule.user_id == user.id)
        .order_by(TrainSchedule.scheduled_departure.asc())
    )
    return [TrainScheduleResponse.model_validate(item) for item in result.scalars().all()]


@router.get("/schedules/{schedule_id}", response_model=TrainScheduleResponse)
async def get_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TrainScheduleResponse:
    schedule = await _user_schedule_or_404(db, schedule_id, user.id)
    return TrainScheduleResponse.model_validate(schedule)


@router.post("/schedules", response_model=TrainScheduleResponse, status_code=201)
async def create_schedule(
    payload: TrainScheduleCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TrainScheduleResponse:
    if payload.generated_route_id:
        route_result = await db.execute(
            select(GeneratedRoute).where(
                GeneratedRoute.id == payload.generated_route_id,
                GeneratedRoute.user_id == user.id,
            )
        )
        linked_route = route_result.scalar_one_or_none()
        if linked_route is None:
            raise HTTPException(status_code=404, detail="Generated route not found")
        if (
            linked_route.source_station_code.upper() != payload.source_station_code.upper()
            or linked_route.dest_station_code.upper() != payload.dest_station_code.upper()
        ):
            raise HTTPException(
                status_code=409,
                detail="Schedule endpoints must match the linked EvidenceGate route",
            )

    schedule = TrainSchedule(
        user_id=user.id,
        generated_route_id=payload.generated_route_id,
        train_code=payload.train_code.upper(),
        train_name=payload.train_name,
        source_station_code=payload.source_station_code.upper(),
        dest_station_code=payload.dest_station_code.upper(),
        scheduled_departure=payload.scheduled_departure,
        scheduled_arrival=payload.scheduled_arrival,
        berth_window_start=payload.berth_window_start,
        berth_window_end=payload.berth_window_end,
        schedule_status="PLANNED",
        conflict_status="CLEAR",
        is_demo=False,
    )
    db.add(schedule)
    await db.flush()
    await _reassess_schedule(db, schedule)
    await db.commit()
    await db.refresh(schedule)
    return TrainScheduleResponse.model_validate(schedule)


@router.patch("/schedules/{schedule_id}", response_model=TrainScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    payload: TrainScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TrainScheduleResponse:
    schedule = await _user_schedule_or_404(db, schedule_id, user.id)
    if schedule.schedule_status == "DISPATCHED":
        raise HTTPException(status_code=409, detail="Dispatched schedules cannot be edited")

    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(schedule, key, value)

    if schedule.scheduled_arrival <= schedule.scheduled_departure:
        raise HTTPException(
            status_code=422, detail="scheduled_arrival must be after scheduled_departure"
        )
    if (schedule.berth_window_start is None) != (schedule.berth_window_end is None):
        raise HTTPException(
            status_code=422, detail="Both berth window fields are required together"
        )
    if schedule.berth_window_start and schedule.berth_window_end <= schedule.berth_window_start:
        raise HTTPException(
            status_code=422, detail="berth_window_end must be after berth_window_start"
        )

    await _reassess_schedule(db, schedule)
    await db.commit()
    await db.refresh(schedule)
    return TrainScheduleResponse.model_validate(schedule)


@router.post("/schedules/{schedule_id}/dispatch", response_model=TrainScheduleResponse)
async def dispatch_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> TrainScheduleResponse:
    schedule = await _user_schedule_or_404(db, schedule_id, user.id)
    if schedule.conflict_status == "BLOCKED":
        raise HTTPException(
            status_code=409, detail=schedule.conflict_reason or "Schedule is blocked"
        )
    if schedule.schedule_status == "CANCELLED":
        raise HTTPException(status_code=409, detail="Cancelled schedules cannot be dispatched")
    if schedule.schedule_status == "DISPATCHED":
        return TrainScheduleResponse.model_validate(schedule)

    if schedule.generated_route_id is None:
        raise HTTPException(
            status_code=409,
            detail="Operational dispatch requires an owned EvidenceGate route",
        )
    route_result = await db.execute(
        select(GeneratedRoute)
        .where(
            GeneratedRoute.id == schedule.generated_route_id,
            GeneratedRoute.user_id == user.id,
        )
        .with_for_update()
    )
    route = route_result.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="Linked route not found")
    if (
        route.source_station_code.upper() != schedule.source_station_code.upper()
        or route.dest_station_code.upper() != schedule.dest_station_code.upper()
    ):
        raise HTTPException(
            status_code=409,
            detail="Schedule endpoints do not match the linked EvidenceGate route",
        )
    if route.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Linked route is not clearance-approved")
    snapshot = await _require_ready_route_evidence(db, route.id, user.id)
    _require_current_approval(route, snapshot)
    await _require_schedule_matches_evidence(db, schedule, snapshot)
    dispatched_at = datetime.now(timezone.utc)
    if route.dispatch_status != "DISPATCHED":
        route.dispatch_status = "DISPATCHED"
        route.dispatched_at = dispatched_at
    elif route.dispatched_at is None:
        raise HTTPException(status_code=409, detail="Stored route dispatch receipt is incomplete")

    schedule.schedule_status = "DISPATCHED"
    schedule.dispatched_at = dispatched_at
    await db.commit()
    await db.refresh(schedule)
    return TrainScheduleResponse.model_validate(schedule)
