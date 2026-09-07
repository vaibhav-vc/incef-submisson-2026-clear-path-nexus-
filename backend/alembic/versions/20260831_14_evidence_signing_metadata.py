"""Persist the evidence signing key identity and algorithm.

Revision ID: 20260831_14
Revises: 20260829_13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260831_14"
down_revision = "20260829_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "route_decision_snapshots",
        sa.Column("evidence_root_key_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "route_decision_snapshots",
        sa.Column("evidence_root_algorithm", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("route_decision_snapshots", "evidence_root_algorithm")
    op.drop_column("route_decision_snapshots", "evidence_root_key_id")
