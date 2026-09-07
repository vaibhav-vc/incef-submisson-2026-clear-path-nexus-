from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.observability import provider_status

logger = logging.getLogger(__name__)

UNAVAILABLE_WEATHER = {"status": "unavailable", "source": "provider-unavailable"}
UNAVAILABLE_KP = {
    "status": "unavailable",
    "source": "provider-unavailable",
    "kp_index": None,
    "alert_level": "UNKNOWN",
    "issue_datetime": None,
}


def _with_provenance(
    payload: dict[str, Any],
    *,
    provider: str,
    raw_state: str,
    observed_at: str | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Attach decision-safe provider metadata; never include request credentials."""
    result = dict(payload)
    result["_provenance"] = {
        "provider": provider,
        "raw_state": raw_state,
        "observed_at": observed_at,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
    }
    return result


def _finite_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ValueError(f"{field} is outside the valid range")
    return number


def _parse_noaa_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NOAA response is missing a timestamp")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%m/%d/%Y %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError as exc:
            raise ValueError("NOAA timestamp format is unsupported") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_scoring_weather(payload: Any) -> tuple[float, float, list[int]]:
    """Validate every weather field used by the decision score; never infer clear weather."""
    if not isinstance(payload, dict):
        raise ValueError("Weather payload must be an object")
    wind = payload.get("wind")
    main = payload.get("main")
    weather = payload.get("weather")
    if not isinstance(wind, dict) or not isinstance(main, dict):
        raise ValueError("Weather payload is missing wind or main observations")
    if not isinstance(weather, list) or not weather:
        raise ValueError("Weather payload is missing condition observations")
    speed = _finite_number(wind.get("speed"), "wind.speed", minimum=0)
    visibility_value = payload.get("visibility", main.get("visibility"))
    visibility = _finite_number(visibility_value, "visibility", minimum=0)
    codes: list[int] = []
    for index, item in enumerate(weather):
        if not isinstance(item, dict):
            raise ValueError(f"weather[{index}] must be an object")
        code = _finite_number(item.get("id"), f"weather[{index}].id", minimum=0)
        codes.append(int(code))
    return speed, visibility, codes


class SpaceWeatherService:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
            )
        return self._redis

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            redis = await self._get_redis()
            raw = await redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _cache_set(self, key: str, payload: dict[str, Any], ttl: int = 900) -> None:
        try:
            redis = await self._get_redis()
            await redis.set(key, json.dumps(payload), ex=ttl)
        except Exception:
            pass

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def fetch_route_environmental_risks(self, lat: float, lon: float) -> dict[str, Any]:
        """Fetch configured weather data, falling back to Open-Meteo."""
        cache_key = f"weather:{lat:.2f}:{lon:.2f}"
        cached = await self._cache_get(cache_key)
        if cached:
            try:
                validate_scoring_weather(cached)
            except ValueError:
                cached = None
            else:
                cached_meta = cached.get("_provenance", {})
                return _with_provenance(
                    {k: v for k, v in cached.items() if k != "_provenance"},
                    provider=cached_meta.get("provider", "open_meteo"),
                    raw_state="CACHED",
                    observed_at=cached_meta.get("observed_at"),
                    fetched_at=cached_meta.get("fetched_at"),
                )

        if not settings.OPENWEATHER_API_KEY:
            try:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,visibility"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    current = resp.json().get("current", {})
                    required = {
                        "temperature_2m",
                        "relative_humidity_2m",
                        "weather_code",
                        "wind_speed_10m",
                        "visibility",
                    }
                    if not required.issubset(current):
                        raise ValueError("Open-Meteo response is missing current weather fields")
                    wind_kmh = _finite_number(
                        current["wind_speed_10m"], "wind_speed_10m", minimum=0
                    )
                    temperature = _finite_number(current["temperature_2m"], "temperature_2m")
                    visibility = _finite_number(current["visibility"], "visibility", minimum=0)
                    humidity = _finite_number(
                        current["relative_humidity_2m"], "relative_humidity_2m", minimum=0
                    )
                    weather_code = int(
                        _finite_number(current["weather_code"], "weather_code", minimum=0)
                    )
                    if humidity > 100 or weather_code > 99:
                        raise ValueError("Open-Meteo humidity or weather code is outside range")
                    owm_data = {
                        "wind": {"speed": round(wind_kmh / 3.6, 2)},
                        "main": {
                            "temp": temperature,
                            "visibility": visibility,
                            "humidity": humidity,
                        },
                        "weather": [
                            {
                                "id": 500 if weather_code >= 51 else 800,
                                "main": "Precipitation"
                                if weather_code >= 51
                                else "Clear",
                                "description": "precipitation"
                                if weather_code >= 51
                                else "clear sky",
                            }
                        ],
                    }
                    validate_scoring_weather(owm_data)
                    owm_data = _with_provenance(
                        owm_data,
                        provider="open_meteo",
                        raw_state="LIVE",
                        observed_at=current.get("time"),
                    )
                    await self._cache_set(cache_key, owm_data)
                    provider_status.record_success("open_meteo")
                    return owm_data
            except Exception as exc:
                provider_status.record_failure("open_meteo")
                logger.warning("Open-Meteo weather fetch failed: %s", exc)
                return _with_provenance(
                    UNAVAILABLE_WEATHER, provider="open_meteo", raw_state="UNAVAILABLE"
                )

        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"lat": lat, "lon": lon, "appid": settings.OPENWEATHER_API_KEY, "units": "metric"}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload = resp.json()
                validate_scoring_weather(payload)
                if not payload.get("dt"):
                    raise ValueError("OpenWeather payload is missing observation timestamp")
                data = _with_provenance(
                    payload,
                    provider="openweather",
                    raw_state="LIVE",
                    observed_at=datetime.fromtimestamp(
                        float(payload["dt"]), tz=timezone.utc
                    ).isoformat(),
                )
                await self._cache_set(cache_key, data)
                provider_status.record_success("openweather")
                return data
        except Exception as exc:
            provider_status.record_failure("openweather")
            logger.warning("Weather fetch failed: %s", exc)
            cached = await self._cache_get(cache_key)
        if cached:
            try:
                validate_scoring_weather(cached)
            except ValueError:
                cached = None
            else:
                cached_meta = cached.get("_provenance", {})
                return _with_provenance(
                    {k: v for k, v in cached.items() if k != "_provenance"},
                    provider=cached_meta.get("provider", "openweather"),
                    raw_state="CACHED",
                    observed_at=cached_meta.get("observed_at"),
                    fetched_at=cached_meta.get("fetched_at"),
                )
        return _with_provenance(
            UNAVAILABLE_WEATHER, provider="openweather", raw_state="UNAVAILABLE"
        )

    async def fetch_route_weather_point(
        self, point_id: str, lat: float, lon: float
    ) -> dict[str, Any]:
        """Return a fully populated live weather record or an explicit unavailable result."""
        cache_key = f"route_weather:{lat:.3f}:{lon:.3f}"
        cached = await self._cache_get(cache_key)
        if cached:
            return {"id": point_id, "lat": lat, "lon": lon, "available": True, **cached}

        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
            "wind_speed_10m,wind_direction_10m,visibility,uv_index,precipitation"
            f"&latitude={lat}&longitude={lon}&timezone=auto"
        )
        required = {
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "visibility",
            "uv_index",
            "precipitation",
        }
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                current = response.json().get("current", {})
            if not required.issubset(current):
                raise ValueError("Open-Meteo response is missing route-weather fields")
            payload = {field: current[field] for field in required}
            await self._cache_set(cache_key, payload, ttl=600)
            provider_status.record_success("open_meteo")
            return {"id": point_id, "lat": lat, "lon": lon, "available": True, **payload}
        except Exception as exc:
            provider_status.record_failure("open_meteo")
            logger.warning("Route weather fetch failed for %s: %s", point_id, exc)
            return {
                "id": point_id,
                "lat": lat,
                "lon": lon,
                "available": False,
                "message": "Weather provider unavailable; do not use this record for dispatch decisions.",
            }

    async def fetch_kp_index(self) -> dict[str, Any]:
        """Parse NOAA planetary Kp-index feed."""
        cache_key = "noaa:kp_index"
        cached = await self._cache_get(cache_key)
        if cached:
            cached_meta = cached.get("_provenance", {})
            return _with_provenance(
                {k: v for k, v in cached.items() if k != "_provenance"},
                provider="noaa_swpc",
                raw_state="CACHED",
                observed_at=cached.get("issue_datetime"),
                fetched_at=cached_meta.get("fetched_at"),
            )

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(settings.NOAA_SPACE_WEATHER_FEED_URL)
                resp.raise_for_status()
                rows = resp.json()
                if isinstance(rows, list) and rows:
                    latest = rows[-1]
                    if isinstance(latest, dict):
                        issue_datetime = latest.get("time_tag")
                        raw_kp = latest.get("Kp")
                    elif isinstance(latest, list) and len(latest) > 1:
                        issue_datetime = latest[0]
                        raw_kp = latest[1]
                    else:
                        raise ValueError("NOAA response is missing the latest Kp value")
                    if issue_datetime is None or raw_kp is None:
                        raise ValueError("NOAA response is missing timestamp or Kp value")
                    observed_at = _parse_noaa_timestamp(issue_datetime)
                    kp_number = _finite_number(raw_kp, "NOAA Kp", minimum=0)
                    if kp_number > 9:
                        raise ValueError("NOAA Kp is outside the valid 0–9 range")
                    kp_val = int(kp_number)
                    result = {
                        "kp_index": kp_val,
                        "alert_level": "WARNING" if kp_val >= 7 else "NONE",
                        "issue_datetime": observed_at.isoformat(),
                    }
                    result = _with_provenance(
                        result,
                        provider="noaa_swpc",
                        raw_state="LIVE",
                        observed_at=result["issue_datetime"],
                    )
                    await self._cache_set(cache_key, result)
                    provider_status.record_success("noaa_space_weather")
                    return result
        except Exception as exc:
            provider_status.record_failure("noaa_space_weather")
            logger.warning("NOAA fetch failed: %s", exc)

        cached = await self._cache_get(cache_key)
        if cached:
            cached_meta = cached.get("_provenance", {})
            return _with_provenance(
                {k: v for k, v in cached.items() if k != "_provenance"},
                provider="noaa_swpc",
                raw_state="CACHED",
                observed_at=cached.get("issue_datetime"),
                fetched_at=cached_meta.get("fetched_at"),
            )
        return _with_provenance(UNAVAILABLE_KP, provider="noaa_swpc", raw_state="UNAVAILABLE")

    def weather_to_score(
        self, weather_data: dict[str, Any], kp_data: dict[str, Any]
    ) -> tuple[float | None, list[str]]:
        alerts: list[str] = []
        score = 100.0

        if weather_data.get("status") == "unavailable":
            alerts.append("Weather provider unavailable — verify conditions before dispatch")
            if kp_data.get("status") == "unavailable":
                alerts.append("NOAA space-weather feed unavailable — telemetry risk is unknown")
            return None, alerts
        if kp_data.get("status") == "unavailable":
            alerts.append("NOAA space-weather feed unavailable — telemetry risk is unknown")
            return None, alerts

        try:
            wind, visibility, weather_codes = validate_scoring_weather(weather_data)
        except ValueError:
            alerts.append("Weather provider response is incomplete or invalid — conditions are unknown")
            return None, alerts

        if any(200 <= c < 700 for c in weather_codes):
            score -= 30
            alerts.append("Precipitation or storm conditions detected along corridor")
        if wind > 15:
            score -= 20
            alerts.append(f"High wind speeds ({wind} m/s)")
        if visibility < 5000:
            score -= 25
            alerts.append("Reduced visibility — dust/fog risk")

        kp = kp_data.get("kp_index")
        if kp is None:
            alerts.append("NOAA Kp-index missing — telemetry risk is unknown")
            return None, alerts
        if kp >= 7:
            score -= 35
            alerts.append(f"CRITICAL: Geomagnetic Kp-index {kp} — signaling telemetry risk")
        elif kp >= 5:
            score -= 10
            alerts.append(f"Elevated Kp-index {kp}")

        return max(0.0, min(100.0, score)), alerts


space_weather_service = SpaceWeatherService()
