"""Authorised live-feed gateway: authentication, replay protection, map-matching and station events."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail.railguard.livefeed import IST, MAX_EVENTS, FeedGateway, FeedRejected, FeedSimulator, sign
from india_rail.railguard.national import NationalTwin

DAY = date(2026, 10, 7)
SECRET = bytes(range(32))


def _gateway(data, minute: float):  # noqa: F811
    twin = NationalTwin(data, start_min=minute)
    now = datetime.combine(DAY, datetime.min.time(), IST).timestamp() + minute * 60
    gateway = FeedGateway(twin, {("RTIS", "k1"): SECRET}, service_date=DAY, clock=lambda: now)
    return twin, gateway, FeedSimulator(gateway, "RTIS", "k1", SECRET, seed=1)


def test_signed_positions_make_evidence_live_and_reviewable(data):  # noqa: F811
    twin, gateway, sim = _gateway(data, 615.0)  # 12001 is between B and C; 54001 waits at D
    twin.disrupt("12001@0", "C", 6)
    assert twin.recommend("12001@0")["state"] == "PLANNING_ONLY"  # projections only: a rehearsal
    result = gateway.receive(sim.envelope([sim.position_event("12001@0"), sim.position_event("54001@0")]))
    assert result["accepted"] == 2 and result["results"][0]["section_id"] == "B-C"
    assert twin.position_state("12001@0") == twin.position_state("54001@0") == "FRESH"
    assert twin.recommend("12001@0")["state"] == "REVIEWABLE"  # every involved train is live: a real decision
    assert any(e["type"] == "FEED_BATCH" for e in twin.audit.events)


def test_envelope_attacks_are_refused(data):  # noqa: F811
    twin, gateway, sim = _gateway(data, 615.0)
    event = sim.position_event("12001@0")
    good = sim.envelope([event])
    tampered = {**good, "events": [{**event, "lat": event["lat"] + 0.01}]}
    with pytest.raises(FeedRejected, match="bad signature"):
        gateway.receive(tampered)
    with pytest.raises(FeedRejected, match="unknown source"):
        gateway.receive({**good, "key_id": "k2"})
    gateway.receive(good)
    with pytest.raises(FeedRejected, match="replayed nonce"):
        gateway.receive(good)
    old = sim.envelope([event], sent_at=datetime.fromtimestamp(gateway.clock() - 3600, IST))
    with pytest.raises(FeedRejected, match="clock window"):
        gateway.receive(old)
    replayed_sequence = sim.envelope([event])
    replayed_sequence["sequence"] = 1
    replayed_sequence["signature"] = sign(replayed_sequence, SECRET)
    with pytest.raises(FeedRejected, match="sequence"):
        gateway.receive(replayed_sequence)
    with pytest.raises(FeedRejected, match="events must be"):
        gateway.receive(sim.envelope([event] * (MAX_EVENTS + 1)))
    with pytest.raises(FeedRejected, match="no feed keys"):
        FeedGateway(twin, {}, service_date=DAY).receive(good)


def test_bad_events_are_rejected_one_by_one(data):  # noqa: F811
    twin, gateway, sim = _gateway(data, 615.0)
    event = sim.position_event("12001@0")
    off_route = {**event, "lat": event["lat"] + 0.2}  # ~22 km off the line
    future = {**event, "observed_at": datetime.fromtimestamp(gateway.clock() + 900, IST).isoformat()}
    unknown = {**event, "train_number": "99999"}
    result = gateway.receive(sim.envelope([off_route, future, unknown, {"type": "NOPE"}, "x", event]))
    assert [r["accepted"] for r in result["results"]] == [False, False, False, False, False, True]
    assert "ROUTE_DEVIATION" in {t.type for t in twin.threats.active()}


def test_late_departure_is_recorded_as_a_disruption_for_the_controller(data):  # noqa: F811
    twin, gateway, sim = _gateway(data, 620.0)  # planned to leave B at 10:11; observed leaving at 10:20
    observed = datetime.combine(DAY, datetime.min.time(), IST).replace(hour=10, minute=20)
    station = {"type": "STATION", "train_number": "12001", "start_date": DAY.isoformat(), "station_code": "B",
               "event": "DEP", "observed_at": observed.isoformat()}  # fmt: skip
    result = gateway.receive(sim.envelope([station]))["results"][0]
    assert result["accepted"] and result["late_min"] == 9.0
    assert result["disruption_recorded"] == {"station": "B", "delay_min": 9.0}
    assert "12001@0" in twin.pending  # a controller decision is now needed; the feed approved nothing
    assert twin.position("12001@0")["section_id"] == "B-C"


def test_feed_endpoint_requires_feed_role_and_valid_signature(data, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from india_rail import security
    from india_rail.api import app
    from india_rail.railguard import api as railguard_api

    tokens = {"viewer": "v" * 40, "controller": "c" * 40, "feed": "f" * 40}
    monkeypatch.setenv("RAILGUARD_RATE_LIMIT", "off")
    for role, env in security.ROLE_ENV.items():
        monkeypatch.setenv(env, tokens[role])
    _twin, gateway, sim = _gateway(data, 615.0)
    monkeypatch.setattr(railguard_api, "_gateway", lambda: gateway)
    client = TestClient(app)
    good = sim.envelope([sim.position_event("12001@0")])
    url = "/railguard/national/feed/batch"
    assert client.post(url, json=good, headers={"Authorization": f"Bearer {tokens['viewer']}"}).status_code == 403
    assert client.post(url, json=good, headers={"Authorization": f"Bearer {tokens['controller']}"}).status_code == 403
    feed = {"Authorization": f"Bearer {tokens['feed']}"}
    bad = {**good, "signature": "0" * 64}
    refused = client.post(url, json=bad, headers=feed)
    assert refused.status_code == 401 and "bad signature" in refused.json()["detail"]
    ok = client.post(url, json=good, headers=feed)
    assert ok.status_code == 200 and ok.json()["accepted"] == 1
