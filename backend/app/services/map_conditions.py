from __future__ import annotations

import math
from typing import Any

import httpx

from app.services.space_weather import space_weather_service

OPEN_METEO = (
    "https://api.open-meteo.com/v1/forecast"
    "?current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,visibility,uv_index"
    "&timezone=auto"
)


def _primary_weather_type(code: int) -> str:
    if code == 0:
        return "clear"
    if code == 1:
        return "partly_cloudy"
    if code in (2, 3):
        return "cloudy"
    if code == 45:
        return "mist"
    if code == 48:
        return "fog"
    if 51 <= code <= 57:
        return "light_rain"
    if 61 <= code <= 65:
        return "heavy_rain" if code >= 63 else "light_rain"
    if 66 <= code <= 67:
        return "sleet"
    if 71 <= code <= 77:
        return "snow"
    if 80 <= code <= 82:
        return "heavy_rain"
    if 85 <= code <= 86:
        return "snow"
    if 95 <= code <= 99:
        return "hail" if code >= 96 else "thunderstorm"
    return "cloudy"


def map_weather_to_conditions(
    data: dict[str, Any], lat: float, lon: float, point_id: str
) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    current = validate_open_meteo_current(data)
    code = int(current["weather_code"])
    temp = current["temperature_2m"]
    humidity = current["relative_humidity_2m"]
    wind = current["wind_speed_10m"]
    visibility = current["visibility"]
    uv = current["uv_index"]

    primary = _primary_weather_type(code)
    conditions.append(
        {
            "id": f"{point_id}-{primary}",
            "type": primary,
            "category": "weather",
            "lat": lat,
            "lon": lon,
            "reading": f"{round(temp)}°C",
        }
    )

    if wind >= 20:
        conditions.append(
            {
                "id": f"{point_id}-high_winds",
                "type": "high_winds",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"{round(wind)} km/h",
            }
        )
    elif wind >= 10:
        conditions.append(
            {
                "id": f"{point_id}-strong_wind",
                "type": "strong_wind",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"{round(wind)} km/h",
            }
        )

    if temp >= 35:
        conditions.append(
            {
                "id": f"{point_id}-high_temp",
                "type": "high_temp",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"{round(temp)}°C",
            }
        )
    elif temp <= 5:
        conditions.append(
            {
                "id": f"{point_id}-low_temp",
                "type": "low_temp",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"{round(temp)}°C",
            }
        )

    if humidity >= 85:
        conditions.append(
            {
                "id": f"{point_id}-high_humidity",
                "type": "high_humidity",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"{round(humidity)}%",
            }
        )
    elif humidity <= 30:
        conditions.append(
            {
                "id": f"{point_id}-low_humidity",
                "type": "low_humidity",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"{round(humidity)}%",
            }
        )

    if 0 < visibility < 2000:
        conditions.append(
            {
                "id": f"{point_id}-low_visibility",
                "type": "low_visibility",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"{visibility / 1000:.1f} km",
            }
        )

    if uv >= 8:
        conditions.append(
            {
                "id": f"{point_id}-high_uv",
                "type": "high_uv",
                "category": "weather",
                "lat": lat,
                "lon": lon,
                "reading": f"UV {round(uv)}",
            }
        )

    if temp <= 2 and 51 <= code <= 67:
        conditions.append(
            {
                "id": f"{point_id}-icing",
                "type": "icing",
                "category": "weather",
                "lat": lat,
                "lon": lon,
            }
        )

    if code >= 95:
        conditions.append(
            {
                "id": f"{point_id}-storm_warning",
                "type": "storm_warning",
                "category": "environmental",
                "lat": lat,
                "lon": lon,
            }
        )

    if code >= 63 and humidity > 80:
        conditions.append(
            {
                "id": f"{point_id}-flood_risk",
                "type": "flood_risk",
                "category": "environmental",
                "lat": lat,
                "lon": lon,
            }
        )

    if 0 < visibility < 3000 and wind > 8 and humidity < 40:
        conditions.append(
            {
                "id": f"{point_id}-dust",
                "type": "dust",
                "category": "weather",
                "lat": lat,
                "lon": lon,
            }
        )

    return conditions


_REQUIRED_CURRENT_FIELDS = (
    "weather_code",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "visibility",
    "uv_index",
)


def validate_open_meteo_current(data: Any) -> dict[str, float]:
    if not isinstance(data, dict):
        raise ValueError("Open-Meteo current observation is not an object")
    missing = [key for key in _REQUIRED_CURRENT_FIELDS if key not in data]
    if missing:
        raise ValueError(f"Open-Meteo current observation is missing: {', '.join(missing)}")
    parsed: dict[str, float] = {}
    for key in _REQUIRED_CURRENT_FIELDS:
        value = data[key]
        if isinstance(value, bool):
            raise ValueError(f"Open-Meteo field {key} is not numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Open-Meteo field {key} is not numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"Open-Meteo field {key} is not finite")
        parsed[key] = number
    if not 0 <= parsed["weather_code"] <= 99:
        raise ValueError("Open-Meteo weather_code is outside the supported range")
    if not 0 <= parsed["relative_humidity_2m"] <= 100:
        raise ValueError("Open-Meteo relative_humidity_2m is outside 0..100")
    if parsed["wind_speed_10m"] < 0 or parsed["visibility"] < 0 or parsed["uv_index"] < 0:
        raise ValueError("Open-Meteo wind, visibility, and UV values must be non-negative")
    return parsed


async def fetch_open_meteo(lat: float, lon: float) -> dict[str, Any]:
    cache_key = f"openmeteo:{lat:.2f}:{lon:.2f}"
    cached = await space_weather_service._cache_get(cache_key)
    if cached:
        validate_open_meteo_current(cached)
        return cached

    url = f"{OPEN_METEO}&latitude={lat}&longitude={lon}"
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("Open-Meteo response is not an object")
        current = payload.get("current")
        validate_open_meteo_current(current)
        await space_weather_service._cache_set(cache_key, current, ttl=600)
        return current


async def fetch_map_conditions(
    points: list[dict[str, Any]], destination_code: str | None = None
) -> list[dict[str, Any]]:
    report = await fetch_map_conditions_report(points, destination_code)
    return report["conditions"]


async def fetch_map_conditions_report(
    points: list[dict[str, Any]], destination_code: str | None = None
) -> dict[str, Any]:
    all_conditions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for i, point in enumerate(points[:8]):
        lat = float(point["lat"])
        lon = float(point["lon"])
        point_id = str(point.get("id", f"pt-{i}"))
        try:
            data = await fetch_open_meteo(lat, lon)
            mapped = map_weather_to_conditions(data, lat, lon, point_id)
            all_conditions.extend(mapped)
        except Exception as exc:
            failures.append({"point_id": point_id, "message": str(exc)[:240]})

    try:
        kp_data = await space_weather_service.fetch_kp_index()
    except Exception as exc:
        kp_data = {"status": "unavailable", "kp_index": None}
        failures.append({"point_id": "NOAA_KP", "message": str(exc)[:240]})
    if kp_data.get("status") == "unavailable" or kp_data.get("kp_index") is None:
        if not any(failure["point_id"] == "NOAA_KP" for failure in failures):
            failures.append(
                {"point_id": "NOAA_KP", "message": "NOAA Kp observation unavailable"}
            )
        kp = None
    else:
        kp = int(kp_data["kp_index"])
    if kp is not None and kp >= 5 and points:
        p = points[0]
        all_conditions.append(
            {
                "id": "solar-kp",
                "type": "solar",
                "category": "weather",
                "lat": float(p["lat"]),
                "lon": float(p["lon"]),
                "reading": f"Kp {kp}",
            }
        )

    return {
        "status": "UNAVAILABLE" if failures else "AVAILABLE",
        "conditions": all_conditions,
        "source": "open-meteo" if not failures else "unavailable",
        "failures": failures,
    }
