from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from app.schemas.predictive import DelayPredictionResponse


def unavailable_delay(route_id: UUID, reason: str) -> DelayPredictionResponse:
    return DelayPredictionResponse(
        status="UNAVAILABLE",
        route_id=route_id,
        predicted_delay_minutes=None,
        confidence_pct=None,
        risk_level=None,
        primary_bottleneck_segment=None,
        weather_impact_pct=None,
        congestion_impact_pct=None,
        optimal_dispatch_window=None,
        limitation=reason,
    )


def _number(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def calculate_predictive_delay(
    *,
    route_id: UUID,
    segments: list[Any],
    score_breakdown: dict[str, Any],
) -> DelayPredictionResponse:
    """Deterministic advisory from the sealed route's stored segment features.

    This is intentionally not presented as calibrated ML and cannot allocate a
    dispatch slot. It refuses to operate without the route's persisted inputs.
    """

    if not segments:
        return unavailable_delay(route_id, "Stored route has no resolvable segment features")

    try:
        historical_minutes = [max(0.0, float(item.historical_delay_hours) * 60) for item in segments]
        congestion_minutes = [
            max(0.0, (float(item.congestion_factor) - 1.0) * 30) for item in segments
        ]
    except (TypeError, ValueError, AttributeError):
        return unavailable_delay(route_id, "Stored segment delay features are invalid")

    weather_score = _number(score_breakdown.get("weather"))
    weather_minutes = max(0.0, (100.0 - weather_score) * 0.3) if weather_score is not None else 0.0
    total = sum(historical_minutes) + sum(congestion_minutes) + weather_minutes
    predicted_delay = max(0, int(math.ceil(total)))

    if predicted_delay < 30:
        risk_level = "LOW"
    elif predicted_delay < 60:
        risk_level = "MODERATE"
    elif predicted_delay < 90:
        risk_level = "HIGH"
    else:
        risk_level = "CRITICAL"

    burdens = [
        historical_minutes[index] + congestion_minutes[index] for index in range(len(segments))
    ]
    bottleneck_index = max(range(len(segments)), key=burdens.__getitem__)
    bottleneck = segments[bottleneck_index]
    source = getattr(getattr(bottleneck, "source_station", None), "code", None)
    destination = getattr(getattr(bottleneck, "dest_station", None), "code", None)
    label = f"{source} → {destination}" if source and destination else str(bottleneck.id)

    denominator = total if total > 0 else None
    weather_pct = round(weather_minutes / denominator * 100, 1) if denominator else 0.0
    congestion_total = sum(congestion_minutes)
    congestion_pct = round(congestion_total / denominator * 100, 1) if denominator else 0.0
    limitation = (
        "Deterministic advisory from stored route features; no empirical confidence is claimed. "
        "Dispatch windows and movement authority must come from railway control."
    )
    if weather_score is None:
        limitation += " Weather evidence was unavailable and was excluded."

    return DelayPredictionResponse(
        status="AVAILABLE",
        route_id=route_id,
        predicted_delay_minutes=predicted_delay,
        confidence_pct=None,
        risk_level=risk_level,
        primary_bottleneck_segment=label,
        weather_impact_pct=weather_pct if weather_score is not None else None,
        congestion_impact_pct=congestion_pct,
        optimal_dispatch_window=None,
        limitation=limitation,
    )
