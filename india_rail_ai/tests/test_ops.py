"""Production operations: UPS power via NUT, checkpoints and restore, health, metrics and JSON logs."""

from __future__ import annotations

import json
import logging
import socketserver
import threading
import time
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail.railguard import ops
from india_rail.railguard.livefeed import IST, FeedGateway, FeedSimulator
from india_rail.railguard.national import NationalTwin

UPS = {"ups.status": "OL", "battery.charge": "100", "battery.runtime": "1800"}
KEY = b"k" * 32
DAY = date(2026, 10, 7)
SECRET = bytes(range(32))


class _Nut(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            parts = raw.decode().split()
            if parts[:2] == ["GET", "VAR"] and parts[2] == "rack1":
                name = parts[3]
                reply = f'VAR rack1 {name} "{UPS[name]}"' if name in UPS else "ERR VAR-NOT-SUPPORTED"
                self.wfile.write((reply + "\n").encode())
            elif parts[:1] == ["LOGOUT"]:
                self.wfile.write(b"OK Goodbye\n")
                return
            else:
                self.wfile.write(b"ERR UNKNOWN-UPS\n")


@pytest.fixture()
def nut():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Nut)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    UPS.update({"ups.status": "OL", "battery.charge": "100", "battery.runtime": "1800"})
    yield f"rack1@127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def supervisor(nut, tmp_path, monkeypatch, data):  # noqa: F811
    monkeypatch.setenv("RAILGUARD_UPS", nut)
    monkeypatch.setenv("RAILGUARD_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RAILGUARD_CHECKPOINT_KEY", KEY.decode())
    sup = ops.reset()
    twin = NationalTwin(data, start_min=615.0)
    now = datetime.combine(DAY, datetime.min.time(), IST).timestamp() + 615 * 60
    gateway = FeedGateway(twin, {("RTIS", "k1"): SECRET}, service_date=DAY, clock=lambda: now)
    sup.attach(twin, gateway)
    yield sup
    ops.reset()


def test_power_levels_from_nut(nut):
    client = ops.NutClient.from_spec(nut)
    assert ops.read_power(client).level == "NORMAL"
    UPS["ups.status"] = "OB DISCHRG"
    assert ops.read_power(client).level == "ON_BATTERY"
    UPS["battery.runtime"] = "120"  # on battery with two minutes left
    assert ops.read_power(client).level == "CRITICAL"
    UPS.update({"ups.status": "OB LB", "battery.runtime": "900"})
    assert ops.read_power(client).level == "CRITICAL"
    assert ops.read_power(ops.NutClient("rack1", "127.0.0.1", 1)).level == "MONITOR_LOST"
    assert ops.read_power(None).level == "UNMONITORED"
    with pytest.raises(ValueError):
        ops.NutClient.from_spec("bad name;rm@host")


def test_battery_raises_an_alert_checkpoints_and_low_battery_pauses_approvals(supervisor):
    twin = supervisor.twin
    supervisor.poll_power()
    assert supervisor.power.level == "NORMAL" and not supervisor.read_only
    UPS["ups.status"] = "OB DISCHRG"
    supervisor.poll_power()
    assert "POWER_ON_BATTERY" in {t.type for t in twin.threats.active()}
    assert supervisor.checkpointer.path.exists()  # checkpointed the moment mains was lost
    UPS["ups.status"] = "OB LB"
    supervisor.poll_power()
    assert supervisor.read_only and "POWER_CRITICAL" in {t.type for t in twin.threats.active()}
    from india_rail import api

    client = TestClient(api.app)
    refused = client.post("/railguard/national/disrupt", json={"run": "12001@0", "station": "C", "delay_min": 5})
    assert refused.status_code == 503 and "Power critical" in refused.json()["detail"]
    assert client.get("/health/ready").status_code == 503
    UPS["ups.status"] = "OL CHRG"
    supervisor.poll_power()
    assert not supervisor.read_only and not {t.type for t in twin.threats.active()} & {"POWER_CRITICAL"}
    assert client.get("/health/ready").status_code == 200


def test_checkpoint_restores_state_and_replay_protection_after_a_restart(supervisor, data):  # noqa: F811
    twin, gateway = supervisor.twin, supervisor.gateway
    sim = FeedSimulator(gateway, "RTIS", "k1", SECRET, seed=2)
    envelope = sim.envelope([sim.position_event("12001@0")])
    assert gateway.receive(envelope)["accepted"] == 1
    twin.disrupt("12001@0", "C", 9)
    supervisor.checkpoint("test")

    fresh = NationalTwin(data, start_min=615.0)
    fresh_gateway = FeedGateway(fresh, {("RTIS", "k1"): SECRET}, service_date=DAY, clock=gateway.clock)
    restarted = ops.reset()
    restarted.attach(fresh, fresh_gateway)
    assert fresh.dynamic_state() == twin.dynamic_state()  # plans, evidence, holds: as they were
    assert any(e["type"] == "STATE_RESTORED" for e in fresh.audit.events)
    replay = {**envelope, "nonce": "f" * 32}  # a captured batch replayed after the restart
    with pytest.raises(Exception, match="sequence|signature"):
        fresh_gateway.receive(replay)


def test_a_tampered_stale_or_foreign_checkpoint_is_not_restored(supervisor, data):  # noqa: F811
    supervisor.checkpoint("test")
    cp = supervisor.checkpointer
    assert cp.load(supervisor.twin.data.checksum) is not None
    assert cp.load("other-timetable") is None
    record = json.loads(cp.path.read_text())
    record["state"] = record["state"].replace('"now":615.0', '"now":900.0')
    cp.path.write_text(json.dumps(record))
    assert cp.load(supervisor.twin.data.checksum) is None  # signature no longer holds
    supervisor.checkpoint("test")
    old = ops.Checkpointer(cp.folder, KEY, clock=lambda: cp.last_saved + ops.MAX_RESTORE_AGE_S + 1)
    assert old.load(supervisor.twin.data.checksum) is None
    with pytest.raises(ValueError):
        ops.Checkpointer(cp.folder, b"short")


def test_health_metrics_and_request_ids(supervisor):
    from india_rail import api

    client = TestClient(api.app)
    live = client.get("/health/live")
    assert live.status_code == 200 and len(live.headers["x-request-id"]) == 16
    ready = client.get("/health/ready").json()
    assert ready["ready"] and ready["checks"]["national_twin_loaded"] and ready["power"] == "NORMAL"
    text = client.get("/metrics").text
    assert 'railguard_requests_total{method="GET",route="/health/live",status="200"}' in text
    assert "railguard_twin_ready 1" in text and "railguard_power_level 0" in text


def test_json_access_log_has_route_template_and_no_query(caplog):
    record = logging.LogRecord("railguard.access", logging.INFO, __file__, 1, "request", None, None)
    record.route, record.status, record.ms, record.request_id = "/railguard/national/trains/{number}", 200, 1.2, "ab"
    line = json.loads(ops.JsonFormatter().format(record))
    assert line["route"] == "/railguard/national/trains/{number}" and line["status"] == 200
    assert "token" not in json.dumps(line).lower()


# ---- clock (CERT-In: synchronised with NIC/NPL NTP) --------------------------------------------------------------
def _fake_ntp(offset_s: float, echo: bool = True, stratum: int = 2, leap: int = 0, reply_from: str | None = None):
    """A one-shot SNTP server on localhost whose clock is `offset_s` ahead of ours (`reply_from`: answer from
    another address, as a spoofer would)."""

    import socket as _socket
    import threading as _threading

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))

    def serve():
        request, addr = sock.recvfrom(512)
        now = time.time() + offset_s + ops.NTP_EPOCH_OFFSET
        stamp = int(now).to_bytes(4, "big") + int((now % 1) * 2**32).to_bytes(4, "big")
        reply = bytearray(48)
        reply[0], reply[1] = (leap << 6) | (4 << 3) | 4, stratum
        reply[24:32] = request[40:48] if echo else b"\x00" * 8
        reply[32:40] = reply[40:48] = stamp
        if reply_from:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as other:
                other.bind((reply_from, 0))
                other.sendto(bytes(reply), addr)
        else:
            sock.sendto(bytes(reply), addr)
        sock.close()

    _threading.Thread(target=serve, daemon=True).start()
    return sock.getsockname()[1]


def test_sntp_measures_the_offset_and_refuses_forged_or_unsynchronised_replies():
    assert abs(ops.sntp_offset("127.0.0.1", _fake_ntp(2.5)) - 2.5) < 0.2
    with pytest.raises(OSError, match="echo"):
        ops.sntp_offset("127.0.0.1", _fake_ntp(0.0, echo=False))
    with pytest.raises(OSError, match="not synchronised"):
        ops.sntp_offset("127.0.0.1", _fake_ntp(0.0, leap=3))
    with pytest.raises(OSError, match="not synchronised"):
        ops.sntp_offset("127.0.0.1", _fake_ntp(0.0, stratum=0))
    with pytest.raises(OSError):  # an echoing reply from another address never reaches the client
        ops.sntp_offset("127.0.0.1", _fake_ntp(3599.0, reply_from="127.0.0.5"), timeout_s=0.5)


def test_one_forged_ntp_reply_cannot_fail_readiness(monkeypatch):
    monkeypatch.setenv("RAILGUARD_NTP", "samay1.nic.in")
    sup = ops.reset()
    sup.check_clock(measure=lambda host: 0.02)
    sup.check_clock(measure=lambda host: 3599.0)  # one reply, one server: not believed yet
    ready = sup.readiness()
    assert ready["checks"]["clock"] is True and any("confirming at the next check" in n for n in ready["notes"])
    sup.check_clock(measure=lambda host: 3599.2)  # measured again: the clock really is off
    assert sup.readiness()["checks"]["clock"] is False
    monkeypatch.setenv("RAILGUARD_NTP", "samay1.nic.in,time.nplindia.org")
    sup = ops.reset()
    sup.check_clock(measure=lambda host: 3599.0 if host == "samay1.nic.in" else 0.01)  # servers disagree
    ready = sup.readiness()
    assert ready["checks"]["clock"] is True and any("disagree" in n for n in ready["notes"])


def test_a_drifting_clock_warns_every_console_and_fails_readiness(monkeypatch, data):  # noqa: F811
    from india_rail.railguard.national import NationalTwin

    twin = NationalTwin(data, start_min=615.0)
    monkeypatch.setenv("RAILGUARD_NTP", "samay1.nic.in,time.nplindia.org")
    sup = ops.reset()
    sup.attach(twin, None)
    sup.check_clock(measure=lambda host: 3.0)
    assert sup.readiness()["checks"]["clock"] is False
    assert any(t.type == "CLOCK_DRIFT" for t in twin.threats.active())
    assert sup.gauges()[0]["clock_offset_seconds"] == 3.0
    sup.check_clock(measure=lambda host: 0.05)
    assert sup.readiness()["checks"]["clock"] is True
    assert not any(t.type == "CLOCK_DRIFT" for t in twin.threats.active())

    def unreachable(host):
        raise OSError("timed out")

    sup.check_clock(measure=unreachable)  # reported, but a last good reading keeps the service in
    ready = sup.readiness()
    assert ready["checks"]["clock"] is True and any("timed out" in n for n in ready["notes"])
