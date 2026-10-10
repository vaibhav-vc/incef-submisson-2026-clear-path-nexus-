"""TrackSense: relative infrastructure-stress and energy indices.

These are explainable *research indices* for ranking alternatives on the demo
network. They are not a certified track-deterioration or traction model: every
factor is a documented multiplier clamped to 0.5-2.0 so no single input
dominates and no false precision is implied.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from india_rail.railguard.model import Section, Train


def _clamp(value: float, low: float = 0.5, high: float = 2.0) -> float:
    return max(low, min(high, value))


def running_speed(train: Train, section: Section) -> float:
    """Planned speed: the lowest of train, line and temporary-restriction limits."""

    limits = [train.vmax_kmph, section.vmax_kmph]
    if section.temp_restriction_kmph:
        limits.append(section.temp_restriction_kmph)
    return float(min(limits))


FACTOR_NAMES = ("load", "speed", "geometry", "condition", "asset", "weather", "utilisation")


@lru_cache(maxsize=65_536)
def _factors(
    axle_t: float, speed: float, curvature: float, gradient: float, condition: float, asset: float, weather: bool,
    utilisation: float,
) -> tuple[float, ...]:  # fmt: skip
    return (
        _clamp(axle_t / 20.0),
        _clamp(speed / 80.0),
        _clamp(curvature * gradient),
        _clamp(1.0 + 1.5 * (1.0 - condition)),
        _clamp(asset),
        1.3 if weather else 1.0,
        _clamp(0.75 + utilisation / 200.0),
    )


def stress_factors(train: Train, section: Section, speed_kmph: float) -> dict[str, float]:
    values = _factors(
        train.axle_load_t,
        speed_kmph,
        section.curvature,
        section.gradient,
        section.condition,
        section.asset_sensitivity,
        bool(section.weather_alert),
        section.utilisation,
    )
    return dict(zip(FACTOR_NAMES, values, strict=True))


def section_stress(train: Train, section: Section, speed_kmph: float) -> dict[str, Any]:
    """Stress units for one traversal = product of factors x length (km)."""

    factors = stress_factors(train, section, speed_kmph)
    product = 1.0
    for value in factors.values():
        product *= value
    return {"section_id": section.id, "factors": factors, "stress": round(product * section.length_km, 3)}


def section_energy(train: Train, section: Section, speed_kmph: float) -> float:
    """Energy proxy (relative units): mass x distance x (rolling + speed^2 + gradient) terms."""

    speed_term = 0.6 + 0.4 * (speed_kmph / 100.0) ** 2
    return train.mass_t / 1000.0 * section.length_km * speed_term * section.gradient


def restart_energy(train: Train) -> float:
    """Energy proxy for stopping and restarting a train at a planned hold."""

    return train.mass_t / 1000.0 * 2.0
