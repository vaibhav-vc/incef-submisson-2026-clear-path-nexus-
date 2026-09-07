import pytest
from datetime import datetime, timedelta, timezone

from app.services.map_conditions import (
    fetch_map_conditions,
    fetch_map_conditions_report,
    map_weather_to_conditions,
)
from app.services.port_sync import compute_port_sync_score
from app.services.railradar import fetch_trains_between
from app.services.space_weather import SpaceWeatherService, _parse_noaa_timestamp


def test_current_noaa_timestamp_is_canonicalized_to_utc() -> None:
    parsed = _parse_noaa_timestamp("08/31/2026 06:00:00")

    assert parsed == datetime(2026, 8, 31, 6, tzinfo=timezone.utc)
    assert parsed.isoformat() == "2026-08-31T06:00:00+00:00"


def test_invalid_noaa_timestamp_fails_closed() -> None:
    with pytest.raises(ValueError, match="timestamp"):
        _parse_noaa_timestamp("not-a-time")


def test_port_sync_score_uses_timezone_aware_window() -> None:
    score, warning = compute_port_sync_score(
        24.0,
        {
            "start_time": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
            "end_time": (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(),
        },
    )

    assert 60.0 <= score <= 100.0
    assert warning is None


def test_unavailable_environment_is_not_scored_as_clear() -> None:
    score, alerts = SpaceWeatherService().weather_to_score(
        {"status": "unavailable"},
        {"status": "unavailable", "kp_index": None},
    )

    assert score is None
    assert any("unavailable" in alert.lower() for alert in alerts)


def test_live_weather_with_unavailable_noaa_is_not_scored_as_clear() -> None:
    score, alerts = SpaceWeatherService().weather_to_score(
        {"weather": [{"id": 800}], "wind": {"speed": 2}, "main": {"visibility": 10000}},
        {"status": "unavailable", "kp_index": None},
    )

    assert score is None
    assert any("NOAA" in alert for alert in alerts)


def test_malformed_weather_is_not_scored_as_clear() -> None:
    score, alerts = SpaceWeatherService().weather_to_score(
        {},
        {"status": "available", "kp_index": 2},
    )

    assert score is None
    assert any("incomplete or invalid" in alert for alert in alerts)


def test_clear_openweather_code_is_not_precipitation() -> None:
    score, alerts = SpaceWeatherService().weather_to_score(
        {"weather": [{"id": 800}], "wind": {"speed": 2}, "main": {"visibility": 10000}},
        {"status": "available", "kp_index": 2},
    )

    assert score == 100.0
    assert not any("precipitation" in alert.lower() for alert in alerts)


def test_native_openweather_visibility_field_is_accepted() -> None:
    score, alerts = SpaceWeatherService().weather_to_score(
        {
            "weather": [{"id": 800}],
            "wind": {"speed": 2},
            "main": {"temp": 28},
            "visibility": 10_000,
        },
        {"status": "available", "kp_index": 2},
    )

    assert score == 100.0
    assert alerts == []


@pytest.mark.asyncio
async def test_map_conditions_does_not_emit_all_clear_when_weather_fails(monkeypatch) -> None:
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.services.map_conditions.fetch_open_meteo", unavailable)

    async def unavailable_kp():
        return {"status": "unavailable", "kp_index": None}

    monkeypatch.setattr(
        "app.services.map_conditions.space_weather_service.fetch_kp_index",
        unavailable_kp,
    )

    conditions = await fetch_map_conditions([{"lat": 21.1, "lon": 79.1, "id": "NGP"}])

    assert conditions == []


def test_map_conditions_rejects_missing_weather_fields() -> None:
    with pytest.raises(ValueError, match="missing"):
        map_weather_to_conditions({}, 21.1, 79.1, "NGP")


@pytest.mark.asyncio
async def test_map_conditions_reports_per_point_provider_failure(monkeypatch) -> None:
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.services.map_conditions.fetch_open_meteo", unavailable)
    async def unavailable_kp():
        return {"status": "unavailable", "kp_index": None}

    monkeypatch.setattr(
        "app.services.map_conditions.space_weather_service.fetch_kp_index",
        unavailable_kp,
    )
    report = await fetch_map_conditions_report(
        [{"lat": 21.1, "lon": 79.1, "id": "NGP"}]
    )
    assert report["status"] == "UNAVAILABLE"
    assert report["source"] == "unavailable"
    assert report["failures"] == [
        {"point_id": "NGP", "message": "provider unavailable"},
        {"point_id": "NOAA_KP", "message": "NOAA Kp observation unavailable"},
    ]


@pytest.mark.asyncio
async def test_map_conditions_reports_noaa_unavailable(monkeypatch) -> None:
    async def available_weather(*_args, **_kwargs):
        return {
            "temperature_2m": 27,
            "relative_humidity_2m": 60,
            "weather_code": 1,
            "wind_speed_10m": 5,
            "visibility": 10000,
            "uv_index": 3,
        }

    async def unavailable_kp():
        return {"status": "unavailable", "kp_index": None}

    monkeypatch.setattr("app.services.map_conditions.fetch_open_meteo", available_weather)
    monkeypatch.setattr(
        "app.services.map_conditions.space_weather_service.fetch_kp_index",
        unavailable_kp,
    )
    report = await fetch_map_conditions_report(
        [{"lat": 21.1, "lon": 79.1, "id": "NGP"}]
    )

    assert report["status"] == "UNAVAILABLE"
    assert report["source"] == "unavailable"
    assert report["failures"][0]["point_id"] == "NOAA_KP"


@pytest.mark.asyncio
async def test_railradar_reports_unavailable_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr("app.services.railradar.settings.RAILRADAR_API_KEY", "")

    result = await fetch_trains_between("NGP", "JNPT")

    assert result["available"] is False
    assert result["trains"] == []
