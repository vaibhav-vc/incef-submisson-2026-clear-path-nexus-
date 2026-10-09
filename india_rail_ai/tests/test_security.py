"""Access control, fail-closed configuration, rate limits and HTTP hardening."""

from __future__ import annotations

import json
import re
import tempfile

import pytest
from fastapi.testclient import TestClient

from india_rail import security
from india_rail.api import app
from india_rail.railguard import api as railguard_api
from india_rail.railguard.audit import AuditLog, verify_events

TOKENS = {"viewer": "v" * 40, "controller": "c" * 40, "feed": "f" * 40}


def bearer(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[role]}"}


@pytest.fixture()
def prod(monkeypatch):
    monkeypatch.setenv("RAILGUARD_MODE", "production")
    monkeypatch.setenv("RAILGUARD_RATE_LIMIT", "off")
    monkeypatch.setenv("RAILGUARD_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("RAILGUARD_AUDIT_DIR", tempfile.mkdtemp(prefix="rg-audit-"))
    for role, env in security.ROLE_ENV.items():
        monkeypatch.setenv(env, TOKENS[role])
    # These tests attack the HTTP layer through the small demo network, which production otherwise disables.
    app.dependency_overrides[railguard_api._demo_network] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.pop(railguard_api._demo_network, None)


def test_production_serves_real_data_only(monkeypatch):
    monkeypatch.setenv("RAILGUARD_MODE", "production")
    monkeypatch.setenv("RAILGUARD_RATE_LIMIT", "off")
    monkeypatch.setenv("RAILGUARD_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("RAILGUARD_AUDIT_DIR", tempfile.mkdtemp(prefix="rg-audit-"))
    for role, env in security.ROLE_ENV.items():
        monkeypatch.setenv(env, TOKENS[role])
    client = TestClient(app)
    assert client.get("/railguard/state", headers=bearer("viewer")).status_code == 404  # made-up demo network
    assert client.post("/railguard/tick", json={"seconds": 1}, headers=bearer("controller")).status_code == 404
    assert client.get("/control").status_code == 404
    assert client.get("/control/national").status_code == 200


def test_production_without_tokens_fails_closed(monkeypatch):
    monkeypatch.setenv("RAILGUARD_MODE", "production")
    for env in security.ROLE_ENV.values():
        monkeypatch.delenv(env, raising=False)
    client = TestClient(app)
    assert client.get("/railguard/state").status_code == 503
    assert client.post("/railguard/tick", json={"seconds": 1}).status_code == 503
    assert client.get("/health").json() == {"status": "misconfigured", "security_configured": False}


def test_production_rejects_short_or_shared_tokens(monkeypatch):
    monkeypatch.setenv("RAILGUARD_MODE", "production")
    monkeypatch.setenv("RAILGUARD_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("RAILGUARD_AUDIT_DIR", tempfile.mkdtemp(prefix="rg-audit-"))
    for env in security.ROLE_ENV.values():
        monkeypatch.setenv(env, "s" * 40)
    assert "role tokens must all differ" in security.configuration_problems()
    monkeypatch.setenv("RAILGUARD_VIEWER_TOKEN", "short")
    assert any("RAILGUARD_VIEWER_TOKEN" in p for p in security.configuration_problems())


def test_roles_are_separated(prod):
    assert prod.get("/health").json()["security_configured"] is True
    assert prod.get("/railguard/state").status_code == 403  # no token
    assert prod.get("/railguard/state", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert prod.get("/railguard/state", headers=bearer("viewer")).status_code == 200
    assert prod.get("/railguard/state", headers=bearer("controller")).status_code == 200
    assert prod.get("/railguard/state", headers=bearer("feed")).status_code == 403  # a feed may not read
    tick = {"seconds": 1}
    assert prod.post("/railguard/tick", json=tick, headers=bearer("viewer")).status_code == 403
    assert prod.post("/railguard/tick", json=tick, headers=bearer("feed")).status_code == 403
    assert prod.post("/railguard/tick", json=tick, headers=bearer("controller")).status_code == 200
    report = {"section_id": "S03", "condition": 0.8}
    assert prod.post("/railguard/tracksense/section", json=report, headers=bearer("controller")).status_code == 403
    assert prod.post("/railguard/tracksense/section", json=report, headers=bearer("feed")).status_code == 200
    assert prod.post("/railguard/console/section", json=report, headers=bearer("feed")).status_code == 403


def test_host_allow_list(prod):
    assert prod.get("/health", headers={"Host": "evil.example"}).status_code == 400


def test_body_limits(prod):
    big = json.dumps({"section_id": "S03", "pad": "x" * (security.MAX_BODY_BYTES + 1)})
    response = prod.post(
        "/railguard/console/section", content=big, headers={**bearer("controller"), "Content-Type": "application/json"}
    )
    assert response.status_code == 413

    def chunks():
        yield b'{"section_id": "S03"}'

    chunked = prod.post("/railguard/console/section", content=chunks(), headers=bearer("controller"))
    assert chunked.status_code == 411


def test_security_headers_on_every_response(prod):
    for response in (prod.get("/health"), prod.get("/railguard/state"), prod.get("/control")):
        assert response.headers["content-security-policy"] == security.CSP
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["strict-transport-security"].startswith("max-age=")
        assert response.headers["cache-control"] == "no-store"


def test_pages_have_no_inline_script_or_style():
    from india_rail.railguard.api import STATIC

    for page in STATIC.glob("*.html"):
        html = page.read_text()
        assert "<script>" not in html and "<style" not in html and " style=" not in html, page.name
        assert not re.search(r"\son[a-z]+=", html), page.name  # no inline event handlers


def test_rate_limit(monkeypatch):
    monkeypatch.setenv("RAILGUARD_RATE_LIMIT", "on")
    monkeypatch.setattr(security, "LIMITER", security.RateLimiter(clock=lambda: 1000.0))  # no refill
    client = TestClient(app)
    burst = int(security.LIMITS["read"][1])
    codes = [client.get("/railguard/state").status_code for _ in range(burst + 5)]
    assert codes[0] == 200 and codes[-1] == 429


def test_rate_limiter_memory_is_bounded():
    limiter = security.RateLimiter(max_clients=10)
    for i in range(100):
        limiter.allow(f"10.0.0.{i}", "read", 1, 1)
    assert len(limiter.buckets) == 10


def test_audit_chain_detects_tampering_and_survives_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("RAILGUARD_AUDIT_DIR", str(tmp_path))
    monkeypatch.setenv("RAILGUARD_AUDIT_KEY", "k" * 40)
    log = AuditLog("t")
    for i in range(3):
        log.record(i, "EVENT", "tester", {"i": i})
    restarted = AuditLog("t")  # a restart continues the same chain
    restarted.record(9, "EVENT", "tester", {"i": 9})
    events = [json.loads(line) for line in (tmp_path / "t_events.jsonl").read_text().splitlines()]
    key = b"k" * 40
    assert [e["seq"] for e in events] == [1, 2, 3, 4] and verify_events(events, key=key)
    events[1]["details"]["i"] = 99
    assert not verify_events(events, key=key)
    events[1]["details"]["i"] = 1
    events[2]["mac"] = "0" * 64  # rewriting without the key is detected
    assert not verify_events(events, key=key)
