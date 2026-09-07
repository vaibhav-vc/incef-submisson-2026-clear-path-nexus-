from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.predictive import DustStormRiskResponse

logger = logging.getLogger(__name__)


def _warning_level(pm10: float) -> str:
    if pm10 >= 250:
        return "HAZARD"
    if pm10 >= 150:
        return "SEVERE"
    if pm10 >= 100:
        return "ADVISORY"
    return "SAFE"


def _risk_index(pm10: float, dust: float | None) -> float:
    """Normalize provider measurements; never infer a measurement from location."""

    particulate = max(pm10, dust or 0.0)
    return round(min(100.0, particulate / 3.0), 1)


def _unavailable(lat: float, lon: float, location_name: str, detail: str) -> DustStormRiskResponse:
    return DustStormRiskResponse(
        status="UNAVAILABLE",
        source=settings.DUST_AIR_QUALITY_PROVIDER_NAME,
        location=location_name,
        lat=lat,
        lon=lon,
        observed_at=None,
        fetched_at=datetime.now(timezone.utc),
        dust_risk_index=None,
        airborne_particulate_pm10=None,
        visibility_km=None,
        warning_level=None,
        recommended_speed_limit_kmh=None,
        operational_limitation=detail,
    )


async def analyze_dust_storm_hazard(
    lat: float, lon: float, location_name: str
) -> DustStormRiskResponse:
    """Fetch provider-measured particulates and disclose operational limits.

    The air-quality provider supplies atmospheric composition, not railway
    movement authority. Therefore this endpoint never recommends a speed.
    """

    if not settings.DUST_AIR_QUALITY_FEED_URL:
        return _unavailable(
            lat,
            lon,
            location_name,
            "Dust provider is not configured; official railway restrictions remain authoritative.",
        )

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "pm10,dust",
        "timezone": "UTC",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.PROVIDER_TIMEOUT_SECONDS) as client:
            response = await client.get(settings.DUST_AIR_QUALITY_FEED_URL, params=params)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        current = payload.get("current")
        if not isinstance(current, dict) or not isinstance(current.get("pm10"), (int, float)):
            raise ValueError("provider response missing current.pm10")
        pm10 = float(current["pm10"])
        dust = float(current["dust"]) if isinstance(current.get("dust"), (int, float)) else None
        return DustStormRiskResponse(
            status="AVAILABLE",
            source=settings.DUST_AIR_QUALITY_PROVIDER_NAME,
            location=location_name,
            lat=lat,
            lon=lon,
            observed_at=current.get("time"),
            fetched_at=datetime.now(timezone.utc),
            dust_risk_index=_risk_index(pm10, dust),
            airborne_particulate_pm10=round(pm10, 1),
            visibility_km=None,
            warning_level=_warning_level(pm10),
            recommended_speed_limit_kmh=None,
            operational_limitation=(
                "Air-quality evidence is advisory only. No official railway speed restriction "
                "provider is integrated; consult movement authority and control orders."
            ),
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Dust provider unavailable for %s/%s: %s", lat, lon, exc)
        return _unavailable(
            lat,
            lon,
            location_name,
            "Dust provider unavailable; no hazard or speed value was inferred from coordinates.",
        )
