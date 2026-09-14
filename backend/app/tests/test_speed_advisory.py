"""Speed advisory is useful only when every safety-critical input is real and current."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.speed import (
    BrakePerformanceInput,
    SpeedRiskAdvisoryRequest,
    SpeedSourceEvidence,
)
from app.services.speed_advisory import (
    calculate_speed_risk_advisory,
    calculate_stopping_distance_meters,
)


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
CHECKSUM = "a" * 64


def evidence(
    key: str,
    *,
    source_type: str = "AUTHORIZED_FEED",
    authority: str = "AUTHORITATIVE",
    observed: datetime = NOW - timedelta(minutes=2),
    valid_until: datetime = NOW + timedelta(minutes=30),
    checksum: str = CHECKSUM,
) -> SpeedSourceEvidence:
    return SpeedSourceEvidence(
        source_key=key,
        source_type=source_type,
        authority_level=authority,
        source_reference=f"https://rail-authority.example/evidence/{key}",
        observed_at=observed,
        fetched_at=observed + timedelta(seconds=10),
        valid_until=valid_until,
        checksum=checksum,
    )


def complete_payload(**overrides) -> SpeedRiskAdvisoryRequest:
    data = {
        "route_id": uuid4(),
        "corridor_reference": "AUTH-CORRIDOR-01",
        "consist_manifest_checksum": CHECKSUM,
        "evaluation_at": NOW,
        "constraints": [
            {
                "category": "ROUTE_LIMIT",
                "label": "Authorized route limit",
                "limit_kph": 80,
                "evidence": evidence("route_speed_limit"),
            },
            {
                "category": "HEADWAY",
                "label": "Authorized block/headway cap",
                "limit_kph": 65,
                "evidence": evidence("block_headway"),
            },
            {
                "category": "ENVIRONMENT",
                "label": "Current visibility restriction",
                "limit_kph": 70,
                "evidence": evidence(
                    "visibility",
                    source_type="LIVE_PROVIDER",
                    authority="SUPPLEMENTARY",
                ),
            },
        ],
        "braking": {
            "effective_deceleration_mps2": 0.55,
            "reaction_time_seconds": 3,
            "safety_margin_meters": 25,
            "evidence": evidence("brake_test", source_type="IMPORTED_DOCUMENT", checksum=CHECKSUM),
        },
    }
    data.update(overrides)
    return SpeedRiskAdvisoryRequest(**data)


def test_complete_current_authoritative_evidence_returns_advisory():
    result = calculate_speed_risk_advisory(complete_payload())

    assert result.status == "ADVISORY"
    assert result.advisory_speed_kph == 65
    assert result.limiting_constraint == "Authorized block/headway cap"
    assert result.stopping_distance_meters is not None
    assert all(item.source_reference for item in result.evidence)
    assert any(item.freshness == "CURRENT" for item in result.evidence)
    assert "not movement authority" in result.disclaimer


def test_missing_headway_source_withholds_speed():
    payload = complete_payload(
        constraints=[
            {
                "category": "ROUTE_LIMIT",
                "label": "Authorized route limit",
                "limit_kph": 80,
                "evidence": evidence("route_speed_limit"),
            }
        ]
    )

    result = calculate_speed_risk_advisory(payload)

    assert result.status == "HOLD"
    assert result.advisory_speed_kph is None
    assert any("HEADWAY" in warning for warning in result.warnings)


def test_missing_braking_evidence_withholds_speed():
    result = calculate_speed_risk_advisory(complete_payload(braking=None))

    assert result.status == "UNAVAILABLE"
    assert result.advisory_speed_kph is None
    assert any("braking" in warning.lower() for warning in result.warnings)


def test_expired_authoritative_source_withholds_speed():
    expired = NOW - timedelta(minutes=1)
    payload = complete_payload(
        constraints=[
            {
                "category": "ROUTE_LIMIT",
                "label": "Expired route limit",
                "limit_kph": 80,
                "evidence": evidence("route_speed_limit", valid_until=expired),
            },
            {
                "category": "HEADWAY",
                "label": "Expired block/headway cap",
                "limit_kph": 65,
                "evidence": evidence("block_headway", valid_until=expired),
            },
        ],
        braking=complete_payload().braking,
    )

    result = calculate_speed_risk_advisory(payload)

    assert result.status == "HOLD"
    assert result.advisory_speed_kph is None
    assert all(item.freshness == "EXPIRED" or item.category == "BRAKING" for item in result.evidence)


def test_supplementary_environment_data_never_becomes_authoritative_cap():
    payload = complete_payload(
        constraints=[
            {
                "category": "ROUTE_LIMIT",
                "label": "Authorized route limit",
                "limit_kph": 80,
                "evidence": evidence("route_speed_limit"),
            },
            {
                "category": "HEADWAY",
                "label": "Authorized block/headway cap",
                "limit_kph": 65,
                "evidence": evidence("block_headway"),
            },
            {
                "category": "ENVIRONMENT",
                "label": "Weather provider suggestion",
                "limit_kph": 5,
                "evidence": evidence(
                    "open_meteo",
                    source_type="LIVE_PROVIDER",
                    authority="SUPPLEMENTARY",
                ),
            },
        ]
    )

    result = calculate_speed_risk_advisory(payload)

    assert result.advisory_speed_kph == 65
    weather = next(item for item in result.evidence if item.source_key == "open_meteo")
    assert weather.used_in_decision is False
    assert weather.excluded_reason is not None


def test_future_fetched_source_is_not_current():
    future = NOW + timedelta(minutes=1)
    payload = complete_payload(
        constraints=[
            {
                "category": "ROUTE_LIMIT",
                "label": "Future route limit",
                "limit_kph": 80,
                "evidence": evidence("route_speed_limit", observed=future),
            },
            {
                "category": "HEADWAY",
                "label": "Authorized block/headway cap",
                "limit_kph": 65,
                "evidence": evidence("block_headway"),
            },
        ]
    )

    result = calculate_speed_risk_advisory(payload)

    assert result.advisory_speed_kph is None
    assert next(item for item in result.evidence if item.category == "ROUTE_LIMIT").freshness == "FUTURE"


def test_imported_brake_document_requires_checksum():
    with pytest.raises(ValidationError, match="checksum"):
        BrakePerformanceInput(
            effective_deceleration_mps2=0.5,
            reaction_time_seconds=3,
            safety_margin_meters=25,
            evidence={
                "source_key": "brake_test",
                "source_type": "IMPORTED_DOCUMENT",
                "authority_level": "AUTHORITATIVE",
                "source_reference": "https://rail-authority.example/evidence/brake_test",
                "observed_at": NOW,
                "fetched_at": NOW,
                "valid_until": NOW + timedelta(minutes=30),
            },
        )


def test_public_cached_or_operator_data_cannot_claim_authority():
    with pytest.raises(ValidationError, match="cannot be authoritative"):
        evidence("public_schedule", source_type="PUBLIC_OPEN_DATA")
    with pytest.raises(ValidationError, match="cannot be authoritative"):
        evidence("operator_schedule", source_type="OPERATOR_INPUT")


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        complete_payload(evaluation_at=datetime(2026, 9, 14, 12, 0))


def test_stopping_distance_formula_is_transparent():
    assert calculate_stopping_distance_meters(36, 2, 1, 10) == 80
