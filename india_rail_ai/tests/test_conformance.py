"""Feed conformance kit: the producer check, the endpoint battery, and agreement with the real gateway."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from test_livefeed import DAY, SECRET, _gateway
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail.railguard import conformance
from india_rail.railguard.livefeed import IST, sign


def _sample(data):  # noqa: F811
    _twin, gateway, sim = _gateway(data, 615.0)
    return gateway, sim, [sim.envelope([sim.position_event("12001@0")]) for _ in range(3)]


def test_a_correct_producer_sample_passes(data):  # noqa: F811
    _gw, _sim, envelopes = _sample(data)
    cert = conformance.check_producer(envelopes, SECRET, "RTIS")
    assert cert["result"] == "PASS" and cert["envelopes"] == 3 and cert["events"] == 3


def test_producer_faults_are_each_named(data):  # noqa: F811
    _gw, sim, envelopes = _sample(data)
    replay = dict(envelopes[1], nonce=envelopes[0]["nonce"])
    replay["signature"] = sign(replay, SECRET)
    unsigned = dict(envelopes[2], signature="ab" * 32)
    stale_event = dict(envelopes[2]["events"][0])
    stale_event["observed_at"] = (datetime.fromisoformat(envelopes[2]["sent_at"]) - timedelta(minutes=5)).isoformat()
    stale = sim.envelope([stale_event])
    extra = sim.envelope([{**envelopes[0]["events"][0], "driver_name": "x"}])
    cert = conformance.check_producer([envelopes[0], replay, unsigned, stale, extra], SECRET, "RTIS")
    problems = [" ".join(c["problems"]) for c in cert["details"]]
    assert cert["result"] == "FAIL" and problems[0] == ""
    assert "nonce reused" in problems[1]
    assert "does not verify" in problems[2]
    assert "stale" in problems[3]
    assert "unexpected fields" in problems[4]  # personal data has no place in a feed: refused by shape


@pytest.mark.parametrize(
    "bad",
    [{"lat": 51.5, "lon": -0.1}, {"speed_kmph": 300}, {"hdop": 9.0}, {"satellites": 2}, {"type": "TELEPORT"},
     {"train_number": "12 001"}, {"observed_at": "2026-10-07T10:15:00"}],
)  # fmt: skip
def test_what_the_kit_flags_the_real_gateway_refuses(data, bad):  # noqa: F811
    gateway, sim, envelopes = _sample(data)
    event = {**envelopes[0]["events"][0], **bad}
    assert conformance.event_problems(event)
    result = gateway.receive(sim.envelope([event]))["results"][0]
    assert not result["accepted"]


class _Client:
    """The kit's POST interface over FastAPI's test client."""

    def __init__(self, client):
        self.client = client

    def __call__(self, body, token):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        raw = body if isinstance(body, str) else json.dumps(body)
        r = self.client.post("/railguard/national/feed/batch", content=raw, headers=headers)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}


def test_the_endpoint_battery_passes_against_the_real_receiver(data, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from india_rail import security
    from india_rail.api import app
    from india_rail.railguard import api as railguard_api

    tokens = {"viewer": "v" * 40, "controller": "c" * 40, "feed": "f" * 40}
    monkeypatch.setenv("RAILGUARD_RATE_LIMIT", "off")
    for role, env in security.ROLE_ENV.items():
        monkeypatch.setenv(env, tokens[role])
    _twin, gateway, _sim = _gateway(data, 615.0)
    monkeypatch.setattr(railguard_api, "_gateway", lambda: gateway)
    now = lambda: datetime.fromtimestamp(gateway.clock(), IST)  # noqa: E731 - the receiver's clock
    cert = conformance.check_endpoint(
        _Client(TestClient(app)), "RTIS", "k1", SECRET, tokens["feed"], "12001", "C", now=now
    )
    assert cert["result"] == "PASS", [c for c in cert["details"] if not c["passed"]]
    assert cert["checks"] == 10
    # A wrong key fails the battery: the good envelope is refused instead of received.
    wrong = conformance.check_endpoint(
        _Client(TestClient(app)), "RTIS", "k1", bytes(32), tokens["feed"], "12001", "C", now=now
    )
    assert wrong["result"] == "FAIL"


def test_keys_never_travel_in_clear_text():
    with pytest.raises(ValueError, match="https"):
        conformance.http_post("http://nexus.example.in")
    conformance.http_post("http://127.0.0.1:8100")  # this machine only
    conformance.http_post("https://nexus.example.in")


def test_day_constant_is_the_feed_tests_day():
    assert DAY.isoformat() == "2026-10-07"
