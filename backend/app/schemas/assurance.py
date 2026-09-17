"""API contracts for generic non-vital evidence assurance."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


AssuranceState = Literal["REVIEWABLE", "HOLD", "UNAVAILABLE"]
CaseStatus = Literal["OPEN", "ASSESSED", "REVIEWED", "ARCHIVED"]


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value


class AssuranceCaseCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    title: str = Field(..., min_length=3, max_length=200)
    purpose: str = Field(..., min_length=10, max_length=4000)
    subject_type: str = Field(..., min_length=1, max_length=80)
    subject_key: str = Field(..., min_length=1, max_length=255)
    context: dict = Field(default_factory=dict)
    required_roles: list[str] = Field(..., min_length=1, max_length=64)
    policy_key: str = Field(default="GENERIC_PROVENANCE_V1", max_length=80)
    assigned_reviewer_id: str | None = Field(default=None, max_length=64)

    @field_validator("required_roles")
    @classmethod
    def normalize_roles(cls, value: list[str]) -> list[str]:
        roles = [item.strip().upper() for item in value if item.strip()]
        if not roles:
            raise ValueError("at least one non-empty evidence role is required")
        if len(set(roles)) != len(roles):
            raise ValueError("required_roles must be unique")
        return roles

    @field_validator("assigned_reviewer_id")
    @classmethod
    def normalize_reviewer_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AssuranceCaseResponse(BaseModel):
    id: UUID
    user_id: str
    assigned_reviewer_id: str | None
    title: str
    purpose: str
    subject_type: str
    subject_key: str
    context: dict = Field(validation_alias="context_json", serialization_alias="context")
    required_roles: list[str]
    policy_key: str
    policy_version: str
    status: CaseStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssuranceEvidenceCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    source_id: UUID
    evidence_role: str = Field(..., min_length=1, max_length=80)
    required: bool = True
    entity_type: str = Field(..., min_length=1, max_length=80)
    entity_key: str = Field(..., min_length=1, max_length=255)
    # This public endpoint captures human declarations or imported documents.
    # Provider and derived classifications are assigned only by trusted server
    # connectors/transforms and can be linked through AssuranceEvidenceLinkCreate.
    canonical_source_type: Literal["OPERATOR_INPUT", "IMPORTED_DOCUMENT"]
    observed_at: datetime
    fetched_at: datetime
    valid_until: datetime | None = None
    freshness_state: Literal["FRESH", "AGING", "STALE", "NOT_APPLICABLE"]
    availability_state: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    completeness: float = Field(..., ge=0, le=1)
    value_summary: dict
    metadata: dict = Field(default_factory=dict)
    transform_name: str | None = Field(default=None, max_length=120)
    transform_version: str | None = Field(default=None, max_length=40)
    formula_reference: str | None = Field(default=None, max_length=120)
    parent_record_ids: list[UUID] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_evidence(self) -> "AssuranceEvidenceCreate":
        self.evidence_role = self.evidence_role.strip().upper()
        _aware(self.observed_at, "observed_at")
        _aware(self.fetched_at, "fetched_at")
        if self.valid_until is not None:
            _aware(self.valid_until, "valid_until")
        if self.fetched_at < self.observed_at:
            raise ValueError("fetched_at cannot be before observed_at")
        if not self.value_summary:
            raise ValueError("value_summary must contain the captured evidence payload")
        if len(set(self.parent_record_ids)) != len(self.parent_record_ids):
            raise ValueError("parent_record_ids must be unique")
        return self


class AssuranceEvidenceLinkCreate(BaseModel):
    """Link an already-ingested, owner-scoped provenance record to a case."""

    record_id: UUID
    evidence_role: str = Field(..., min_length=1, max_length=80)
    required: bool = True

    @field_validator("evidence_role")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("evidence_role cannot be empty")
        return normalized


class AssuranceEvidenceResponse(BaseModel):
    id: UUID
    case_id: UUID
    source_id: UUID
    source_key: str
    source_name: str
    source_url: str | None
    license_name: str | None
    license_url: str | None
    attribution_text: str | None
    terms_note: str | None
    authority_level: str
    official: bool
    source_limitations: dict
    evidence_role: str
    required: bool
    entity_type: str
    entity_key: str
    canonical_source_type: str
    observed_at: datetime
    fetched_at: datetime
    valid_until: datetime | None
    freshness_state: str
    availability_state: str
    confidence: float | None
    completeness: float | None
    value_summary: dict
    metadata: dict
    integrity_checksum: str | None
    created_at: datetime


class AssuranceFindingResponse(BaseModel):
    id: UUID
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    message: str
    evidence_record_ids: list[str]
    details: dict = Field(validation_alias="details_json", serialization_alias="details")
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceMatrixItem(BaseModel):
    role: str
    required: bool
    status: Literal["PASS", "WARNING", "FAIL", "MISSING"]
    record_ids: list[UUID] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class EvidenceMatrixResponse(BaseModel):
    case_id: UUID
    snapshot_id: UUID
    state: AssuranceState
    roles: list[EvidenceMatrixItem]


class AssuranceAssessmentResponse(BaseModel):
    id: UUID
    case_id: UUID
    sequence_no: int
    decision_state: AssuranceState
    policy_key: str
    policy_version: str
    matrix: EvidenceMatrixResponse
    metrics: dict
    bundle_checksum: str
    bundle_signature: str
    signing_key_id: str
    signing_algorithm: str
    assessed_at: datetime
    findings: list[AssuranceFindingResponse]


class ReviewReceiptCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    snapshot_id: UUID
    outcome: Literal["ATTESTED", "RETURNED"]
    statement: str = Field(..., min_length=12, max_length=4000)


class ReviewReceiptResponse(BaseModel):
    id: UUID
    case_id: UUID
    snapshot_id: UUID
    reviewer_id: str
    reviewer_role: str
    outcome: Literal["ATTESTED", "RETURNED"]
    statement: str
    snapshot_checksum: str
    receipt_checksum: str
    receipt_signature: str
    signing_key_id: str
    signing_algorithm: str
    reviewed_at: datetime

    model_config = {"from_attributes": True}


class AssuranceTimelineEvent(BaseModel):
    occurred_at: datetime
    event_type: str
    entity_id: UUID
    summary: str
    details: dict = Field(default_factory=dict)


class AssuranceTimelineResponse(BaseModel):
    case_id: UUID
    events: list[AssuranceTimelineEvent]


class AssuranceBundleResponse(BaseModel):
    format_version: Literal["clearpath.assurance-bundle.v1"] = (
        "clearpath.assurance-bundle.v1"
    )
    case: AssuranceCaseResponse
    assessment: AssuranceAssessmentResponse
    evidence: list[AssuranceEvidenceResponse]
    review_receipts: list[ReviewReceiptResponse]
    review_receipt_manifests: list[dict]
    sealed_manifest: dict
    evidence_envelopes: list[dict]
    source_catalog: list[dict]
    lineage: list[dict]
    limitations: list[str]


class AssuranceVerifyRequest(BaseModel):
    snapshot_id: UUID | None = None


class AssuranceVerifyResponse(BaseModel):
    case_id: UUID
    snapshot_id: UUID
    verified: bool
    bundle_checksum_valid: bool
    bundle_signature_valid: bool
    evidence_integrity_valid: bool
    invalid_evidence_record_ids: list[UUID]
    invalid_review_receipt_ids: list[UUID]


class AssurancePolicyResponse(BaseModel):
    key: str
    version: str
    title: str
    description: str
    decision_states: list[str]
    checks: list[dict]
    limitations: list[str]
