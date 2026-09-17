"""Require an independently declared carriage count for every consist.

Existing rows are conservatively marked unverified because their count is
inferred during migration rather than supplied by an authenticated manifest.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260916_18"
down_revision = "20260915_17"
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
    op.add_column(
        "train_consists",
        sa.Column("expected_carriage_count", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE train_consists AS tc
        SET expected_carriage_count = GREATEST(
            (SELECT COUNT(*) FROM carriage_loads AS cl WHERE cl.consist_id = tc.id),
            1
        ),
        verification_state = 'UNVERIFIED'
        """
    )
    op.alter_column("train_consists", "expected_carriage_count", nullable=False)
    op.create_check_constraint(
        "ck_train_consist_expected_count_positive",
        "train_consists",
        "expected_carriage_count > 0",
    )
    op.add_column(
        "route_occupation_windows",
        sa.Column(
            "verification_state",
            sa.String(30),
            nullable=False,
            server_default="UNVERIFIED",
        ),
    )
    op.create_index(
        "ix_route_occupation_windows_verification_state",
        "route_occupation_windows",
        ["verification_state"],
    )
    op.add_column(
        "track_section_policies",
        sa.Column(
            "verification_state",
            sa.String(30),
            nullable=False,
            server_default="UNVERIFIED",
        ),
    )
    op.create_index(
        "ix_track_section_policies_verification_state",
        "track_section_policies",
        ["verification_state"],
    )
    for table in APPLICATION_TABLES:
        _lockdown(table)
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")


def downgrade() -> None:
    op.drop_index(
        "ix_track_section_policies_verification_state",
        table_name="track_section_policies",
    )
    op.drop_column("track_section_policies", "verification_state")
    op.drop_index(
        "ix_route_occupation_windows_verification_state",
        table_name="route_occupation_windows",
    )
    op.drop_column("route_occupation_windows", "verification_state")
    op.drop_constraint(
        "ck_train_consist_expected_count_positive",
        "train_consists",
        type_="check",
    )
    op.drop_column("train_consists", "expected_carriage_count")
