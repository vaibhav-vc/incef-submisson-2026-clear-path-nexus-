"""Port sync must never silently invent a schedule."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.port_sync import (
    LoadingWindow,
    PortDataSource,
    PortSchedule,
    _window_from_payload,
    compute_port_sync,
    fetch_port_schedule,
)
from app.services.reliability import calculate_route_reliability
from app.schemas.route import RouteEvaluateRequest, RouteSuggestRequest

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def test_route_port_context_has_no_operational_defaults() -> None:
    for request_type in (RouteEvaluateRequest, RouteSuggestRequest):
        for field_name in ("port_id", "vessel_id", "train_arrival_hours"):
            assert request_type.model_fields[field_name].is_required()


def _window(start_h: float, end_h: float) -> LoadingWindow:
    return LoadingWindow(start=NOW + timedelta(hours=start_h), end=NOW + timedelta(hours=end_h))


def _schedule(source=PortDataSource.LIVE_FEED, window=None) -> PortSchedule:
    return PortSchedule(source=source, window=window or _window(12, 48))


def test_unavailable_is_not_a_zero_score():
    """The bug: an unreachable feed used to look like a terrible port score."""
    result = compute_port_sync(24.0, PortSchedule(source=PortDataSource.UNAVAILABLE))
    assert result.available is False
    assert result.aligned is False
    assert result.warning and "excluded" in result.warning.lower()


def test_unavailable_port_does_not_drag_the_score_down():
    with_port_missing = calculate_route_reliability(80, 0, 70, 60, port_available=False)
    as_if_port_were_terrible = calculate_route_reliability(80, 0, 70, 60, port_available=True)
    assert with_port_missing > as_if_port_were_terrible


def test_operator_window_is_scored_normally():
    schedule = PortSchedule(
        source=PortDataSource.OPERATOR_INPUT,
        port_id="INNSA",
        vessel_id="IMO1234567",
        window=_window(12, 48),
    )
    result = compute_port_sync(24.0, schedule, now=NOW)
    assert result.available is True
    assert result.source is PortDataSource.OPERATOR_INPUT
    assert 0 < result.score <= 100
    assert result.evaluated_at == NOW
    assert result.train_arrival_hours == 24.0
    assert result.window == _schedule(PortDataSource.OPERATOR_INPUT).window
    assert result.port_id == "INNSA"
    assert result.vessel_id == "IMO1234567"


@pytest.mark.asyncio
async def test_live_maritime_feed_sends_bearer_and_preserves_requested_identities(
    monkeypatch,
) -> None:
    from app.services import port_sync

    captured: dict = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "berth_id": "BMCT-4",
                "vessel_status": "SCHEDULED",
                "observed_at": NOW.isoformat(),
                "loading_window": {
                    "start_time": (NOW + timedelta(hours=12)).isoformat(),
                    "end_time": (NOW + timedelta(hours=48)).isoformat(),
                },
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return Response()

    monkeypatch.setattr(port_sync.httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        port_sync.settings, "MARITIME_BERTH_DATA_FEED", "https://maritime.test/api"
    )
    monkeypatch.setattr(port_sync.settings, "MARITIME_FEED_API_KEY", "maritime-secret")

    schedule = await fetch_port_schedule("INNSA", "IMO1234567")
    result = compute_port_sync(24, schedule, now=NOW)

    assert captured["params"] == {"port_id": "INNSA", "vessel_id": "IMO1234567"}
    assert captured["headers"] == {"Authorization": "Bearer maritime-secret"}
    assert (schedule.port_id, schedule.vessel_id) == ("INNSA", "IMO1234567")
    assert (result.port_id, result.vessel_id) == ("INNSA", "IMO1234567")


def test_port_schedule_is_sealed_to_berth_window_expiry():
    window = _window(12, 48)
    schedule = PortSchedule(
        source=PortDataSource.LIVE_FEED,
        window=window,
        observed_at=NOW - timedelta(minutes=2),
        fetched_at=NOW,
        valid_until=window.end,
    )

    result = compute_port_sync(24.0, schedule, now=NOW)

    assert result.observed_at == NOW - timedelta(minutes=2)
    assert result.fetched_at == NOW
    assert result.valid_until == window.end


def test_arrival_inside_window_is_aligned():
    result = compute_port_sync(24.0, _schedule(window=_window(12, 48)), now=NOW)
    assert result.aligned is True
    assert result.warning is None
    assert result.score >= 60


def test_arrival_after_window_is_critical():
    result = compute_port_sync(72.0, _schedule(window=_window(12, 48)), now=NOW)
    assert result.score == 0.0
    assert result.aligned is False
    assert "misses vessel loading window" in result.warning


def test_live_feed_rejects_reversed_loading_window() -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        _window_from_payload(
            {
                "loading_window": {
                    "start_time": (NOW + timedelta(hours=10)).isoformat(),
                    "end_time": (NOW + timedelta(hours=5)).isoformat(),
                }
            }
        )


def test_early_arrival_warns_but_does_not_zero():
    result = compute_port_sync(1.0, _schedule(window=_window(12, 48)), now=NOW)
    assert result.aligned is False
    assert result.score >= 40.0
    assert "early" in result.warning
