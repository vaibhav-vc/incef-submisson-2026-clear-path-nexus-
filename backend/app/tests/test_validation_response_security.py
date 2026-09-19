import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.main import app as production_app, request_validation_error
from app.schemas.consist import CarriageLoadCreate


def test_production_registers_safe_validation_handler():
    assert production_app.exception_handlers[RequestValidationError] is request_validation_error


@pytest.mark.parametrize("numeric", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_invalid_nonfinite_body_returns_422_without_reflection(numeric):
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_error)

    @app.post("/carriage")
    def carriage(payload: CarriageLoadCreate):
        raise AssertionError("Invalid input must not reach endpoint")

    with TestClient(app) as client:
        response = client.post(
            "/carriage",
            content='{"length_m":' + numeric + ',"source_reference":"private-input-marker"}',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert "private-input-marker" not in response.text
    assert any(error["loc"] == ["body", "length_m"] for error in response.json()["detail"])
    assert all(set(error) == {"type", "loc", "msg"} for error in response.json()["detail"])


def test_validation_error_response_caps_error_count_and_discards_context():
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_error)

    @app.get("/invalid")
    def invalid():
        raise RequestValidationError([
            {"type": "value_error", "loc": ("body", index), "msg": "Invalid value",
             "input": float("nan"), "ctx": {"error": ValueError("private")}}
            for index in range(100)
        ])

    with TestClient(app) as client:
        response = client.get("/invalid")
    assert response.status_code == 422
    assert len(response.json()["detail"]) == 64
    assert "private" not in response.text
