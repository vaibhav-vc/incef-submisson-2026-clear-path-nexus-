"""Adversarial tests: what an attacker on the network would try against the HTTP service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from india_rail import security
from india_rail.api import app
from india_rail.railguard import api as railguard_api
from india_rail.railguard.engine import RailGuardEngine

TOKENS = {"viewer": "v" * 40, "controller": "c" * 40, "feed": "f" * 40}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("RAILGUARD_MODE", "production")
    monkeypatch.setenv("RAILGUARD_RATE_LIMIT", "off")
    monkeypatch.setenv("RAILGUARD_ALLOWED_HOSTS", "testserver")
    for role, env in security.ROLE_ENV.items():
        monkeypatch.setenv(env, TOKENS[role])
    monkeypatch.setattr(railguard_api, "ENGINE", RailGuardEngine())
    return TestClient(app, raise_server_exceptions=False)


CONTROL = {"Authorization": f"Bearer {TOKENS['controller']}"}


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Basic {TOKENS['controller']}"},
        {"Authorization": f"Bearer {TOKENS['controller'][:-1]}"},  # prefix of the real token
        {"Authorization": f"Bearer {TOKENS['controller']}x"},  # real token plus suffix
        {"Authorization": f"Bearer {TOKENS['viewer']}"},  # wrong role
        {"Authorization": f"Bearer {TOKENS['feed']}"},
        {"X-Controller-Token": TOKENS["viewer"]},
        {"Authorization": ("Bearer " + chr(0x441) * 40).encode()},  # look-alike Cyrillic, raw UTF-8 bytes
    ],
)
def test_auth_bypass_attempts_fail(client, headers):
    assert client.post("/railguard/tick", json={"seconds": 1}, headers=headers).status_code == 403


def test_token_in_query_string_is_ignored(client):
    url = f"/railguard/tick?token={TOKENS['controller']}&access_token={TOKENS['controller']}"
    assert client.post(url, json={"seconds": 1}).status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/railguard/static/../../security.py",
        "/railguard/static/%2e%2e/%2e%2e/security.py",
        "/railguard/static/..%2f..%2fsecurity.py",
        "/railguard/static/%2e%2e%2f%2e%2e%2fapi.py",
        "/railguard/static//etc/passwd",
    ],
)
def test_static_path_traversal_is_contained(client, path):
    response = client.get(path)
    assert response.status_code in (400, 404) and b"def " not in response.content and b"root:" not in response.content


@pytest.mark.parametrize(
    "body",
    [
        '{"seconds": NaN}',
        '{"seconds": Infinity}',
        '{"seconds": -Infinity}',
        '{"seconds": 1e400}',
        '{"seconds": "5"}',
        '{"seconds": true}',
        '{"seconds": 5.5}',
        '{"seconds": 5, "t": 0}',  # unknown fields are refused, not ignored
    ],
)
def test_non_finite_and_mistyped_numbers_never_reach_the_clock(client, body):
    before = railguard_api.ENGINE.t
    headers = {**CONTROL, "Content-Type": "application/json"}
    response = client.post("/railguard/tick", content=body, headers=headers)
    assert response.status_code == 422 and "NaN" not in response.text and "Infinity" not in response.text
    assert railguard_api.ENGINE.t == before


def test_json_bomb_is_a_client_error_not_a_crash(client):
    depth = 30_000  # 60 KB: under the body cap, far beyond the parser's recursion limit
    response = client.post(
        "/railguard/tick", content="[" * depth + "]" * depth, headers={**CONTROL, "Content-Type": "application/json"}
    )
    assert 400 <= response.status_code < 500


@pytest.mark.parametrize("value", ["1' OR '1'='1", "1; DROP TABLE trains;--", "../../etc/passwd", "<script>x</script>"])
def test_injection_strings_in_identifiers_are_rejected_or_inert(client, value):
    viewer = {"Authorization": f"Bearer {TOKENS['viewer']}"}
    for path in (f"/railguard/cab/{value}", f"/railguard/audit/{value}", f"/railguard/national/runs/{value}"):
        response = client.get(path, headers=viewer)
        assert response.status_code in (404, 422), path
        assert "<script>" not in response.text


def test_controller_name_cannot_carry_markup(client):
    rec = client.post("/railguard/recommend", json={}, headers=CONTROL).json()
    bad = {"snapshot_id": rec["snapshot_id"], "candidate_id": "C1", "controller": "<img src=x onerror=alert(1)>"}
    assert client.post("/railguard/approve", json=bad, headers=CONTROL).status_code == 422


def test_wrong_methods_and_no_cross_origin_grants(client):
    assert client.get("/railguard/approve", headers=CONTROL).status_code == 405
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_errors_do_not_leak_internals(client):
    response = client.post("/railguard/approve", json={"snapshot_id": "SNAP-0001"}, headers=CONTROL)
    assert response.status_code == 422 and "Traceback" not in response.text and "/home/" not in response.text


def test_feed_role_cannot_take_decisions(client):
    feed = {"Authorization": f"Bearer {TOKENS['feed']}"}
    for path, body in [
        ("/railguard/recommend", {}),
        ("/railguard/approve", {"snapshot_id": "SNAP-0001", "candidate_id": "C1", "controller": "x"}),
        ("/railguard/hold", {"controller": "x", "reason": "y"}),
        ("/railguard/console/section", {"section_id": "S03", "condition": 0.1}),
        ("/railguard/national/reset", {}),
    ]:
        assert client.post(path, json=body, headers=feed).status_code == 403, path
