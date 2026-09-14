from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.dust_storm_service import analyze_dust_storm_hazard
from app.services.geometry_service import fetch_railway_geometry_from_overpass
from app.services.indian_railways_service import fetch_indian_railways_live_forecast
from app.services.live_data import PROVIDERS
from app.services.live_port import AisCollector, PortActivitySource
from app.services.live_rail import RailDataSource, rail_client
from app.services.map_conditions import fetch_map_conditions_report
from app.services.port_sync import PortDataSource, fetch_port_schedule
from app.services.railradar import fetch_trains_between
from app.services.space_weather import SpaceWeatherService


@pytest.mark.asyncio
async def test_offline_demo_never_calls_weather_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LIVE_DATA_ENABLED", False)
    monkeypatch.setattr(settings, "ENABLE_LIVE_WEATHER", False)
    service = SpaceWeatherService()

    with patch("app.services.space_weather.httpx.AsyncClient") as client:
        weather = await service.fetch_route_environmental_risks(21.1458, 79.0882)
        point = await service.fetch_route_weather_point("demo", 21.1458, 79.0882)
        kp = await service.fetch_kp_index()

    client.assert_not_called()
    assert weather["_provenance"]["raw_state"] == "UNAVAILABLE"
    assert point["available"] is False
    assert kp["_provenance"]["raw_state"] == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_offline_demo_disables_every_external_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LIVE_DATA_ENABLED", False)
    monkeypatch.setattr(settings, "ENABLE_LIVE_WEATHER", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_RAIL", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_AIS", True)
    monkeypatch.setattr(settings, "RAILRADAR_API_KEY", "would-have-enabled-network")
    monkeypatch.setattr(settings, "AISSTREAM_API_KEY", "would-have-enabled-network")
    monkeypatch.setattr(settings, "MARITIME_BERTH_DATA_FEED", "https://provider.invalid")
    monkeypatch.setattr(settings, "MARITIME_FEED_API_KEY", "would-have-enabled-network")
    monkeypatch.setattr(settings, "DUST_AIR_QUALITY_FEED_URL", "https://provider.invalid")

    with (
        patch("httpx.AsyncClient") as http_client,
        patch("asyncio.create_task") as create_task,
    ):
        geometry = await fetch_railway_geometry_from_overpass(18.8, 72.8, 19.1, 73.1)
        map_report = await fetch_map_conditions_report(
            [{"id": "judge-point", "lat": 19.0, "lon": 72.9}]
        )
        network = await fetch_indian_railways_live_forecast()
        dust = await analyze_dust_storm_hazard(19.0, 72.9, "Judge corridor")
        port = await fetch_port_schedule("JNPT", "demo-vessel")
        trains = await fetch_trains_between("NGP", "JNPT")
        corridor = await rail_client.fetch_corridor(("NGP", "JNPT"))
        weather_envelope = await PROVIDERS["open_meteo"].fetch(
            {"location": {"latitude": 19.0, "longitude": 72.9}}
        )
        collector = AisCollector()
        await collector.start()

    http_client.assert_not_called()
    create_task.assert_not_called()
    assert geometry == []
    assert map_report["status"] == "UNAVAILABLE"
    assert network.overall_health_score is None
    assert dust.status == "UNAVAILABLE"
    assert port.source is PortDataSource.UNAVAILABLE
    assert trains["state"] == "DISABLED"
    assert corridor.source is RailDataSource.UNAVAILABLE
    assert weather_envelope.status == "UNAVAILABLE"
    assert collector.snapshot().source is PortActivitySource.UNAVAILABLE
