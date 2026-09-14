"""Read-only APIs for configured, real timetable providers.

These endpoints fetch and validate provider data on demand. They deliberately
do not return a guessed/default timetable when a feed is absent or fails. The
normalized preview includes the exact source checksum and timestamps so a
caller can decide whether the result is suitable for a later conflict
calculation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.core.security import CurrentUser, get_current_user
from app.schemas.timetable import TimetableSourceCatalogItem, TimetableSourceCatalogResponse
from app.services.timetable_ingestion import (
    TimetableIngestionError,
    fetch_gtfs_realtime,
    fetch_gtfs_static,
    fetch_india_open_data,
    feed_summary,
    public_source_reference,
)

router = APIRouter()


def _provider_error(exc: TimetableIngestionError) -> HTTPException:
    code_to_status = {
        "NOT_CONFIGURED": status.HTTP_503_SERVICE_UNAVAILABLE,
        "DISABLED": status.HTTP_503_SERVICE_UNAVAILABLE,
        "UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
        "AUTH_REQUIRED": status.HTTP_502_BAD_GATEWAY,
    }
    return HTTPException(
        status_code=code_to_status.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY),
        detail={"code": exc.code, "message": str(exc)},
    )


def _preview(feed: Any, *, limit: int) -> dict[str, Any]:
    result = feed_summary(feed)
    if hasattr(feed, "stops"):
        result["preview"] = {
            "stops": [item.model_dump(mode="json") for item in feed.stops[:limit]],
            "routes": [item.model_dump(mode="json") for item in feed.routes[:limit]],
            "trips": [item.model_dump(mode="json") for item in feed.trips[:limit]],
            "stop_times": [item.model_dump(mode="json") for item in feed.stop_times[:limit]],
        }
    elif hasattr(feed, "trip_updates"):
        result["preview"] = {
            "trip_updates": [item.model_dump(mode="json") for item in feed.trip_updates[:limit]],
            "vehicle_positions": [
                item.model_dump(mode="json") for item in feed.vehicle_positions[:limit]
            ],
            "alerts": [item.model_dump(mode="json") for item in feed.alerts[:limit]],
        }
    else:
        result["preview"] = {"rows": [item.model_dump(mode="json") for item in feed.rows[:limit]]}
    result["preview_limit"] = limit
    result["authority_notice"] = (
        "Timetable evidence is decision-support input only. Public feeds do not provide "
        "movement authority, signal state, block occupancy, or collision protection."
    )
    return result


@router.get("/sources", response_model=TimetableSourceCatalogResponse)
async def timetable_sources(_user: CurrentUser = Depends(get_current_user)) -> TimetableSourceCatalogResponse:
    """Describe which legitimate timetable feeds are configured."""

    return TimetableSourceCatalogResponse(
        # This catalog reports configuration only; it is not a live-data claim.
        real_data_only=settings.REAL_DATA_ONLY,
        items=[
            TimetableSourceCatalogItem(
                provider_key="gtfs_static",
                provider_name=settings.GTFS_STATIC_SOURCE_NAME,
                feed_type="GTFS_STATIC",
                configured=bool(settings.GTFS_STATIC_FEED_URL.strip()),
                source_url=(
                    public_source_reference(settings.GTFS_STATIC_FEED_URL)
                    if settings.GTFS_STATIC_FEED_URL.strip()
                    else None
                ),
                source_license=settings.GTFS_SOURCE_LICENSE.strip() or None,
                authority_note="Public/static timetable input; not movement authority.",
            ),
            TimetableSourceCatalogItem(
                provider_key="gtfs_realtime",
                provider_name=settings.GTFS_REALTIME_SOURCE_NAME,
                feed_type="GTFS_REALTIME",
                configured=bool(settings.GTFS_REALTIME_FEED_URL.strip()),
                source_url=(
                    public_source_reference(settings.GTFS_REALTIME_FEED_URL)
                    if settings.GTFS_REALTIME_FEED_URL.strip()
                    else None
                ),
                source_license=settings.GTFS_SOURCE_LICENSE.strip() or None,
                authority_note="Realtime service update input; not signal or block authority.",
            ),
            TimetableSourceCatalogItem(
                provider_key="india_open_data",
                provider_name=settings.INDIA_RAILWAYS_SOURCE_NAME,
                feed_type="INDIA_RAILWAYS_OPEN_DATA",
                configured=bool(settings.INDIA_RAILWAYS_TIMETABLE_API_URL.strip()),
                source_url=(
                    public_source_reference(settings.INDIA_RAILWAYS_TIMETABLE_API_URL)
                    if settings.INDIA_RAILWAYS_TIMETABLE_API_URL.strip()
                    else None
                ),
                source_license=settings.INDIA_RAILWAYS_SOURCE_LICENSE.strip() or None,
                authority_note="Government open-data timetable; release date and freshness must be checked.",
            ),
        ],
    )


@router.get("/gtfs-static")
async def current_gtfs_static(
    limit: int = Query(10, ge=0, le=100),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch and validate the configured GTFS static feed."""

    try:
        return _preview(await fetch_gtfs_static(), limit=limit)
    except TimetableIngestionError as exc:
        raise _provider_error(exc) from exc


@router.get("/gtfs-realtime")
async def current_gtfs_realtime(
    limit: int = Query(10, ge=0, le=100),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch and validate the configured GTFS-Realtime feed."""

    try:
        return _preview(await fetch_gtfs_realtime(), limit=limit)
    except TimetableIngestionError as exc:
        raise _provider_error(exc) from exc


@router.get("/india-open-data")
async def current_india_open_data(
    limit: int = Query(10, ge=0, le=100),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch and validate the configured India Open Data timetable feed."""

    try:
        return _preview(await fetch_india_open_data(), limit=limit)
    except TimetableIngestionError as exc:
        raise _provider_error(exc) from exc
