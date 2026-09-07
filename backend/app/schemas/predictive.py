from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DelayPredictionRequest(BaseModel):
    route_id: UUID


class DelayPredictionResponse(BaseModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    source: Literal["STORED_ROUTE_FEATURES"] = "STORED_ROUTE_FEATURES"
    route_id: UUID
    predicted_delay_minutes: int | None
    confidence_pct: float | None
    risk_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"] | None
    primary_bottleneck_segment: str | None = None
    weather_impact_pct: float | None
    congestion_impact_pct: float | None
    optimal_dispatch_window: str | None
    limitation: str


class DustStormRiskResponse(BaseModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    source: str
    location: str
    lat: float
    lon: float
    observed_at: datetime | None
    fetched_at: datetime
    dust_risk_index: float | None
    airborne_particulate_pm10: float | None
    visibility_km: float | None
    warning_level: Literal["SAFE", "ADVISORY", "SEVERE", "HAZARD"] | None
    recommended_speed_limit_kmh: int | None
    operational_limitation: str
