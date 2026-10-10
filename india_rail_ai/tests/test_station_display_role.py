"""A public station screen holds a board token: it reads boards and expected times, nothing of the control room."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from india_rail import security
from india_rail.railguard.national import NationalTwin
from tests.test_shared_track import LOCAL, STATIONS, TRAINS, _build

BOARD, VIEWER = "b" * 40, "v" * 40


@pytest.fixture()
def http(tmp_path, monkeypatch):
    from india_rail import api
    from india_rail.railguard import api as rg

    twin = NationalTwin(_build(tmp_path, STATIONS, TRAINS), start_min=590.0)
    monkeypatch.setattr(rg, "_national", lambda: twin)
    monkeypatch.setenv("RAILGUARD_VIEWER_TOKEN", VIEWER)
    monkeypatch.setenv("RAILGUARD_CONTROLLER_TOKEN", "c" * 40)
    monkeypatch.setenv("RAILGUARD_FEED_TOKEN", "f" * 40)
    monkeypatch.setenv("RAILGUARD_BOARD_TOKEN", BOARD)
    return TestClient(api.app)


def _get(http, path, token):
    return http.get(path, headers={"Authorization": f"Bearer {token}"}).status_code


def test_a_board_token_reads_boards_and_expected_times_only(http):
    assert _get(http, "/railguard/national/board/B", BOARD) == 200
    assert _get(http, f"/railguard/national/expected/{LOCAL}", BOARD) == 200
    for path in ("/railguard/national/summary", f"/railguard/national/cab/{LOCAL}", "/railguard/national/positions",
                 "/metrics", "/railguard/national/feed/status", f"/railguard/national/eta/{LOCAL}"):  # fmt: skip
        assert _get(http, path, BOARD) == 403, path
    assert _get(http, "/railguard/national/board/B", VIEWER) == 200  # staff can read boards too
    assert _get(http, "/railguard/national/board/B", "f" * 40) == 403  # a feed device cannot
    assert http.get("/railguard/national/board/B").status_code == 403


def test_a_board_token_must_be_strong_and_distinct_in_production(monkeypatch):
    for env, value in (("RAILGUARD_VIEWER_TOKEN", "v" * 40), ("RAILGUARD_CONTROLLER_TOKEN", "c" * 40),
                       ("RAILGUARD_FEED_TOKEN", "f" * 40)):  # fmt: skip
        monkeypatch.setenv(env, value)
    monkeypatch.setenv("RAILGUARD_MODE", "production")
    monkeypatch.setenv("RAILGUARD_ALLOWED_HOSTS", "railguard.example")
    monkeypatch.setenv("RAILGUARD_AUDIT_DIR", "/tmp/railguard-audit-test")
    monkeypatch.delenv("RAILGUARD_BOARD_TOKEN", raising=False)
    assert security.configuration_problems() == []  # optional
    monkeypatch.setenv("RAILGUARD_BOARD_TOKEN", "short")
    assert any("RAILGUARD_BOARD_TOKEN" in p for p in security.configuration_problems())
    monkeypatch.setenv("RAILGUARD_BOARD_TOKEN", "v" * 40)
    assert "role tokens must all differ" in security.configuration_problems()


def test_the_load_test_refuses_to_run_in_a_production_shell(monkeypatch, capsys):
    from india_rail.railguard import loadtest

    monkeypatch.setenv("RAILGUARD_CAB_KEY", "x" * 40)
    assert loadtest.main(["--seconds", "1"]) == 2
    assert "refusing to run" in capsys.readouterr().err
