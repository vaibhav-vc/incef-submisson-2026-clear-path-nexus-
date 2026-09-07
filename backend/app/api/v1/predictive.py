from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.models.provenance import RouteDecisionSnapshot
from app.models.route import GeneratedRoute, LineSegment
from app.schemas.predictive import (
    DelayPredictionRequest,
    DelayPredictionResponse,
    DustStormRiskResponse,
)
from app.services.dust_storm_service import analyze_dust_storm_hazard
from app.services.predictive_delay import calculate_predictive_delay, unavailable_delay

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/delay", response_model=DelayPredictionResponse)
async def predict_route_delay(
    payload: DelayPredictionRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> DelayPredictionResponse:
    route = await db.scalar(
        select(GeneratedRoute).where(
            GeneratedRoute.id == payload.route_id,
            GeneratedRoute.user_id == user.id,
        )
    )
    if route is None:
        return unavailable_delay(payload.route_id, "Owned stored route evidence is unavailable")
    snapshot = await db.scalar(
        select(RouteDecisionSnapshot).where(
            RouteDecisionSnapshot.route_id == payload.route_id,
            RouteDecisionSnapshot.user_id == user.id,
        )
    )
    if snapshot is None:
        return unavailable_delay(payload.route_id, "Stored route decision snapshot is unavailable")

    segment_ids = snapshot.route_segment_ids or []
    if not segment_ids:
        return unavailable_delay(payload.route_id, "Stored route segment references are unavailable")
    result = await db.scalars(
        select(LineSegment)
        .where(LineSegment.id.in_(segment_ids))
        .options(selectinload(LineSegment.source_station), selectinload(LineSegment.dest_station))
    )
    by_id = {str(segment.id): segment for segment in result.all()}
    segments = [by_id[str(segment_id)] for segment_id in segment_ids if str(segment_id) in by_id]
    if len(segments) != len(segment_ids):
        return unavailable_delay(payload.route_id, "Stored route segment features are incomplete")
    return calculate_predictive_delay(
        route_id=payload.route_id,
        segments=segments,
        score_breakdown=snapshot.score_breakdown,
    )


@router.get("/dust-risk", response_model=DustStormRiskResponse)
async def get_dust_storm_risk(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude"),
    location: str = Query(..., min_length=1, max_length=100, description="Node name"),
) -> DustStormRiskResponse:
    return await analyze_dust_storm_hazard(lat, lon, location)
