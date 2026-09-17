from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import assurance as api
from app.core.security import CurrentUser
from app.schemas.assurance import AssuranceVerifyRequest, ReviewReceiptCreate
from app.services.assurance import seal_snapshot, source_integrity_payload
from app.services.assurance_integrity import lineage_payload
from app.services.provenance import stable_checksum
from app.tests.test_assurance_v7 import _record, _sealed_snapshot, _source


def _user(identifier="reviewer", role="approver"):
    return CurrentUser(id=identifier, email=None, role=role, claims={})


def _review_setup(monkeypatch):
    case, snapshot, findings = _sealed_snapshot()
    case.assigned_reviewer_id = "reviewer"
    case.status = "ASSESSED"
    monkeypatch.setattr(api, "_accessible_case", AsyncMock(return_value=case))
    monkeypatch.setattr(api, "_owned_snapshot", AsyncMock(return_value=snapshot))
    monkeypatch.setattr(api, "verify_assurance_bundle", AsyncMock(return_value=SimpleNamespace(verified=True)))
    monkeypatch.setattr(api, "_evidence_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(api, "_lineage", AsyncMock(return_value=[]))
    monkeypatch.setattr(api, "assess_case_evidence", lambda *args: SimpleNamespace(state="REVIEWABLE"))
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), commit=AsyncMock(), added=[])
    db.add = db.added.append
    payload = ReviewReceiptCreate(snapshot_id=snapshot.id, outcome="ATTESTED", statement="Independent reviewer inspected the full evidence.")
    return case, snapshot, db, payload


@pytest.mark.asyncio
@pytest.mark.parametrize("identity,role", [("owner-a", "approver"), ("stranger", "approver"), ("reviewer", "operator")])
async def test_review_rejects_self_unassigned_and_operator(monkeypatch, identity, role):
    case, _, db, payload = _review_setup(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        await api.create_review_receipt(case.id, payload, db, _user(identity, role))
    assert caught.value.status_code == 403
    assert not db.added


@pytest.mark.asyncio
async def test_assigned_approver_can_attest_exact_snapshot(monkeypatch):
    case, snapshot, db, payload = _review_setup(monkeypatch)
    receipt = await api.create_review_receipt(case.id, payload, db, _user())
    assert receipt.reviewer_id != case.user_id
    assert receipt.snapshot_checksum == snapshot.bundle_checksum
    assert case.status == "REVIEWED"
    assert db.commit.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["duplicate", "older", "new_evidence", "corrupt", "expired", "archived"])
async def test_review_rejects_obsolete_or_invalid_snapshot(monkeypatch, reason):
    case, snapshot, db, payload = _review_setup(monkeypatch)
    if reason == "duplicate":
        db.scalar.return_value = object()
    elif reason == "older":
        api._owned_snapshot.side_effect = [snapshot, SimpleNamespace(id=uuid4())]
    elif reason == "new_evidence":
        case.status = "OPEN"
    elif reason == "corrupt":
        api.verify_assurance_bundle.return_value = SimpleNamespace(verified=False)
    elif reason == "expired":
        monkeypatch.setattr(api, "assess_case_evidence", lambda *args: SimpleNamespace(state="HOLD"))
    else:
        case.status = "ARCHIVED"
    with pytest.raises(HTTPException) as caught:
        await api.create_review_receipt(case.id, payload, db, _user())
    assert caught.value.status_code == 409
    assert not db.added


@pytest.mark.asyncio
async def test_returned_review_reopens_case(monkeypatch):
    case, _, db, payload = _review_setup(monkeypatch)
    payload.outcome = "RETURNED"
    await api.create_review_receipt(case.id, payload, db, _user())
    assert case.status == "OPEN"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [None, "checksum", "lineage"])
async def test_verify_checks_stored_checksum_and_lineage(monkeypatch, mutation):
    case, snapshot, findings = _sealed_snapshot()
    case.assigned_reviewer_id = "reviewer"
    source = _source()
    record = _record(case, source)
    snapshot.evidence_manifest = [{
        "record_id": str(record.id), "source_id": str(source.id),
        "integrity_checksum": record.integrity_checksum,
        "source_metadata_checksum": stable_checksum(source_integrity_payload(source)),
        "lineage_checksum": stable_checksum(lineage_payload([], record.id)),
    }]
    seal_snapshot(case, snapshot, findings)
    edges = []
    if mutation == "checksum":
        record.integrity_checksum = "f" * 64
    if mutation == "lineage":
        edges = [SimpleNamespace(id=uuid4(), parent_record_id=uuid4(), child_record_id=record.id, relationship="DERIVED_FROM")]
    monkeypatch.setattr(api, "_accessible_case", AsyncMock(return_value=case))
    monkeypatch.setattr(api, "_owned_snapshot", AsyncMock(return_value=snapshot))
    monkeypatch.setattr(api, "_lineage", AsyncMock(return_value=edges))
    monkeypatch.setattr(api, "_review_receipts", AsyncMock(return_value=[]))
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: findings)),
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(record, source)])),
    )
    result = await api.verify_assurance_bundle(case.id, AssuranceVerifyRequest(snapshot_id=snapshot.id), db, _user())
    assert result.verified is (mutation is None)
    assert result.evidence_integrity_valid is (mutation is None)
    query = db.execute.call_args.args[0]
    assert case.user_id in query.compile().params.values()


@pytest.mark.asyncio
async def test_read_acl_limits_visibility_to_owner_or_assigned_reviewer():
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as caught:
        await api._accessible_case(db, uuid4(), "stranger")
    assert caught.value.status_code == 404
    query = str(db.scalar.call_args.args[0])
    assert "assigned_reviewer_id" in query and "user_id" in query
