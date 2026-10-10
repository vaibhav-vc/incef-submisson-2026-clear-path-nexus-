"""HTTP API behaviour on the miniature network."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from india_rail import api
from india_rail.services import Services


@pytest.fixture()
def client(db_path, tmp_path, monkeypatch):
    services = Services(db_path=db_path, model_path=tmp_path / "missing.joblib")
    monkeypatch.setattr(api, "services", lambda: services)
    return TestClient(api.app)


def test_plan_endpoint(client):
    response = client.post("/plan/disruption", json={"train_number": "54001", "station_code": "AAA", "delay_min": 3})
    assert response.status_code == 200
    assert response.json()["status"] == "PROPOSED_FOR_CONTROLLER_REVIEW"


def test_paid_assistant_refused_by_default(client, monkeypatch):
    monkeypatch.delenv("INDIA_RAIL_ALLOW_PAID_ASSISTANT", raising=False)
    response = client.post("/assistant/ask", json={"question": "hi", "provider": "claude"})
    assert response.status_code == 403


def test_offline_assistant_endpoint(client):
    response = client.post("/assistant/ask", json={"question": "schedule of 12001", "provider": "offline"})
    assert response.status_code == 200
    assert response.json()["provider"] == "offline"
    assert "12001" in response.json()["answer"]
