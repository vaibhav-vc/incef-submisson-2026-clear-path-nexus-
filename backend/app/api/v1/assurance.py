"""Route-independent, non-vital evidence-assurance API."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user
from app.models.assurance import (
    AssuranceCase,
    AssuranceFinding,
    AssuranceSnapshot,
    CaseEvidenceLink,
    ReviewReceipt,
)
from app.models.provenance import DataSource, LineageEdge, ProvenanceRecord
from app.schemas.assurance import (
    AssuranceAssessmentResponse,
    AssuranceBundleResponse,
    AssuranceCaseCreate,
    AssuranceCaseResponse,
    AssuranceEvidenceCreate,
    AssuranceEvidenceLinkCreate,
    AssuranceEvidenceResponse,
    AssuranceFindingResponse,
    AssurancePolicyResponse,
    AssuranceTimelineEvent,
    AssuranceTimelineResponse,
    AssuranceVerifyRequest,
    AssuranceVerifyResponse,
    EvidenceMatrixItem,
    EvidenceMatrixResponse,
    ReviewReceiptCreate,
    ReviewReceiptResponse,
)
from app.services.assurance import (
    POLICIES,
    assess_case_evidence,
    get_policy,
    receipt_payload,
    seal_receipt,
    seal_snapshot,
    snapshot_manifest_payload,
    source_integrity_payload,
    verify_receipt,
    verify_snapshot,
)
from app.services.assurance_integrity import lineage_payload
from app.services.provenance import redact_metadata, record_integrity_payload, stable_checksum


router = APIRouter(dependencies=[Depends(get_current_user)])


def _authorized_attestation_role(role: str) -> bool:
    allowed_roles = {item.casefold().strip() for item in settings.APPROVAL_ALLOWED_ROLES}
    normalized = role.casefold().strip()
    return normalized in allowed_roles and normalized != "operator"


async def _owned_case(
    db: AsyncSession, case_id: UUID, user_id: str, *, lock: bool = False
) -> AssuranceCase:
    statement = select(AssuranceCase).where(
        AssuranceCase.id == case_id,
        AssuranceCase.user_id == user_id,
    )
    case = await db.scalar(statement.with_for_update() if lock else statement)
    if case is None:
        raise HTTPException(status_code=404, detail="Assurance case not found")
    return case


async def _accessible_case(
    db: AsyncSession, case_id: UUID, user_id: str, *, lock: bool = False
) -> AssuranceCase:
    """Load a case visible to its owner or explicitly assigned reviewer."""

    statement = select(AssuranceCase).where(
        AssuranceCase.id == case_id,
        or_(
            AssuranceCase.user_id == user_id,
            AssuranceCase.assigned_reviewer_id == user_id,
        ),
    )
    case = await db.scalar(statement.with_for_update() if lock else statement)
    if case is None:
        raise HTTPException(status_code=404, detail="Assurance case not found")
    return case


async def _evidence_rows(
    db: AsyncSession, case: AssuranceCase
) -> list[tuple[ProvenanceRecord, DataSource | None, str, bool]]:
    result = await db.execute(
        select(
            ProvenanceRecord,
            DataSource,
            CaseEvidenceLink.evidence_role,
            CaseEvidenceLink.required,
        )
        .join(CaseEvidenceLink, CaseEvidenceLink.record_id == ProvenanceRecord.id)
        .outerjoin(DataSource, DataSource.id == ProvenanceRecord.source_id)
        .where(
            CaseEvidenceLink.case_id == case.id,
            ProvenanceRecord.user_id == case.user_id,
        )
        .order_by(CaseEvidenceLink.created_at, ProvenanceRecord.id)
    )
    return [(row[0], row[1], row[2], row[3]) for row in result.all()]


async def _lineage(db: AsyncSession, record_ids: list[UUID]) -> list[LineageEdge]:
    if not record_ids:
        return []
    return list(
        (
            await db.scalars(
                select(LineageEdge).where(
                    LineageEdge.child_record_id.in_(record_ids),
                )
            )
        ).all()
    )


def _case_response(case: AssuranceCase) -> AssuranceCaseResponse:
    return AssuranceCaseResponse.model_validate(case)


def _evidence_response(
    case_id: UUID,
    record: ProvenanceRecord,
    source: DataSource,
    role: str,
    required: bool,
) -> AssuranceEvidenceResponse:
    return AssuranceEvidenceResponse(
        id=record.id,
        case_id=case_id,
        source_id=source.id,
        source_key=source.key,
        source_name=source.display_name,
        source_url=source.reference_url,
        license_name=source.license_name,
        license_url=source.license_url,
        attribution_text=source.attribution_text,
        terms_note=source.terms_note,
        authority_level=source.authority_level,
        official=source.official,
        source_limitations=source.limitations,
        evidence_role=role,
        required=required,
        entity_type=record.entity_type,
        entity_key=record.entity_key,
        canonical_source_type=record.canonical_source_type,
        observed_at=record.observed_at or record.fetched_at,
        fetched_at=record.fetched_at,
        valid_until=record.valid_until,
        freshness_state=record.freshness_state,
        availability_state=record.availability_state,
        confidence=float(record.confidence) if record.confidence is not None else None,
        completeness=float(record.completeness) if record.completeness is not None else None,
        value_summary=record.value_summary,
        metadata=record.metadata_json,
        integrity_checksum=record.integrity_checksum,
        created_at=record.created_at,
    )


def _finding_response(finding: AssuranceFinding) -> AssuranceFindingResponse:
    return AssuranceFindingResponse.model_validate(finding)


def _matrix_response(snapshot: AssuranceSnapshot) -> EvidenceMatrixResponse:
    return EvidenceMatrixResponse(
        case_id=snapshot.case_id,
        snapshot_id=snapshot.id,
        state=snapshot.decision_state,
        roles=[EvidenceMatrixItem.model_validate(item) for item in snapshot.matrix_json["roles"]],
    )


async def _assessment_response(
    db: AsyncSession, snapshot: AssuranceSnapshot
) -> AssuranceAssessmentResponse:
    findings = list(
        (
            await db.scalars(
                select(AssuranceFinding)
                .where(AssuranceFinding.snapshot_id == snapshot.id)
                .order_by(AssuranceFinding.severity.desc(), AssuranceFinding.code)
            )
        ).all()
    )
    return AssuranceAssessmentResponse(
        id=snapshot.id,
        case_id=snapshot.case_id,
        sequence_no=snapshot.sequence_no,
        decision_state=snapshot.decision_state,
        policy_key=snapshot.policy_key,
        policy_version=snapshot.policy_version,
        matrix=_matrix_response(snapshot),
        metrics=snapshot.metrics_json,
        bundle_checksum=snapshot.bundle_checksum,
        bundle_signature=snapshot.bundle_signature,
        signing_key_id=snapshot.signing_key_id,
        signing_algorithm=snapshot.signing_algorithm,
        assessed_at=snapshot.assessed_at,
        findings=[_finding_response(item) for item in findings],
    )


async def _owned_snapshot(
    db: AsyncSession,
    case: AssuranceCase,
    snapshot_id: UUID | None = None,
) -> AssuranceSnapshot:
    statement = select(AssuranceSnapshot).where(
        AssuranceSnapshot.case_id == case.id,
        AssuranceSnapshot.user_id == case.user_id,
    )
    if snapshot_id is not None:
        statement = statement.where(AssuranceSnapshot.id == snapshot_id)
    else:
        statement = statement.order_by(AssuranceSnapshot.sequence_no.desc()).limit(1)
    snapshot = await db.scalar(statement)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Assurance assessment not found")
    return snapshot


@router.get("/policies", response_model=list[AssurancePolicyResponse])
async def list_assurance_policies() -> list[AssurancePolicyResponse]:
    return [AssurancePolicyResponse.model_validate(value) for value in POLICIES.values()]


@router.post(
    "/cases",
    response_model=AssuranceCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assurance_case(
    payload: AssuranceCaseCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceCaseResponse:
    try:
        policy = get_policy(payload.policy_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.assigned_reviewer_id == user.id:
        raise HTTPException(
            status_code=422,
            detail="The case owner cannot be assigned as its reviewer",
        )
    case = AssuranceCase(
        id=uuid4(),
        user_id=user.id,
        assigned_reviewer_id=payload.assigned_reviewer_id,
        title=payload.title.strip(),
        purpose=payload.purpose.strip(),
        subject_type=payload.subject_type.strip(),
        subject_key=payload.subject_key.strip(),
        context_json=payload.context,
        required_roles=payload.required_roles,
        policy_key=policy["key"],
        policy_version=policy["version"],
        status="OPEN",
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return _case_response(case)


@router.get("/cases", response_model=list[AssuranceCaseResponse])
async def list_assurance_cases(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[AssuranceCaseResponse]:
    rows = list(
        (
            await db.scalars(
                select(AssuranceCase)
                .where(
                    or_(
                        AssuranceCase.user_id == user.id,
                        AssuranceCase.assigned_reviewer_id == user.id,
                    )
                )
                .order_by(AssuranceCase.updated_at.desc())
            )
        ).all()
    )
    return [_case_response(item) for item in rows]


@router.get("/cases/{case_id}", response_model=AssuranceCaseResponse)
async def get_assurance_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceCaseResponse:
    return _case_response(await _accessible_case(db, case_id, user.id))


@router.post(
    "/cases/{case_id}/evidence",
    response_model=AssuranceEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_case_evidence(
    case_id: UUID,
    payload: AssuranceEvidenceCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceEvidenceResponse:
    case = await _owned_case(db, case_id, user.id, lock=True)
    if case.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="Archived assurance cases are immutable")
    source = await db.scalar(
        select(DataSource).where(DataSource.id == payload.source_id, DataSource.enabled.is_(True))
    )
    if source is None:
        raise HTTPException(status_code=422, detail="Evidence source is unknown or disabled")
    compatible_sources = {
        "OPERATOR_INPUT": "operator_input",
        "IMPORTED_DOCUMENT": "imported_engineering",
    }
    expected_source_key = compatible_sources[payload.canonical_source_type]
    if source.key != expected_source_key:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{payload.canonical_source_type} evidence must use the "
                f"{expected_source_key} source registry entry"
            ),
        )

    if payload.parent_record_ids:
        parent_count = await db.scalar(
            select(func.count())
            .select_from(CaseEvidenceLink)
            .join(ProvenanceRecord, ProvenanceRecord.id == CaseEvidenceLink.record_id)
            .where(
                CaseEvidenceLink.case_id == case.id,
                CaseEvidenceLink.record_id.in_(payload.parent_record_ids),
                ProvenanceRecord.user_id == user.id,
            )
        )
        if parent_count != len(payload.parent_record_ids):
            raise HTTPException(
                status_code=422,
                detail="Every parent_record_id must already belong to this assurance case",
            )
    if payload.canonical_source_type == "DERIVED" and not payload.parent_record_ids:
        raise HTTPException(status_code=422, detail="Derived evidence requires parent_record_ids")

    now = datetime.now(timezone.utc)
    record = ProvenanceRecord(
        id=uuid4(),
        user_id=user.id,
        route_id=None,
        decision_snapshot_id=None,
        source_id=source.id,
        entity_type=payload.entity_type.strip(),
        entity_key=payload.entity_key.strip(),
        decision_input_role=payload.evidence_role,
        canonical_source_type=payload.canonical_source_type,
        raw_source_state=(
            "USER_DECLARED_OPERATOR_INPUT"
            if payload.canonical_source_type == "OPERATOR_INPUT"
            else "USER_DECLARED_DOCUMENT_IMPORT"
        ),
        observed_at=payload.observed_at.astimezone(timezone.utc),
        fetched_at=payload.fetched_at.astimezone(timezone.utc),
        valid_until=(
            payload.valid_until.astimezone(timezone.utc) if payload.valid_until else None
        ),
        freshness_state=payload.freshness_state,
        freshness_seconds=max(
            0, int((payload.fetched_at - payload.observed_at).total_seconds())
        ),
        cache_hit=payload.canonical_source_type == "CACHED_PROVIDER",
        used_in_decision=True,
        excluded_reason=None,
        availability_state=payload.availability_state,
        confidence=payload.confidence,
        completeness=payload.completeness,
        transform_name=payload.transform_name,
        transform_version=payload.transform_version,
        formula_reference=payload.formula_reference,
        request_id=str(case.id),
        checksum=stable_checksum(payload.value_summary),
        value_summary=payload.value_summary,
        metadata_json={
            **payload.metadata,
            "assurance_case_id": str(case.id),
            "assurance_subject_type": case.subject_type,
            "assurance_subject_key": case.subject_key,
            "assurance_context_checksum": stable_checksum(case.context_json),
            "ingest_trust": "USER_DECLARED",
            "signature_verified": False,
            "issuer_authentication": "NONE",
            "captured_at": now.isoformat(),
        },
        created_at=now,
    )
    # Seal the PostgreSQL representation: Numeric fields may be quantized and
    # returned as Decimal, which differs from the incoming Python float form.
    db.add(record)
    await db.flush()
    await db.refresh(record)
    record.integrity_checksum = stable_checksum(record_integrity_payload(record))
    link = CaseEvidenceLink(
        id=uuid4(),
        case_id=case.id,
        record_id=record.id,
        evidence_role=payload.evidence_role,
        required=payload.required,
        linked_by=user.id,
        created_at=now,
    )
    db.add(link)
    db.add_all(
        [
            LineageEdge(
                id=uuid4(),
                parent_record_id=parent_id,
                child_record_id=record.id,
                relationship="DERIVED_FROM",
                created_at=now,
            )
            for parent_id in payload.parent_record_ids
        ]
    )
    case.status = "OPEN"
    await db.commit()
    return _evidence_response(case.id, record, source, link.evidence_role, link.required)


@router.post(
    "/cases/{case_id}/evidence-links",
    response_model=AssuranceEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def link_existing_case_evidence(
    case_id: UUID,
    payload: AssuranceEvidenceLinkCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceEvidenceResponse:
    """Bind evidence previously produced by a trusted connector/transform.

    This endpoint never relabels a record: its stored source, source type,
    role, timestamps, checksum and payload remain authoritative.
    """

    case = await _owned_case(db, case_id, user.id, lock=True)
    if case.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="Archived assurance cases are immutable")
    row = (
        await db.execute(
            select(ProvenanceRecord, DataSource)
            .join(DataSource, DataSource.id == ProvenanceRecord.source_id)
            .where(
                ProvenanceRecord.id == payload.record_id,
                ProvenanceRecord.user_id == user.id,
                DataSource.enabled.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Eligible provenance record not found")
    record, source = row
    if (record.decision_input_role or "").strip().upper() != payload.evidence_role:
        raise HTTPException(
            status_code=422,
            detail="Evidence role must match the immutable provenance record role",
        )
    existing = await db.scalar(
        select(CaseEvidenceLink).where(
            CaseEvidenceLink.case_id == case.id,
            CaseEvidenceLink.record_id == record.id,
            CaseEvidenceLink.evidence_role == payload.evidence_role,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Evidence record is already linked to this role")
    link = CaseEvidenceLink(
        id=uuid4(),
        case_id=case.id,
        record_id=record.id,
        evidence_role=payload.evidence_role,
        required=payload.required,
        linked_by=user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(link)
    case.status = "OPEN"
    await db.commit()
    return _evidence_response(case.id, record, source, link.evidence_role, link.required)


@router.get("/cases/{case_id}/evidence", response_model=list[AssuranceEvidenceResponse])
async def list_case_evidence(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[AssuranceEvidenceResponse]:
    case = await _accessible_case(db, case_id, user.id)
    rows = await _evidence_rows(db, case)
    return [
        _evidence_response(case.id, record, source, role, required)
        for record, source, role, required in rows
        if source is not None
    ]


@router.post(
    "/cases/{case_id}/assessments",
    response_model=AssuranceAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assess_assurance_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceAssessmentResponse:
    case = await db.scalar(
        select(AssuranceCase)
        .where(AssuranceCase.id == case_id, AssuranceCase.user_id == user.id)
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Assurance case not found")
    if case.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="Archived assurance cases are immutable")
    rows = await _evidence_rows(db, case)
    record_ids = [row[0].id for row in rows]
    edges = await _lineage(db, record_ids)
    result = assess_case_evidence(case, rows, edges)
    manifest = [
        {
            **item,
            "lineage_checksum": stable_checksum(lineage_payload(edges, UUID(item["record_id"]))),
        }
        for item in result.evidence_manifest
    ]
    sequence = int(
        await db.scalar(
            select(func.coalesce(func.max(AssuranceSnapshot.sequence_no), 0)).where(
                AssuranceSnapshot.case_id == case.id
            )
        )
        or 0
    ) + 1
    assessed_at = datetime.now(timezone.utc)
    snapshot = AssuranceSnapshot(
        id=uuid4(),
        case_id=case.id,
        user_id=user.id,
        sequence_no=sequence,
        decision_state=result.state,
        policy_key=case.policy_key,
        policy_version=case.policy_version,
        evidence_manifest=manifest,
        matrix_json=result.matrix,
        metrics_json=result.metrics,
        bundle_checksum="0" * 64,
        bundle_signature="0" * 64,
        signing_key_id="pending",
        signing_algorithm="HMAC-SHA256",
        assessed_at=assessed_at,
        created_at=assessed_at,
    )
    findings = [
        AssuranceFinding(
            id=uuid4(),
            case_id=case.id,
            snapshot_id=snapshot.id,
            code=value.code,
            severity=value.severity,
            message=value.message,
            evidence_record_ids=list(value.record_ids),
            details_json=value.details,
            created_at=assessed_at,
        )
        for value in result.findings
    ]
    seal_snapshot(case, snapshot, findings)
    db.add(snapshot)
    db.add_all(findings)
    case.status = "ASSESSED"
    await db.commit()
    return await _assessment_response(db, snapshot)


@router.get(
    "/cases/{case_id}/assessments/{snapshot_id}",
    response_model=AssuranceAssessmentResponse,
)
async def get_assurance_assessment(
    case_id: UUID,
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceAssessmentResponse:
    case = await _accessible_case(db, case_id, user.id)
    return await _assessment_response(db, await _owned_snapshot(db, case, snapshot_id))


@router.get("/cases/{case_id}/matrix", response_model=EvidenceMatrixResponse)
async def get_evidence_matrix(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> EvidenceMatrixResponse:
    case = await _accessible_case(db, case_id, user.id)
    return _matrix_response(await _owned_snapshot(db, case))


@router.post(
    "/cases/{case_id}/review-receipts",
    response_model=ReviewReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review_receipt(
    case_id: UUID,
    payload: ReviewReceiptCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ReviewReceiptResponse:
    case = await _accessible_case(db, case_id, user.id, lock=True)
    if case.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="Archived assurance cases are immutable")
    if (
        case.assigned_reviewer_id is None
        or user.id != case.assigned_reviewer_id
        or user.id == case.user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the independently assigned reviewer may review this case",
        )
    if not _authorized_attestation_role(user.role):
        raise HTTPException(
            status_code=403,
            detail="An approver or administrator role is required to review this case",
        )
    snapshot = await _owned_snapshot(db, case, payload.snapshot_id)
    if payload.outcome == "ATTESTED" and snapshot.decision_state != "REVIEWABLE":
        raise HTTPException(
            status_code=409,
            detail="Only a REVIEWABLE snapshot can receive an ATTESTED review receipt",
        )
    latest = await _owned_snapshot(db, case)
    if latest.id != snapshot.id or case.status != "ASSESSED":
        raise HTTPException(status_code=409, detail="Assess the current evidence before reviewing")
    existing = await db.scalar(
        select(ReviewReceipt).where(ReviewReceipt.snapshot_id == snapshot.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This snapshot already has a final review receipt")
    verification = await verify_assurance_bundle(
        case_id, AssuranceVerifyRequest(snapshot_id=snapshot.id), db, user
    )
    if not verification.verified:
        raise HTTPException(status_code=409, detail="Snapshot integrity verification failed")
    rows = await _evidence_rows(db, case)
    current = assess_case_evidence(
        case,
        rows,
        await _lineage(db, [row[0].id for row in rows]),
    )
    if current.state != snapshot.decision_state:
        raise HTTPException(status_code=409, detail="Evidence no longer matches this assessment")
    reviewed_at = datetime.now(timezone.utc)
    receipt = ReviewReceipt(
        id=uuid4(),
        case_id=case.id,
        snapshot_id=snapshot.id,
        reviewer_id=user.id,
        reviewer_role=user.role,
        outcome=payload.outcome,
        statement=payload.statement.strip(),
        snapshot_checksum=snapshot.bundle_checksum,
        receipt_checksum="0" * 64,
        receipt_signature="0" * 64,
        signing_key_id="pending",
        signing_algorithm="HMAC-SHA256",
        reviewed_at=reviewed_at,
        created_at=reviewed_at,
    )
    seal_receipt(receipt)
    db.add(receipt)
    if payload.outcome == "ATTESTED":
        case.status = "REVIEWED"
    else:
        case.status = "OPEN"
    await db.commit()
    return ReviewReceiptResponse.model_validate(receipt)


async def _review_receipts(
    db: AsyncSession, case: AssuranceCase, snapshot: AssuranceSnapshot
) -> list[ReviewReceipt]:
    return list(
        (
            await db.scalars(
                select(ReviewReceipt)
                .where(
                    ReviewReceipt.case_id == case.id,
                    ReviewReceipt.snapshot_id == snapshot.id,
                )
                .order_by(ReviewReceipt.reviewed_at)
            )
        ).all()
    )


@router.get(
    "/cases/{case_id}/review-receipts", response_model=list[ReviewReceiptResponse]
)
async def list_review_receipts(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[ReviewReceiptResponse]:
    case = await _accessible_case(db, case_id, user.id)
    receipts = list(
        (
            await db.scalars(
                select(ReviewReceipt)
                .where(ReviewReceipt.case_id == case.id)
                .order_by(ReviewReceipt.reviewed_at)
            )
        ).all()
    )
    return [ReviewReceiptResponse.model_validate(item) for item in receipts]


@router.get("/cases/{case_id}/bundle", response_model=AssuranceBundleResponse)
async def get_assurance_bundle(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceBundleResponse:
    case = await _accessible_case(db, case_id, user.id)
    snapshot = await _owned_snapshot(db, case)
    rows = await _evidence_rows(db, case)
    receipts = await _review_receipts(db, case, snapshot)
    findings = list((await db.scalars(
        select(AssuranceFinding).where(AssuranceFinding.snapshot_id == snapshot.id)
    )).all())
    selected_ids = {UUID(item["record_id"]) for item in snapshot.evidence_manifest}
    selected_rows = [row for row in rows if row[0].id in selected_ids]
    edges = await _lineage(db, list(selected_ids))
    return AssuranceBundleResponse(
        case=_case_response(case),
        assessment=await _assessment_response(db, snapshot),
        evidence=[
            _evidence_response(case.id, record, source, role, required)
            for record, source, role, required in rows
            if source is not None
            and any(item["record_id"] == str(record.id) for item in snapshot.evidence_manifest)
        ],
        review_receipts=[ReviewReceiptResponse.model_validate(item) for item in receipts],
        review_receipt_manifests=[redact_metadata(receipt_payload(item)) for item in receipts],
        sealed_manifest=redact_metadata(snapshot_manifest_payload(case, snapshot, findings)),
        evidence_envelopes=[redact_metadata(record_integrity_payload(row[0])) for row in selected_rows],
        source_catalog=[
            redact_metadata(source_integrity_payload(source))
            for source in {row[1].id: row[1] for row in selected_rows if row[1] is not None}.values()
        ],
        lineage=[item for record_id in sorted(selected_ids, key=str) for item in lineage_payload(edges, record_id)],
        limitations=[
            "Non-vital evidence assurance only; this bundle is not movement authority.",
            "REVIEWABLE records policy admissibility, not operational safety approval.",
            "Provider content is a stored snapshot and is not refreshed by this endpoint.",
            "Offline checksum reconstruction detects changes; HMAC signature verification requires the trusted server key.",
        ],
    )


@router.get("/cases/{case_id}/timeline", response_model=AssuranceTimelineResponse)
async def get_assurance_timeline(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceTimelineResponse:
    case = await _accessible_case(db, case_id, user.id)
    rows = await _evidence_rows(db, case)
    snapshots = list(
        (
            await db.scalars(
                select(AssuranceSnapshot)
                .where(AssuranceSnapshot.case_id == case.id)
                .order_by(AssuranceSnapshot.sequence_no)
            )
        ).all()
    )
    receipts = list(
        (
            await db.scalars(
                select(ReviewReceipt)
                .where(ReviewReceipt.case_id == case.id)
                .order_by(ReviewReceipt.reviewed_at)
            )
        ).all()
    )
    events = [
        AssuranceTimelineEvent(
            occurred_at=case.created_at,
            event_type="CASE_CREATED",
            entity_id=case.id,
            summary="Assurance case created.",
        )
    ]
    events.extend(
        AssuranceTimelineEvent(
            occurred_at=record.created_at,
            event_type="EVIDENCE_CAPTURED",
            entity_id=record.id,
            summary=f"{role} evidence captured from {source.key if source else 'unknown source'}.",
            details={"required": required},
        )
        for record, source, role, required in rows
    )
    events.extend(
        AssuranceTimelineEvent(
            occurred_at=item.assessed_at,
            event_type="CASE_ASSESSED",
            entity_id=item.id,
            summary=f"Assessment {item.sequence_no} produced {item.decision_state}.",
        )
        for item in snapshots
    )
    events.extend(
        AssuranceTimelineEvent(
            occurred_at=item.reviewed_at,
            event_type="REVIEW_RECORDED",
            entity_id=item.id,
            summary=f"Human reviewer recorded {item.outcome}.",
        )
        for item in receipts
    )
    events.sort(key=lambda item: item.occurred_at)
    return AssuranceTimelineResponse(case_id=case.id, events=events)


@router.post("/cases/{case_id}/verify", response_model=AssuranceVerifyResponse)
async def verify_assurance_bundle(
    case_id: UUID,
    payload: AssuranceVerifyRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AssuranceVerifyResponse:
    case = await _accessible_case(db, case_id, user.id)
    snapshot = await _owned_snapshot(db, case, payload.snapshot_id)
    findings = list(
        (
            await db.scalars(
                select(AssuranceFinding).where(AssuranceFinding.snapshot_id == snapshot.id)
            )
        ).all()
    )
    checksum_valid, signature_valid, _computed = verify_snapshot(case, snapshot, findings)

    manifest_by_id = {UUID(item["record_id"]): item for item in snapshot.evidence_manifest}
    current_rows = list(
        (
            await db.execute(
                select(ProvenanceRecord, DataSource)
                .outerjoin(DataSource, DataSource.id == ProvenanceRecord.source_id)
                .where(
                    ProvenanceRecord.id.in_(manifest_by_id),
                    ProvenanceRecord.user_id == case.user_id,
                )
            )
        ).all()
    )
    invalid_evidence = set(manifest_by_id) - {row[0].id for row in current_rows}
    edges = await _lineage(db, list(manifest_by_id))
    for record, source in current_rows:
        expected = manifest_by_id[record.id].get("integrity_checksum")
        computed = stable_checksum(record_integrity_payload(record))
        if (
            not expected
            or not record.integrity_checksum
            or expected != computed
            or record.integrity_checksum != computed
        ):
            invalid_evidence.add(record.id)
            continue
        expected_source = manifest_by_id[record.id].get("source_metadata_checksum")
        if source is None or expected_source != stable_checksum(source_integrity_payload(source)):
            invalid_evidence.add(record.id)
        expected_lineage = manifest_by_id[record.id].get("lineage_checksum")
        if expected_lineage != stable_checksum(lineage_payload(edges, record.id)):
            invalid_evidence.add(record.id)

    receipts = await _review_receipts(db, case, snapshot)
    invalid_receipts = [
        item.id
        for item in receipts
        if item.snapshot_checksum != snapshot.bundle_checksum
        or not verify_receipt(item)
        or (
            item.outcome == "ATTESTED"
            and (
                not _authorized_attestation_role(item.reviewer_role)
                or item.reviewer_id != case.assigned_reviewer_id
                or item.reviewer_id == case.user_id
                or (
                    item.reviewer_id == user.id
                    and not _authorized_attestation_role(user.role)
                )
            )
        )
    ]
    evidence_valid = not invalid_evidence
    verified = checksum_valid and signature_valid and evidence_valid and not invalid_receipts
    return AssuranceVerifyResponse(
        case_id=case.id,
        snapshot_id=snapshot.id,
        verified=verified,
        bundle_checksum_valid=checksum_valid,
        bundle_signature_valid=signature_valid,
        evidence_integrity_valid=evidence_valid,
        invalid_evidence_record_ids=sorted(invalid_evidence, key=str),
        invalid_review_receipt_ids=invalid_receipts,
    )
