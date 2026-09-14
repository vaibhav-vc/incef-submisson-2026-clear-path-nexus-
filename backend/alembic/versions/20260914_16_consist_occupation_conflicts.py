"""Persist carriage manifests and evidence-backed section occupations.

The tables are backend-owned and immediately locked down for Supabase's Data
API. No seeded values are inserted; callers must provide source identity,
timestamps, and SHA-256 checksums for every operational record.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260914_16"
down_revision = "20260913_15"
branch_labels = None
depends_on = None

# Full backend-owned table inventory is repeated here so a future migration
# can be audited against the latest lockdown policy without importing an
# Alembic module that may have a different database state.
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
        "train_consists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("train_schedules.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=False),
        sa.Column("manifest_checksum", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_state", sa.String(30), nullable=False, server_default="UNVERIFIED"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "manifest_checksum ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_train_consist_checksum",
        ),
    )
    op.create_index("ix_train_consists_schedule_id", "train_consists", ["schedule_id"], unique=True)
    op.create_index("ix_train_consists_user_id", "train_consists", ["user_id"])
    op.create_index(
        "ix_train_consists_owner_observed", "train_consists", ["user_id", "observed_at"]
    )

    op.create_table(
        "carriage_loads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "consist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("train_consists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position_in_train", sa.Integer(), nullable=False),
        sa.Column("carriage_identifier", sa.String(80), nullable=False),
        sa.Column("carriage_type", sa.String(80), nullable=False),
        sa.Column("tare_weight_tons", sa.Numeric(10, 3), nullable=False),
        sa.Column("cargo_weight_tons", sa.Numeric(10, 3), nullable=False),
        sa.Column("gross_weight_tons", sa.Numeric(10, 3), nullable=False),
        sa.Column("length_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("width_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("height_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("axle_count", sa.Integer(), nullable=False),
        sa.Column("brake_percentage", sa.Numeric(8, 3)),
        sa.Column("load_distribution", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("hazardous_material_class", sa.String(40)),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("position_in_train > 0", name="ck_carriage_position_positive"),
        sa.CheckConstraint("tare_weight_tons > 0", name="ck_carriage_tare_positive"),
        sa.CheckConstraint("cargo_weight_tons >= 0", name="ck_carriage_cargo_nonnegative"),
        sa.CheckConstraint("gross_weight_tons > 0", name="ck_carriage_gross_positive"),
        sa.CheckConstraint("length_m > 0", name="ck_carriage_length_positive"),
        sa.CheckConstraint("width_m > 0", name="ck_carriage_width_positive"),
        sa.CheckConstraint("height_m > 0", name="ck_carriage_height_positive"),
        sa.CheckConstraint("axle_count > 0", name="ck_carriage_axles_positive"),
        sa.CheckConstraint(
            "brake_percentage IS NULL OR brake_percentage >= 0",
            name="ck_carriage_brake_nonnegative",
        ),
        sa.CheckConstraint(
            "source_checksum ~ '^[0-9A-Fa-f]{64}$'", name="ck_carriage_source_checksum"
        ),
        sa.UniqueConstraint("consist_id", "position_in_train", name="uq_carriage_consist_position"),
    )
    op.create_index("ix_carriage_loads_consist_id", "carriage_loads", ["consist_id"])
    op.create_index(
        "ix_carriage_loads_consist_position", "carriage_loads", ["consist_id", "position_in_train"]
    )

    op.create_table(
        "route_occupation_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("train_schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "segment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("line_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_in_route", sa.Integer(), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("train_length_m", sa.Numeric(10, 3), nullable=False),
        sa.Column("expected_speed_kmh", sa.Numeric(8, 3)),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("sequence_in_route >= 0", name="ck_occupation_sequence_nonnegative"),
        sa.CheckConstraint("entry_time < exit_time", name="ck_occupation_time_order"),
        sa.CheckConstraint("train_length_m > 0", name="ck_occupation_length_positive"),
        sa.CheckConstraint(
            "expected_speed_kmh IS NULL OR expected_speed_kmh > 0",
            name="ck_occupation_speed_positive",
        ),
        sa.CheckConstraint(
            "source_checksum ~ '^[0-9A-Fa-f]{64}$'", name="ck_occupation_source_checksum"
        ),
        sa.UniqueConstraint("schedule_id", "sequence_in_route", name="uq_occupation_schedule_sequence"),
    )
    op.create_index("ix_occupation_schedule_id", "route_occupation_windows", ["schedule_id"])
    op.create_index("ix_occupation_segment_id", "route_occupation_windows", ["segment_id"])
    op.create_index(
        "ix_occupation_segment_window",
        "route_occupation_windows",
        ["segment_id", "entry_time", "exit_time"],
    )

    op.create_table(
        "track_section_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "segment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("line_segments.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("single_track", sa.Boolean(), nullable=False),
        sa.Column("minimum_headway_seconds", sa.Numeric(12, 3)),
        sa.Column("policy_version", sa.String(80)),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "minimum_headway_seconds IS NULL OR minimum_headway_seconds >= 0",
            name="ck_policy_headway_nonnegative",
        ),
        sa.CheckConstraint("source_checksum ~ '^[0-9A-Fa-f]{64}$'", name="ck_policy_checksum"),
    )
    op.create_index("ix_track_section_policies_segment_id", "track_section_policies", ["segment_id"], unique=True)

    for table in APPLICATION_TABLES:
        _lockdown(table)
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")


def downgrade() -> None:
    for table in (
        "track_section_policies",
        "route_occupation_windows",
        "carriage_loads",
        "train_consists",
    ):
        op.drop_table(table)
