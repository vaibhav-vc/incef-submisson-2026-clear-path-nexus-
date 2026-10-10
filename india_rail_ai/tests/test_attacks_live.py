"""Attacks on the new surfaces: accounts, cab capabilities, live streams, registry and advisor inputs."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail import accounts
from india_rail.railguard import live
from india_rail.railguard.national import NationalTwin

PASSWORD = "points-normal-2026"


@pytest.fixture()
def http(tmp_path, monkeypatch, data):  # noqa: F811
    from india_rail import api
    from india_rail.railguard import api as rg

    monkeypatch.setattr(accounts, "SCRYPT", {**accounts.SCRYPT, "n": 2**10})
    monkeypatch.setenv("RAILGUARD_ACCOUNTS_DB", str(tmp_path / "accounts.sqlite"))
    monkeypatch.setenv("RAILGUARD_VIEWER_TOKEN", "v" * 40)
    monkeypatch.setenv("RAILGUARD_CONTROLLER_TOKEN", "c" * 40)
    store = accounts.Accounts(tmp_path / "accounts.sqlite")
    store.add("sharma.r", "R. Sharma", "controller", PASSWORD, must_change=False)
    accounts._ACCOUNTS = store
    twin = NationalTwin(data, start_min=615.0)
    monkeypatch.setattr(rg, "_national", lambda: twin)
    yield TestClient(api.app)
    accounts._ACCOUNTS = None


def test_password_guessing_is_rate_limited_and_locks_the_account(http):
    codes = [http.post("/auth/login", json={"username": "sharma.r", "password": f"guess-{i}-xxxxxx"}).status_code
             for i in range(25)]  # fmt: skip
    assert 429 in codes  # the per-address limiter stops a burst
    assert codes.count(401) >= accounts.MAX_FAILURES
    with pytest.raises(accounts.AuthError, match="locked"):
        accounts._ACCOUNTS.login("sharma.r", PASSWORD)  # the account itself is locked too


def test_unknown_and_known_user_failures_look_the_same(http):
    known = http.post("/auth/login", json={"username": "sharma.r", "password": "wrong-password-1"})
    unknown = http.post("/auth/login", json={"username": "nobody.at.all", "password": "wrong-password-1"})
    assert known.status_code == unknown.status_code == 401 and known.json() == unknown.json()


def test_oversized_and_malformed_login_bodies_are_refused(http):
    huge = http.post("/auth/login", content=b'{"username":"a","password":"' + b"x" * 70_000 + b'"}',
                     headers={"Content-Type": "application/json"})  # fmt: skip
    assert huge.status_code == 413
    extra = http.post("/auth/login", json={"username": "sharma.r", "password": PASSWORD, "role": "admin"})
    assert extra.status_code == 422  # unknown fields are not silently accepted
    assert http.post("/auth/login", json={"username": ["x"], "password": PASSWORD}).status_code == 422


def test_forged_expired_or_other_train_cab_tokens_fail(http):
    good = live.issue_cab_token("12001@0", 600)["token"]
    body, mac = good.split(".")
    forged_run = live.issue_cab_token("54001@0", 600)["token"].split(".")[0] + "." + mac
    for token in (forged_run, body + ".", "x" * 300, "", "a.b.c"):
        r = http.get("/railguard/national/cab/12001@0/live", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403
    expired = live.issue_cab_token("12001@0", -1)["token"]
    assert (
        http.get("/railguard/national/cab/12001@0/live", headers={"Authorization": f"Bearer {expired}"}).status_code
        == 403
    )
    # A capability is never taken from the URL (URLs reach access logs and proxies); non-ASCII is refused, not a 500.
    valid = live.issue_cab_token("12001@0", 600)["token"]
    assert http.get(f"/railguard/national/cab/12001@0/live?token={valid}").status_code == 403
    assert (
        http.get("/railguard/national/cab/12001@0/live", headers={"Authorization": "Bearer é.é".encode()}).status_code
        == 403
    )
    # A role token is not a cab capability: a viewer screen cannot read a cab feed it was not issued.
    assert (
        http.get("/railguard/national/cab/12001@0/live", headers={"Authorization": "Bearer " + "v" * 40}).status_code
        == 403
    )


def test_cab_tokens_never_reach_logs_or_the_audit_chain(http, caplog):
    caplog.set_level(logging.INFO, logger="railguard.access")
    issued = http.post("/railguard/national/cab/12001@0/token", json={"issued_by": "SCR"},
                       headers={"Authorization": "Bearer " + "c" * 40}).json()  # fmt: skip
    http.get("/railguard/national/cab/12001@0/live", headers={"Authorization": f"Bearer {issued['token']}"})
    assert issued["token"] not in caplog.text
    from india_rail.railguard import api as rg

    assert issued["token"] not in str(rg._national().audit.events)


@pytest.mark.parametrize("q", ["' OR 1=1 --", "%'; DROP TABLE trains; --", "../../etc/passwd"])
def test_injection_shaped_inputs_are_refused_or_inert(http, q):
    viewer = {"Authorization": "Bearer " + "v" * 40}
    r = http.get("/railguard/national/trains", params={"q": q}, headers=viewer)
    # Refused by the input pattern, or (a plain search text) matched as text by a parameterised query: inert.
    assert r.status_code in (422, 503) or (r.status_code == 200 and r.json()["trains"] == [])
    assert http.get("/railguard/national/advisor/sections;DROP", headers=viewer).status_code in (404, 422)
    assert http.get("/railguard/national/trains/..%2F..%2Fetc/route", headers=viewer).status_code in (404, 422)


def test_a_viewer_session_cannot_issue_cab_capabilities(http):
    accounts._ACCOUNTS.add("screen.2", "Screen", "viewer", PASSWORD + "v", must_change=False)
    token = http.post("/auth/login", json={"username": "screen.2", "password": PASSWORD + "v"}).json()["token"]
    r = http.post("/railguard/national/cab/12001@0/token", json={"issued_by": "me"},
                  headers={"Authorization": f"Bearer {token}"})  # fmt: skip
    assert r.status_code == 403
