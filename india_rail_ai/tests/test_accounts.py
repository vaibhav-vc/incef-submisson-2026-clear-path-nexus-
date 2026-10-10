"""Named user accounts: passwords, lockout, sessions, roles, and decisions that carry the person's name."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail import accounts
from india_rail.railguard.national import NationalTwin

GOOD = "signal-green-2026"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "SCRYPT", {**accounts.SCRYPT, "n": 2**10})  # fast hashing for tests only
    path = tmp_path / "accounts.sqlite"
    monkeypatch.setenv("RAILGUARD_ACCOUNTS_DB", str(path))
    now = [1_000_000.0]
    s = accounts.Accounts(path, clock=lambda: now[0])
    s.add("admin.k", "K. Admin", "admin", GOOD + "a", must_change=False)
    s.add("sharma.r", "R. Sharma", "controller", GOOD, must_change=False)
    s.add("screen.1", "Screen One", "viewer", GOOD + "v", must_change=False)
    accounts._ACCOUNTS = s
    yield s, now
    accounts._ACCOUNTS = None


def test_password_policy_and_hashing(store):
    s, _ = store
    for bad in ("short", "new.user-is-me-123", "password1234"):  # too short, contains the name, common
        with pytest.raises(ValueError, match="password"):
            s.add("new.user", "New", "viewer", bad)
    row = sqlite3.connect(s.path).execute("SELECT pw_hash FROM users WHERE username='sharma.r'").fetchone()
    assert GOOD.encode() not in row[0] and len(row[0]) == 32


def test_lockout_after_five_failures_and_same_answer_for_unknown_users(store):
    s, now = store
    for _ in range(accounts.MAX_FAILURES):
        with pytest.raises(accounts.AuthError, match="wrong user name or password"):
            s.login("sharma.r", "not-the-password")
    with pytest.raises(accounts.AuthError, match="locked"):
        s.login("sharma.r", GOOD)  # even the right password while locked
    now[0] += accounts.LOCK_MINUTES * 60 + 1
    assert s.login("sharma.r", GOOD)["role"] == "controller"
    with pytest.raises(accounts.AuthError, match="wrong user name or password"):
        s.login("nobody.here", GOOD)


def test_sessions_expire_idle_and_are_stored_hashed(store):
    s, now = store
    token = s.login("sharma.r", GOOD)["token"]
    assert s.session(token)["username"] == "sharma.r"
    stored = sqlite3.connect(s.path).execute("SELECT token_sha256 FROM sessions").fetchall()
    assert all(token not in r[0] for r in stored)
    now[0] += accounts.IDLE_MINUTES * 60 + 1
    assert s.session(token) is None  # idle too long
    token = s.login("sharma.r", GOOD)["token"]
    s.set_disabled("sharma.r", True)
    assert s.session(token) is None  # disabling ends every session


def test_api_roles_and_named_decisions(store, data, monkeypatch):  # noqa: F811
    from india_rail import api
    from india_rail.railguard import api as rg

    twin = NationalTwin(data, start_min=615.0)
    monkeypatch.setattr(rg, "_national", lambda: twin)
    monkeypatch.setenv("RAILGUARD_VIEWER_TOKEN", "v" * 40)
    monkeypatch.setenv("RAILGUARD_CONTROLLER_TOKEN", "c" * 40)  # the shared token exists...
    monkeypatch.setenv("RAILGUARD_REQUIRE_ACCOUNTS", "1")  # ...but decisions need a person
    http = TestClient(api.app)
    assert http.post("/auth/login", json={"username": "sharma.r", "password": "nope-nope-nope"}).status_code == 401
    token = http.post("/auth/login", json={"username": "sharma.r", "password": GOOD}).json()["token"]
    me = {"Authorization": f"Bearer {token}"}
    shared = {"Authorization": "Bearer " + "c" * 40}
    body = {"run": "12001@0", "station": "C", "delay_min": 6}
    assert http.post("/railguard/national/disrupt", json=body, headers=shared).status_code == 403
    assert http.post("/railguard/national/disrupt", json=body, headers=me).status_code == 200
    assert any(e["actor"] == "R. Sharma (sharma.r)" for e in twin.audit.events)
    viewer = http.post("/auth/login", json={"username": "screen.1", "password": GOOD + "v"}).json()["token"]
    assert http.post("/railguard/national/disrupt", json=body,
                     headers={"Authorization": f"Bearer {viewer}"}).status_code == 403  # fmt: skip
    assert http.get("/auth/users", headers=me).status_code == 403  # a controller is not an administrator
    admin = http.post("/auth/login", json={"username": "admin.k", "password": GOOD + "a"}).json()["token"]
    adm = {"Authorization": f"Bearer {admin}"}
    user = {"username": "verma.p", "display_name": "P. Verma", "role": "controller", "initial_password": GOOD + "x"}
    created = http.post("/auth/users", headers=adm, json=user)
    assert created.status_code == 200
    first = http.post("/auth/login", json={"username": "verma.p", "password": GOOD + "x"}).json()
    assert first["must_change_password"]
    new = {"Authorization": f"Bearer {first['token']}"}
    assert http.post("/railguard/national/disrupt", json=body, headers=new).status_code == 403  # change it first
    change = {"old_password": GOOD + "x", "new_password": "verma-own-pass-77"}
    assert http.post("/auth/password", headers=new, json=change).status_code == 200
    assert http.get("/auth/me", headers=new).status_code == 403  # the password change ended the session
    http.post("/auth/logout", headers=me)
    assert http.get("/auth/me", headers=me).status_code == 403
    assert all("password" not in str(e["details"]).lower() for e in twin.audit.events)
