"""Live, one-to-one: console and cab event streams, run-scoped cab capability tokens."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail.railguard import live
from india_rail.railguard.national import NationalTwin


@pytest.fixture()
def client(data, monkeypatch):  # noqa: F811
    from india_rail import api
    from india_rail.railguard import api as rg

    twin = NationalTwin(data, start_min=615.0)
    monkeypatch.setattr(rg, "_national", lambda: twin)
    monkeypatch.setattr(live, "TICK_S", 0.01)
    live.HUB.cached = None
    return TestClient(api.app), twin


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_cab_tokens_are_scoped_to_one_run_and_expire():
    issued = live.issue_cab_token("12001@0", ttl_s=60, clock=lambda: 1000.0)
    token = issued["token"]
    assert live.cab_token_valid(token, "12001@0", clock=lambda: 1059.0)
    assert not live.cab_token_valid(token, "12001@0", clock=lambda: 1061.0)  # expired
    assert not live.cab_token_valid(token, "54001@0", clock=lambda: 1001.0)  # another train
    body, mac = token.split(".")
    assert not live.cab_token_valid(body + "." + "0" * 64, "12001@0", clock=lambda: 1001.0)  # forged
    assert not live.cab_token_valid("not-a-token", "12001@0") and not live.cab_token_valid(None, "12001@0")


def test_console_stream_pushes_positions_and_threats(client):
    http, twin = client
    response = http.get("/railguard/national/stream?events=1")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    (kind, state), *_ = _events(response.text)
    assert kind == "state" and {p[0] for p in state["positions"]} >= {"12001@0"}
    assert "threats" in state and state["minute"] == 615.0


def test_cab_unit_sees_its_own_train_only(client):
    http, twin = client
    issued = http.post("/railguard/national/cab/12001@0/token", json={"hours": 2, "issued_by": "SCR Delhi"}).json()
    token = issued["token"]
    assert any(e["type"] == "CAB_TOKEN_ISSUED" and "token" not in e["details"] for e in twin.audit.events)
    mine = http.get("/railguard/national/cab/12001@0/live", headers={"Authorization": f"Bearer {token}"})
    assert mine.status_code == 200 and mine.json()["run"] == "12001@0"
    assert (
        http.get("/railguard/national/cab/54001@0/live", headers={"Authorization": f"Bearer {token}"}).status_code
        == 403
    )
    assert http.get("/railguard/national/cab/12001@0/live").status_code == 403
    streamed = http.get(f"/railguard/national/cab/12001@0/stream?events=1&token={token}")
    (kind, advisory), *_ = _events(streamed.text)
    assert kind == "advisory" and advisory["run"] == "12001@0"
    assert http.post("/railguard/national/cab/99999@0/token", json={"issued_by": "x"}).status_code == 404


def test_stream_capacity_is_bounded(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(live, "MAX_STREAMS", 0)
    refused = http.get("/railguard/national/stream?events=1")
    assert _events(refused.text)[0][0] == "refused"


def test_a_quiet_stream_still_sends_heartbeats(data, monkeypatch):  # noqa: F811
    """A train whose advisory does not change must not go silent: proxies drop silent connections."""

    import asyncio

    twin = NationalTwin(data, start_min=615.0)
    monkeypatch.setattr(live, "TICK_S", 0.01)
    monkeypatch.setattr(live, "HEARTBEAT_S", 0.05)

    async def run() -> list[bytes]:
        async def connected() -> bool:
            return False

        gen = live.stream(twin, "12001@0", connected, None, "advisory")
        return [await asyncio.wait_for(gen.__anext__(), 2) for _ in range(4)]

    chunks = asyncio.run(run())
    assert chunks[1].startswith(b"id: 1\nevent: advisory") and chunks[2:] == [b": heartbeat\n\n"] * 2
