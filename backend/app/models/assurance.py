"""Generic, non-vital assurance-case persistence.

These models deliberately have no dependency on ``generated_routes``.  An
assurance case can describe any railway decision-support subject while its
evidence remains attributable to the existing SourceLine source registry.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.route import Base


class AssuranceCase(Base):
    """Owner-scoped container for one evidence-assurance question."""

    __tablename__ = "assurance_cases"
    __table_args__ = (
        CheckConstraint(
            "assigned_reviewer_id IS NULL OR assigned_reviewer_id <> user_id",
            name="ck_assurance_case_reviewer_separation",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'ASSESSED', 'REVIEWED', 'ARCHIVED')",
            name="ck_assurance_case_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    assigned_reviewer_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    context_json: Mapped[dict] = mapped_column("context", JSONB, nullable=False, default=dict)
    required_roles: Mapped[list] = mapped_column(JSONB, nullable=False)
    policy_key: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssuranceSnapshot(Base):
    """Immutable result of assessing the evidence linked to a case."""

    __tablename__ = "assurance_snapshots"
    __table_args__ = (
        UniqueConstraint("case_id", "sequence_no", name="uq_assurance_snapshot_sequence"),
        CheckConstraint(
            "decision_state IN ('REVIEWABLE', 'HOLD', 'UNAVAILABLE')",
            name="ck_assurance_snapshot_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assurance_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_state: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_key: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_manifest: Mapped[list] = mapped_column(JSONB, nullable=False)
    matrix_json: Mapped[dict] = mapped_column("matrix", JSONB, nullable=False)
    metrics_json: Mapped[dict] = mapped_column("metrics", JSONB, nullable=False)
    bundle_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    signing_key_id: Mapped[str] = mapped_column(String(120), nullable=False)
    signing_algorithm: Mapped[str] = mapped_column(String(40), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CaseEvidenceLink(Base):
    """Case-specific role and requirement binding for a generic evidence row."""

    __tablename__ = "case_evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "case_id", "record_id", "evidence_role", name="uq_case_evidence_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assurance_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provenance_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_role: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    linked_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AssuranceFinding(Base):
    """Machine-readable reason emitted by one assurance assessment."""

    __tablename__ = "assurance_findings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR')",
            name="ck_assurance_finding_severity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assurance_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assurance_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_record_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    details_json: Mapped[dict] = mapped_column("details", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReviewReceipt(Base):
    """Human review attestation bound to an immutable assurance snapshot."""

    __tablename__ = "review_receipts"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_review_receipt_snapshot"),
        CheckConstraint(
            "outcome IN ('ATTESTED', 'RETURNED')",
            name="ck_review_receipt_outcome",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assurance_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assurance_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reviewer_role: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    signing_key_id: Mapped[str] = mapped_column(String(120), nullable=False)
    signing_algorithm: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
