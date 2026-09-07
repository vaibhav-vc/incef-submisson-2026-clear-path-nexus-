"""Live corridor telemetry endpoints.

Both feeds are free-tier and best-effort. Every response states its source so
the UI can distinguish a live reading from a cached one from nothing at all.
Standalone corridor coverage is explicitly configured; route scoring derives
coverage from the route itself.
"""

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, get_current_user
from app.services.live_port import ais_collector
from app.services.live_rail import configured_corridor_stations, rail_client

router = APIRouter()


@router.get("/corridor-congestion")
async def corridor_congestion(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Live delay picture for the explicitly configured corridor."""
    result = await rail_client.fetch_corridor()
    return {
        "source": result.source.value,
        "available": result.available,
        "score": result.score,
        "fetched_at": result.fetched_at.isoformat() if result.fetched_at else None,
        "detail": result.detail,
        "budget_remaining": rail_client.budget.remaining,
        "stations": [
            {
                "code": s.station_code,
                "source": s.source.value,
                "trains": s.train_count,
                "mean_delay_minutes": s.mean_delay_minutes,
                "max_delay_minutes": s.max_delay_minutes,
                "at_station": s.at_station_count,
                "detail": s.detail,
            }
            for s in result.stations
        ],
    }


@router.get("/port-activity")
async def port_activity(user: CurrentUser = Depends(get_current_user)) -> dict:
    """JNPT vessel activity from AIS.

    NOTE: this is congestion, not schedule. AIS does not broadcast berth
    loading windows - see services/live_port.py.
    """
    snap = ais_collector.snapshot()
    return {
        "source": snap.source.value,
        "available": snap.available,
        "vessels_tracked": snap.vessels_tracked,
        "at_anchor": snap.at_anchor,
        "moored_at_berth": snap.moored_at_berth,
        "underway": snap.underway,
        "congestion_pct": snap.congestion_pct,
        "observed_at": snap.observed_at.isoformat() if snap.observed_at else None,
        "detail": snap.detail,
        "note": "Congestion only. Berth loading windows require operator input.",
    }


@router.get("/corridor-stations")
async def corridor_stations(user: CurrentUser = Depends(get_current_user)) -> dict:
    stations = configured_corridor_stations()
    return {
        "stations": list(stations),
        "available": bool(stations),
        "detail": None
        if stations
        else "RAILRADAR_CORRIDOR_STATIONS is not configured",
    }
