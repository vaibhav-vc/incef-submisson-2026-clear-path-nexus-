"""Add verifiable engineering-source metadata to route segments.

Revision ID: 20260829_12
Revises: 20260822_11
"""

from alembic import op
import sqlalchemy as sa

revision = "20260829_12"
down_revision = "20260822_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "line_segments",
        sa.Column(
            "engineering_source_type",
            sa.String(length=40),
            nullable=False,
            server_default="SEEDED_BASELINE",
        ),
    )
    op.add_column(
        "line_segments",
        sa.Column("engineering_source_reference", sa.String(length=500)),
    )
    op.add_column(
        "line_segments",
        sa.Column("engineering_checksum", sa.String(length=64)),
    )
    op.add_column(
        "line_segments",
        sa.Column("engineering_certified_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "line_segments",
        sa.Column("engineering_certified_by", sa.String(length=160)),
    )


def downgrade() -> None:
    op.drop_column("line_segments", "engineering_certified_by")
    op.drop_column("line_segments", "engineering_certified_at")
    op.drop_column("line_segments", "engineering_checksum")
    op.drop_column("line_segments", "engineering_source_reference")
    op.drop_column("line_segments", "engineering_source_type")
