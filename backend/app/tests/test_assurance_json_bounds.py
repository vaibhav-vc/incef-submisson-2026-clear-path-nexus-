"""Adversarial transport-boundary tests; fixtures are not operational data."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.assurance import (
    AssuranceCaseCreate,
    AssuranceEvidenceCreate,
    AssuranceEvidenceLinkCreate,
)
from app.schemas.bounded_json import (
    MAX_JSON_BYTES,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    bounded_json_object,
)


def case(**updates):
    return AssuranceCaseCreate(**{
        "title": "Fixture", "purpose": "Validation test fixture only",
        "subject_type": "TEST", "subject_key": "fixture", "required_roles": ["source"],
        **updates,
    })


def evidence(**updates):
    now = datetime.now(timezone.utc)
    return AssuranceEvidenceCreate(**{
        "source_id": uuid4(), "evidence_role": "source", "entity_type": "TEST",
        "entity_key": "fixture", "canonical_source_type": "OPERATOR_INPUT",
        "observed_at": now, "fetched_at": now, "freshness_state": "FRESH",
        "availability_state": "AVAILABLE", "completeness": 1,
        "value_summary": {"description": "fixture"}, **updates,
    })


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["context", "value_summary", "metadata"])
def test_nonfinite_nested_values_are_rejected(number, field):
    make = case if field == "context" else evidence
    with pytest.raises(ValidationError, match="must be finite"):
        make(**{field: {"nested": [{"number": number}]}})


def test_valid_payload_is_preserved_without_coercion():
    payload = {"unicode": "रेल", "array": [None, True, False, -3, 1.5, {}, []]}
    assert case(context=payload).context == payload
    assert evidence(value_summary=payload, metadata=payload).value_summary == payload


def test_exact_encoded_byte_limit_including_punctuation():
    payload = {"x": "a" * (MAX_JSON_BYTES - len('{"x":""}'))}
    assert len(json.dumps(payload, separators=(",", ":")).encode()) == MAX_JSON_BYTES
    assert bounded_json_object(payload) == payload
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        bounded_json_object({"x": payload["x"] + "a"})


@pytest.mark.parametrize("text", ["रेल" * 9000, "\n" * 33000], ids=["unicode", "escaped-newlines"])
def test_byte_limit_counts_unicode_and_json_escapes(text):
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        case(context={"value": text})


def test_depth_boundary_and_extremely_deep_input():
    payload = {}
    for _ in range(MAX_JSON_DEPTH):
        payload = {"x": payload}
    assert bounded_json_object(payload) == payload
    with pytest.raises(ValueError, match="depth"):
        bounded_json_object({"x": payload})
    for _ in range(2000):
        payload = {"x": payload}
    with pytest.raises(ValueError, match="depth"):
        bounded_json_object(payload)


def test_node_boundary_includes_object_keys():
    payload = {"x": [None] * (MAX_JSON_NODES - 3)}
    assert bounded_json_object(payload) == payload
    with pytest.raises(ValueError, match="nodes"):
        bounded_json_object({"x": [None] * (MAX_JSON_NODES - 2)})


@pytest.mark.parametrize("payload", [{1: "bad"}, {"x": {1, 2}}, {"x": b"bytes"}, {"x": "\ud800"}])
def test_non_json_values_are_rejected(payload):
    with pytest.raises(ValueError):
        bounded_json_object(payload)


def test_cycles_rejected_but_shared_subobjects_allowed():
    shared = {"x": 1}
    assert bounded_json_object({"a": shared, "b": shared}) == {"a": shared, "b": shared}
    shared["self"] = shared
    with pytest.raises(ValueError, match="cycles"):
        bounded_json_object(shared)


@pytest.mark.parametrize("role", ["a" * 81, "ß" * 41])
def test_roles_cannot_exceed_limit_after_normalization(role):
    with pytest.raises(ValidationError):
        case(required_roles=[role])
    with pytest.raises(ValidationError):
        evidence(evidence_role=role)
    with pytest.raises(ValidationError):
        AssuranceEvidenceLinkCreate(record_id=uuid4(), evidence_role=role)


def test_role_normalization_preserves_valid_boundary():
    assert case(required_roles=["ß" * 40]).required_roles == ["SS" * 40]
    assert evidence(evidence_role=" source ").evidence_role == "SOURCE"
    assert AssuranceEvidenceLinkCreate(record_id=uuid4(), evidence_role=" source ").evidence_role == "SOURCE"
