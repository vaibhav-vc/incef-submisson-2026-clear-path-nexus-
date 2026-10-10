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
    streamed = http.get("/railguard/national/cab/12001@0/stream?events=1", headers={"Authorization": f"Bearer {token}"})
    (kind, advisory), *_ = _events(streamed.text)
    assert kind == "advisory" and advisory["run"] == "12001@0"
    assert http.post("/railguard/national/cab/99999@0/token", json={"issued_by": "x"}).status_code == 404


def test_a_controller_revokes_one_cab_link_or_every_link_of_a_train(client):
    http, twin = client
    bearer = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
    url = "/railguard/national/cab/12001@0/live"
    one = http.post("/railguard/national/cab/12001@0/token", json={"issued_by": "SCR"}).json()
    two = http.post("/railguard/national/cab/12001@0/token", json={"issued_by": "SCR"}).json()
    assert any(
        e["type"] == "CAB_TOKEN_ISSUED" and e["details"]["token_id"] == one["token_id"] for e in twin.audit.events
    )
    revoked = http.post(
        "/railguard/national/cab/12001@0/revoke", json={"token_id": one["token_id"], "revoked_by": "SCR"}
    )
    assert revoked.status_code == 200
    assert http.get(url, headers=bearer(one["token"])).status_code == 403
    assert http.get(url, headers=bearer(two["token"])).status_code == 200  # only that link
    http.post("/railguard/national/cab/12001@0/revoke", json={"revoked_by": "SCR"})
    assert http.get(url, headers=bearer(two["token"])).status_code == 403
    three = http.post("/railguard/national/cab/12001@0/token", json={"issued_by": "SCR"}).json()
    assert http.get(url, headers=bearer(three["token"])).status_code == 200  # a link issued afterwards works
    assert any(e["type"] == "CAB_LINK_REVOKED" for e in twin.audit.events)


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


def test_an_open_cab_stream_ends_when_its_link_is_revoked(client):
    import asyncio

    _http, twin = client
    valid = {"now": True}

    async def collect():
        async def connected():
            return False

        out = []
        async for chunk in live.stream(twin, "12001@0", connected, None, "advisory", allowed=lambda: valid["now"]):
            out.append(chunk)
            if chunk.startswith(b"id: "):  # the first advisory reached the cab: now the controller revokes the link
                valid["now"] = False
        return b"".join(out).decode()

    text = asyncio.run(collect())
    assert "event: advisory" in text and text.rstrip().endswith('{"detail": "this cab link is no longer valid"}')
    assert "event: revoked" in text


def test_cab_streams_have_capacity_viewers_cannot_take(monkeypatch):
    monkeypatch.setattr(live, "MAX_CONSOLE_STREAMS", 2)
    hub = live.Hub()
    assert hub.open("console", "a") and hub.open("console", "b")
    assert not hub.open("console", "c")  # control screens are capped ...
    assert hub.open("cab", "link-1")  # ... so a cab unit still gets its stream
    for _ in range(live.MAX_STREAMS_PER_CAB_LINK - 1):
        assert hub.open("cab", "link-2")
    assert hub.open("cab", "link-2") and not hub.open("cab", "link-2")  # and one link cannot hoard streams
    hub.close("console", "a")
    assert hub.open("console", "c")


def test_a_cab_link_belongs_to_one_journey_and_revocations_only_widen(client):
    http, twin = client
    from india_rail.railguard import api as rg

    journey = rg._journey(twin, "12001@0")
    assert journey.startswith("12001@20")  # the absolute start date, not the twin's day number
    issued = http.post("/railguard/national/cab/12001@0/token", json={"issued_by": "SCR"}).json()
    assert issued["journey"] == journey and live.cab_token_valid(issued["token"], journey)
    assert not live.cab_token_valid(issued["token"], "12001@2099-01-01")  # the same train another day
    live.revoke(journey, clock=lambda: 4_000_000_000.0)
    live.revoke(journey, clock=lambda: 1.0)  # a later "revoke all" under a clock stepped back never re-validates
    assert live.revocations()["journeys"][journey] == 4_000_000_000_000


def test_revocations_are_replayed_only_from_verified_audit_records(tmp_path):
    import json as _json

    from india_rail.railguard.audit import AuditLog

    folder = tmp_path / "audit"
    import os

    os.environ["RAILGUARD_AUDIT_DIR"] = str(folder)
    try:
        log = AuditLog()
        log.record(0, "CAB_LINK_REVOKED", "SCR", {"run": "1@0", "journey": "1@2026-10-09", "token_id": "ab" * 8})
    finally:
        del os.environ["RAILGUARD_AUDIT_DIR"]
    events = folder / "railguard_events.jsonl"
    forged = {"seq": 9, "type": "CAB_LINK_REVOKED", "at": "2026-10-09T00:00:00+00:00", "hash": "x",
              "details": {"journey": "2@2026-10-09"}}  # fmt: skip
    bad_shape = dict(_json.loads(events.read_text().splitlines()[0]), details="not an object")
    with events.open("a") as handle:
        handle.write(_json.dumps(forged) + "\n" + _json.dumps(bad_shape) + "\n")
    import time as _time

    assert live.load_revocations(events, clock=_time.time) == 1  # the real record only; nothing crashes
    assert "ab" * 8 in live.revocations()["ids"]
