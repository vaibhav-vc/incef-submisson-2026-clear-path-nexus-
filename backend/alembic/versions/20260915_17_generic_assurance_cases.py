"""Add route-independent, non-vital evidence assurance cases."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260915_17"
down_revision = "20260914_16"
branch_labels = None
depends_on = None

APPLICATION_TABLES = (
    "stations",
    "users",
    "line_segments",
    "port_berths",
    "generated_routes",
    "auth_sessions",
    "train_schedules",
    "data_sources",
    "route_decision_snapshots",
    "provenance_records",
    "lineage_edges",
    "compliance_rule_sources",
    "shipment_documents",
    "compliance_checks",
    "compliance_check_items",
    "compliance_override_events",
    "provider_observations",
    "shipments",
    "shipment_positions",
    "operational_events",
    "provider_runtime_state",
    "ml_datasets",
    "ml_training_runs",
    "ml_model_versions",
    "ml_predictions",
    "multimodal_plans",
    "multimodal_legs",
    "train_sync_states",
    "train_consists",
    "carriage_loads",
    "route_occupation_windows",
    "track_section_policies",
    "assurance_cases",
    "assurance_snapshots",
    "case_evidence_links",
    "assurance_findings",
    "review_receipts",
)


def _lockdown(table: str) -> None:
    op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC')
    for role in ("anon", "authenticated"):
        op.execute(
            f"DO $lockdown$ BEGIN "
            f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
            f"EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.\"{table}\" FROM {role}'; "
            f"END IF; END $lockdown$;"
        )


def upgrade() -> None:
    op.create_table(
        "assurance_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("assigned_reviewer_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.String(80), nullable=False),
        sa.Column("subject_key", sa.String(255), nullable=False),
        sa.Column(
            "context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("required_roles", postgresql.JSONB(), nullable=False),
        sa.Column("policy_key", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('OPEN', 'ASSESSED', 'REVIEWED', 'ARCHIVED')",
            name="ck_assurance_case_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(required_roles) = 'array' AND jsonb_array_length(required_roles) > 0",
            name="ck_assurance_case_required_roles",
        ),
        sa.CheckConstraint(
            "assigned_reviewer_id IS NULL OR assigned_reviewer_id <> user_id",
            name="ck_assurance_case_reviewer_separation",
        ),
    )
    op.create_index("ix_assurance_cases_user_id", "assurance_cases", ["user_id"])
    op.create_index(
        "ix_assurance_cases_assigned_reviewer_id",
        "assurance_cases",
        ["assigned_reviewer_id"],
    )
    op.create_index("ix_assurance_cases_subject_type", "assurance_cases", ["subject_type"])
    op.create_index("ix_assurance_cases_subject_key", "assurance_cases", ["subject_key"])
    op.create_index(
        "ix_assurance_cases_owner_updated", "assurance_cases", ["user_id", "updated_at"]
    )

    op.create_table(
        "assurance_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assurance_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("decision_state", sa.String(20), nullable=False),
        sa.Column("policy_key", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("evidence_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("matrix", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("bundle_checksum", sa.String(64), nullable=False),
        sa.Column("bundle_signature", sa.String(64), nullable=False),
        sa.Column("signing_key_id", sa.String(120), nullable=False),
        sa.Column("signing_algorithm", sa.String(40), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("case_id", "sequence_no", name="uq_assurance_snapshot_sequence"),
        sa.CheckConstraint("sequence_no > 0", name="ck_assurance_snapshot_sequence"),
        sa.CheckConstraint(
            "decision_state IN ('REVIEWABLE', 'HOLD', 'UNAVAILABLE')",
            name="ck_assurance_snapshot_state",
        ),
        sa.CheckConstraint(
            "bundle_checksum ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_assurance_snapshot_checksum",
        ),
        sa.CheckConstraint(
            "bundle_signature ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_assurance_snapshot_signature",
        ),
    )
    op.create_index("ix_assurance_snapshots_case_id", "assurance_snapshots", ["case_id"])
    op.create_index("ix_assurance_snapshots_user_id", "assurance_snapshots", ["user_id"])
    op.create_table(
        "case_evidence_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assurance_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provenance_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_role", sa.String(80), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("linked_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "case_id", "record_id", "evidence_role", name="uq_case_evidence_role"
        ),
    )
    op.create_index("ix_case_evidence_links_case_id", "case_evidence_links", ["case_id"])
    op.create_index("ix_case_evidence_links_record_id", "case_evidence_links", ["record_id"])
    op.create_index(
        "ix_case_evidence_links_evidence_role", "case_evidence_links", ["evidence_role"]
    )

    op.create_table(
        "assurance_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assurance_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assurance_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "evidence_record_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR')",
            name="ck_assurance_finding_severity",
        ),
    )
    op.create_index("ix_assurance_findings_case_id", "assurance_findings", ["case_id"])
    op.create_index(
        "ix_assurance_findings_snapshot_id", "assurance_findings", ["snapshot_id"]
    )
    op.create_index("ix_assurance_findings_code", "assurance_findings", ["code"])

    op.create_table(
        "review_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assurance_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assurance_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("reviewer_role", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("receipt_checksum", sa.String(64), nullable=False),
        sa.Column("receipt_signature", sa.String(64), nullable=False),
        sa.Column("signing_key_id", sa.String(120), nullable=False),
        sa.Column("signing_algorithm", sa.String(40), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "outcome IN ('ATTESTED', 'RETURNED')",
            name="ck_review_receipt_outcome",
        ),
        sa.CheckConstraint(
            "snapshot_checksum ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_review_receipt_snapshot_checksum",
        ),
        sa.CheckConstraint(
            "receipt_checksum ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_review_receipt_checksum",
        ),
        sa.CheckConstraint(
            "receipt_signature ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_review_receipt_signature",
        ),
        sa.UniqueConstraint("snapshot_id", name="uq_review_receipt_snapshot"),
    )
    op.create_index("ix_review_receipts_case_id", "review_receipts", ["case_id"])
    op.create_index("ix_review_receipts_snapshot_id", "review_receipts", ["snapshot_id"])
    op.create_index("ix_review_receipts_reviewer_id", "review_receipts", ["reviewer_id"])

    for table in (
        "assurance_cases",
        "assurance_snapshots",
        "case_evidence_links",
        "assurance_findings",
        "review_receipts",
    ):
        _lockdown(table)
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")


def downgrade() -> None:
    for table in (
        "review_receipts",
        "assurance_findings",
        "case_evidence_links",
        "assurance_snapshots",
        "assurance_cases",
    ):
        op.drop_table(table)
