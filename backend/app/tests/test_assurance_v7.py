from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

# Register the full relationship graph for isolated test collection.
import app.models.consist  # noqa: F401
from app.api.v1.assurance import _authorized_attestation_role, _owned_case
from app.main import app
from app.models.assurance import AssuranceCase, AssuranceFinding, AssuranceSnapshot, ReviewReceipt
from app.models.provenance import DataSource, LineageEdge, ProvenanceRecord
from app.services.assurance import (
    POLICIES,
    assess_case_evidence,
    seal_receipt,
    seal_snapshot,
    verify_receipt,
    verify_snapshot,
)
from app.services.provenance import record_integrity_payload, stable_checksum


NOW = datetime(2026, 9, 15, 10, tzinfo=timezone.utc)


def _case(*, required_roles: list[str] | None = None) -> AssuranceCase:
    return AssuranceCase(
        id=uuid4(),
        user_id="owner-a",
        title="Train observation evidence",
        purpose="Determine whether stored evidence is suitable for qualified human review.",
        subject_type="TRAIN_OBSERVATION",
        subject_key="public-feed:trip-42",
        context_json={"service_date": "2026-09-15"},
        required_roles=required_roles or ["OBSERVATION"],
        policy_key="GENERIC_PROVENANCE_V1",
        policy_version="1.0.0",
        status="OPEN",
        created_at=NOW,
        updated_at=NOW,
    )


def _source() -> DataSource:
    return DataSource(
        id=uuid4(),
        key="official_public_feed",
        display_name="Official public railway feed",
        category="rail_timetable",
        reference_url="https://data.example.test/rail",
        license_name="Open data licence",
        authority_level="OFFICIAL_PROVIDER",
        official=True,
        free_for_mvp=True,
        requires_key=False,
        enabled=True,
        limitations={},
    )


def _record(
    case: AssuranceCase,
    source: DataSource,
    *,
    role: str = "OBSERVATION",
    source_type: str = "LIVE_PROVIDER",
    value: dict | None = None,
) -> ProvenanceRecord:
    record = ProvenanceRecord(
        id=uuid4(),
        user_id="owner-a",
        route_id=None,
        decision_snapshot_id=None,
        source_id=source.id,
        entity_type="TRAIN_TRIP",
        entity_key="public-feed:trip-42",
        decision_input_role=role,
        canonical_source_type=source_type,
        raw_source_state="AUTHENTICATED_CONNECTOR",
        observed_at=NOW - timedelta(minutes=1),
        fetched_at=NOW,
        valid_until=NOW + timedelta(minutes=10),
        freshness_state="FRESH",
        freshness_seconds=60,
        cache_hit=False,
        used_in_decision=True,
        excluded_reason=None,
        availability_state="AVAILABLE",
        confidence=1,
        completeness=1,
        transform_name=None,
        transform_version=None,
        formula_reference=None,
        request_id=None,
        checksum=stable_checksum(value or {"delay_seconds": 30}),
        value_summary=value or {"delay_seconds": 30},
        metadata_json={
            "connector_authenticated": True,
            "assurance_subject_type": case.subject_type,
            "assurance_subject_key": case.subject_key,
            "assurance_context_checksum": stable_checksum(case.context_json),
        },
        created_at=NOW,
    )
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))
    return record


def test_valid_attributable_evidence_is_reviewable() -> None:
    case = _case()
    source = _source()
    record = _record(case, source)

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "REVIEWABLE"
    assert result.findings == ()
    assert result.matrix["roles"][0]["status"] == "PASS"
    assert result.metrics["satisfied_required_role_count"] == 1


@pytest.mark.parametrize(
    "metadata_key",
    ["assurance_subject_type", "assurance_subject_key", "assurance_context_checksum"],
)
def test_subject_and_context_binding_is_mandatory(metadata_key: str) -> None:
    case = _case()
    source = _source()
    record = _record(case, source)
    record.metadata_json.pop(metadata_key)
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "HOLD"
    assert "EVIDENCE_CONTEXT_MISMATCH" in {item.code for item in result.findings}


def test_context_checksum_must_match_the_exact_case_context() -> None:
    case = _case()
    source = _source()
    record = _record(case, source)
    record.metadata_json["assurance_context_checksum"] = stable_checksum(
        {"service_date": "2026-09-16"}
    )
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "HOLD"
    assert "EVIDENCE_CONTEXT_MISMATCH" in {item.code for item in result.findings}


def test_required_operator_declaration_cannot_be_reviewable() -> None:
    case = _case()
    source = _source()
    record = _record(case, source, source_type="OPERATOR_INPUT")
    record.raw_source_state = "USER_DECLARED_OPERATOR_INPUT"
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    declaration = next(item for item in result.findings if item.code == "SOURCE_USER_DECLARED")
    assert result.state == "HOLD"
    assert declaration.severity == "ERROR"


def test_unsupported_source_type_is_rejected() -> None:
    case = _case()
    source = _source()
    record = _record(case, source)
    record.canonical_source_type = "SIMULATED"
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "HOLD"
    assert "EVIDENCE_SOURCE_TYPE_UNSUPPORTED" in {item.code for item in result.findings}


def test_excluded_record_cannot_satisfy_a_required_role() -> None:
    case = _case()
    source = _source()
    record = _record(case, source)
    record.used_in_decision = False
    record.excluded_reason = "NOT_SELECTED_FOR_REVIEW"
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "HOLD"
    assert "EVIDENCE_EXCLUDED" in {item.code for item in result.findings}


def test_source_identifier_must_match_the_supplied_catalog_row() -> None:
    case = _case()
    source = _source()
    record = _record(case, source)
    record.source_id = uuid4()
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "HOLD"
    assert "SOURCE_ID_MISMATCH" in {item.code for item in result.findings}


def test_source_freshness_policy_cannot_be_extended_by_valid_until() -> None:
    case = _case()
    source = _source()
    source.stale_after_seconds = 60
    record = _record(case, source)
    record.observed_at = NOW - timedelta(minutes=5)
    record.freshness_seconds = 300
    record.valid_until = NOW + timedelta(hours=1)
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    finding = next(item for item in result.findings if item.code == "EVIDENCE_EXPIRED")
    assert result.state == "HOLD"
    assert "source freshness policy" in finding.message


def test_browser_declared_provider_label_cannot_be_reviewable() -> None:
    case = _case()
    source = _source()
    record = _record(case, source)
    record.raw_source_state = "ASSURANCE_CASE_CAPTURE"
    record.metadata_json = {}
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "HOLD"
    assert "SOURCE_AUTHENTICITY_UNVERIFIED" in {item.code for item in result.findings}


def test_empty_case_is_unavailable_and_names_missing_role() -> None:
    result = assess_case_evidence(_case(), [], [], now=NOW)

    assert result.state == "UNAVAILABLE"
    assert {item.code for item in result.findings} == {"REQUIRED_ROLE_MISSING"}
    assert result.matrix["roles"][0]["status"] == "MISSING"


def test_tampering_is_fail_closed_even_when_original_checksum_remains() -> None:
    case = _case()
    source = _source()
    record = _record(case, source)
    record.value_summary["delay_seconds"] = 900

    result = assess_case_evidence(case, [(record, source, "OBSERVATION", True)], [], now=NOW)

    assert result.state == "HOLD"
    assert "EVIDENCE_INTEGRITY_INVALID" in {item.code for item in result.findings}


def test_derived_evidence_requires_an_in_case_parent() -> None:
    case = _case(required_roles=["ASSESSMENT"])
    source = _source()
    derived = _record(case, source, role="ASSESSMENT", source_type="DERIVED")

    missing = assess_case_evidence(case, [(derived, source, "ASSESSMENT", True)], [], now=NOW)
    assert missing.state == "HOLD"
    assert "DERIVED_LINEAGE_MISSING" in {item.code for item in missing.findings}

    parent = _record(case, source, role="INPUT")
    edge = LineageEdge(
        id=uuid4(),
        parent_record_id=parent.id,
        child_record_id=derived.id,
        relationship="DERIVED_FROM",
        created_at=NOW,
    )
    present = assess_case_evidence(
        case,
        [(derived, source, "ASSESSMENT", True), (parent, source, "INPUT", False)],
        [edge],
        now=NOW,
    )
    assert present.state == "REVIEWABLE"


def test_derived_evidence_rejects_unlinked_parent_and_cycles() -> None:
    case = _case(required_roles=["ASSESSMENT"])
    source = _source()
    parent = _record(case, source, role="INPUT", source_type="DERIVED")
    child = _record(case, source, role="ASSESSMENT", source_type="DERIVED")
    external_id = uuid4()
    incomplete = LineageEdge(
        id=uuid4(),
        parent_record_id=external_id,
        child_record_id=child.id,
        relationship="DERIVED_FROM",
        created_at=NOW,
    )
    missing = assess_case_evidence(
        case,
        [(child, source, "ASSESSMENT", True)],
        [incomplete],
        now=NOW,
    )
    assert missing.state == "HOLD"
    assert "DERIVED_LINEAGE_INCOMPLETE" in {item.code for item in missing.findings}

    edges = [
        LineageEdge(
            id=uuid4(),
            parent_record_id=parent.id,
            child_record_id=child.id,
            relationship="DERIVED_FROM",
            created_at=NOW,
        ),
        LineageEdge(
            id=uuid4(),
            parent_record_id=child.id,
            child_record_id=parent.id,
            relationship="DERIVED_FROM",
            created_at=NOW,
        ),
    ]
    cyclic = assess_case_evidence(
        case,
        [(child, source, "ASSESSMENT", True), (parent, source, "INPUT", False)],
        edges,
        now=NOW,
    )
    assert cyclic.state == "HOLD"
    assert "DERIVED_LINEAGE_CYCLE" in {item.code for item in cyclic.findings}


def test_reverse_order_deep_lineage_propagates_optional_parent_failure() -> None:
    case = _case(required_roles=["FINAL"])
    source = _source()
    bad_optional_parent = _record(case, source, role="RAW_INPUT")
    bad_optional_parent.completeness = 0.25
    bad_optional_parent.integrity_checksum = stable_checksum(
        record_integrity_payload(bad_optional_parent)
    )
    intermediate = _record(case, source, role="INTERMEDIATE", source_type="DERIVED")
    final = _record(case, source, role="FINAL", source_type="DERIVED")
    edges = [
        LineageEdge(
            id=uuid4(),
            parent_record_id=bad_optional_parent.id,
            child_record_id=intermediate.id,
            relationship="DERIVED_FROM",
            created_at=NOW,
        ),
        LineageEdge(
            id=uuid4(),
            parent_record_id=intermediate.id,
            child_record_id=final.id,
            relationship="DERIVED_FROM",
            created_at=NOW,
        ),
    ]

    result = assess_case_evidence(
        case,
        [
            (final, source, "FINAL", True),
            (intermediate, source, "INTERMEDIATE", False),
            (bad_optional_parent, source, "RAW_INPUT", False),
        ],
        list(reversed(edges)),
        now=NOW,
    )

    final_finding = next(
        item
        for item in result.findings
        if item.code == "DERIVED_LINEAGE_INVALID" and item.record_ids == (str(final.id),)
    )
    assert result.state == "HOLD"
    assert final_finding.severity == "ERROR"
    assert set(final_finding.details["invalid_ancestor_record_ids"]) == {
        str(bad_optional_parent.id),
        str(intermediate.id),
    }


def test_cycle_detection_is_iterative_beyond_python_recursion_depth() -> None:
    case = _case(required_roles=["FINAL"])
    source = _source()
    records = [
        _record(
            case,
            source,
            role="FINAL" if index == 1_049 else "CHAIN_INPUT",
            source_type="DERIVED",
        )
        for index in range(1_050)
    ]
    edges = [
        LineageEdge(
            id=uuid4(),
            parent_record_id=records[index - 1].id,
            child_record_id=records[index].id,
            relationship="DERIVED_FROM",
            created_at=NOW,
        )
        for index in range(1, len(records))
    ]
    edges.append(
        LineageEdge(
            id=uuid4(),
            parent_record_id=records[-1].id,
            child_record_id=records[0].id,
            relationship="DERIVED_FROM",
            created_at=NOW,
        )
    )
    evidence = [
        (
            record,
            source,
            "FINAL" if index == len(records) - 1 else "CHAIN_INPUT",
            index == len(records) - 1,
        )
        for index, record in reversed(list(enumerate(records)))
    ]

    result = assess_case_evidence(case, evidence, list(reversed(edges)), now=NOW)

    assert result.state == "HOLD"
    assert any(
        item.code == "DERIVED_LINEAGE_CYCLE"
        and item.record_ids == (str(records[-1].id),)
        and item.severity == "ERROR"
        for item in result.findings
    )


def test_conflicting_assertions_cannot_be_reviewable() -> None:
    case = _case()
    source = _source()
    first = _record(case, source, value={"delay_seconds": 30})
    second = _record(case, source, value={"delay_seconds": 600})

    result = assess_case_evidence(
        case,
        [
            (first, source, "OBSERVATION", True),
            (second, source, "OBSERVATION", True),
        ],
        [],
        now=NOW,
    )

    assert result.state == "HOLD"
    assert "EVIDENCE_CONFLICT" in {item.code for item in result.findings}


def _sealed_snapshot() -> tuple[AssuranceCase, AssuranceSnapshot, list[AssuranceFinding]]:
    case = _case()
    snapshot = AssuranceSnapshot(
        id=uuid4(),
        case_id=case.id,
        user_id=case.user_id,
        sequence_no=1,
        decision_state="REVIEWABLE",
        policy_key=case.policy_key,
        policy_version=case.policy_version,
        evidence_manifest=[],
        matrix_json={"roles": []},
        metrics_json={"evidence_record_count": 0},
        bundle_checksum="0" * 64,
        bundle_signature="0" * 64,
        signing_key_id="pending",
        signing_algorithm="HMAC-SHA256",
        assessed_at=NOW,
        created_at=NOW,
    )
    finding = AssuranceFinding(
        id=uuid4(),
        case_id=case.id,
        snapshot_id=snapshot.id,
        code="POLICY_PASSED",
        severity="INFO",
        message="Policy evaluation completed.",
        evidence_record_ids=[],
        details_json={},
        created_at=NOW,
    )
    seal_snapshot(case, snapshot, [finding])
    return case, snapshot, [finding]


def test_snapshot_and_review_receipt_detect_tampering() -> None:
    case, snapshot, findings = _sealed_snapshot()
    assert verify_snapshot(case, snapshot, findings)[:2] == (True, True)

    receipt = ReviewReceipt(
        id=uuid4(),
        case_id=case.id,
        snapshot_id=snapshot.id,
        reviewer_id=case.user_id,
        reviewer_role="approver",
        outcome="ATTESTED",
        statement="Qualified reviewer inspected the stored evidence and findings.",
        snapshot_checksum=snapshot.bundle_checksum,
        receipt_checksum="0" * 64,
        receipt_signature="0" * 64,
        signing_key_id="pending",
        signing_algorithm="HMAC-SHA256",
        reviewed_at=NOW,
        created_at=NOW,
    )
    seal_receipt(receipt)
    assert verify_receipt(receipt) is True

    receipt.statement = "Tampered statement"
    assert verify_receipt(receipt) is False
    snapshot.metrics_json["evidence_record_count"] = 999
    assert verify_snapshot(case, snapshot, findings)[:2] == (False, False)


@pytest.mark.asyncio
async def test_case_lookup_is_owner_scoped_and_non_disclosing() -> None:
    class Session:
        statement = None

        async def scalar(self, statement):
            self.statement = statement
            return None

    session = Session()
    with pytest.raises(HTTPException) as exc:
        await _owned_case(session, uuid4(), "owner-a")  # type: ignore[arg-type]
    assert exc.value.status_code == 404
    assert "user_id" in str(session.statement)
    assert "owner-a" in session.statement.compile().params.values()


def test_policy_contract_states_non_vital_limitations() -> None:
    policy = POLICIES["GENERIC_PROVENANCE_V1"]
    limitations = " ".join(policy["limitations"]).lower()
    assert "movement authority" in limitations
    assert "driver" in limitations


def test_attestation_requires_a_current_authorized_role() -> None:
    assert _authorized_attestation_role("approver") is True
    assert _authorized_attestation_role("viewer") is False


def test_v7_vertical_slice_is_exposed_without_route_identifiers() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/assurance/policies",
        "/api/v1/assurance/cases",
        "/api/v1/assurance/cases/{case_id}",
        "/api/v1/assurance/cases/{case_id}/evidence",
        "/api/v1/assurance/cases/{case_id}/evidence-links",
        "/api/v1/assurance/cases/{case_id}/assessments",
        "/api/v1/assurance/cases/{case_id}/assessments/{snapshot_id}",
        "/api/v1/assurance/cases/{case_id}/matrix",
        "/api/v1/assurance/cases/{case_id}/timeline",
        "/api/v1/assurance/cases/{case_id}/bundle",
        "/api/v1/assurance/cases/{case_id}/review-receipts",
        "/api/v1/assurance/cases/{case_id}/verify",
    }
    assert expected <= paths.keys()
    assert all("route_id" not in path for path in expected)
