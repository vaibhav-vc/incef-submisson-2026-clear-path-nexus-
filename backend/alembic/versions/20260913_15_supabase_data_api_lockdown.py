"""Keep backend-owned tables private from the Supabase Data API.

Revision ID: 20260913_15
Revises: 20260831_14

The application performs authorization in FastAPI and does not define direct
browser-to-database policies. Supabase exposes the ``public`` schema through
PostgREST by default, so these tables must not inherit API access merely from
schema placement. No permissive RLS policies are invented here.
"""

from alembic import op


revision = "20260913_15"
down_revision = "20260831_14"
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
)


def _if_supabase_role_exists(role: str, sql: str) -> None:
    op.execute(
        f"""
        DO $lockdown$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE '{sql}';
            END IF;
        END
        $lockdown$;
        """
    )


def upgrade() -> None:
    for table in APPLICATION_TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC')
        for role in ("anon", "authenticated"):
            _if_supabase_role_exists(
                role,
                f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM {role}',
            )

    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC"
    )

    for role in ("anon", "authenticated"):
        _if_supabase_role_exists(
            role,
            f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {role}",
        )
        # Keep tables and identity sequences introduced by later migrations
        # private unless a future migration deliberately adds an RLS policy.
        _if_supabase_role_exists(
            role,
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role}",
        )
        _if_supabase_role_exists(
            role,
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {role}",
        )


def downgrade() -> None:
    # Disabling RLS restores the pre-migration table behavior for the owner.
    # Revoked Supabase grants intentionally remain revoked: silently restoring
    # broad Data API privileges on downgrade would be an unsafe side effect.
    for table in APPLICATION_TABLES:
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
