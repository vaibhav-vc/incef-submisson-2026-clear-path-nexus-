"""Persist signed evidence roots and human approval receipts.

Revision ID: 20260829_13
Revises: 20260829_12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260829_13"
down_revision = "20260829_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provenance_records",
        sa.Column("integrity_checksum", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "route_decision_snapshots",
        sa.Column("evidence_root_checksum", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "route_decision_snapshots",
        sa.Column("evidence_root_signature", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "generated_routes",
        sa.Column("approved_by_user_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "generated_routes",
        sa.Column("approved_by_role", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "generated_routes",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generated_routes",
        sa.Column("approval_evidence_checksum", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_generated_routes_approval_evidence_checksum",
        "generated_routes",
        ["approval_evidence_checksum"],
    )
    op.execute(
        """
        INSERT INTO data_sources (
            id, key, display_name, category, provider_domain, reference_url,
            license_name, attribution_text, authority_level, official,
            free_for_mvp, requires_key, default_fresh_seconds,
            aging_after_seconds, stale_after_seconds, enabled, limitations
        ) VALUES (
            '10000000-0000-0000-0000-000000000013',
            'imported_engineering',
            'Authorized Engineering Document Import',
            'RAIL_ENGINEERING',
            NULL,
            NULL,
            'Operator-supplied authorization',
            'Imported document identity and certifier are retained in each evidence record.',
            'AUTHORIZED_DOCUMENT',
            FALSE,
            FALSE,
            FALSE,
            NULL,
            NULL,
            NULL,
            TRUE,
            '{"requires_checksum": true, "requires_certifier": true}'::jsonb
        ) ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM data_sources WHERE id = '10000000-0000-0000-0000-000000000013'"
    )
    op.drop_index("ix_generated_routes_approval_evidence_checksum", table_name="generated_routes")
    op.drop_column("generated_routes", "approval_evidence_checksum")
    op.drop_column("generated_routes", "approved_at")
    op.drop_column("generated_routes", "approved_by_role")
    op.drop_column("generated_routes", "approved_by_user_id")
    op.drop_column("route_decision_snapshots", "evidence_root_signature")
    op.drop_column("route_decision_snapshots", "evidence_root_checksum")
    op.drop_column("provenance_records", "integrity_checksum")
