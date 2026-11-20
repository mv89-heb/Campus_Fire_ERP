"""Enforce PostgreSQL row-level security for tenant-owned business data."""
from alembic import op
import sqlalchemy as sa

revision = "0017_force_tenant_rls"
down_revision = "0016_saas_tenant_foundation"
branch_labels = None
depends_on = None

RUNTIME_ROLE = "campus_fire_runtime"
TENANT_TABLES = ["zones","system_requirements","documents","sites","buildings","floors","areas","suppliers","equipment","tasks","audits","deficiencies","document_history","notifications","audit_log","fire_form_templates"]


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    runtime_role_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": RUNTIME_ROLE},
    ).first()
    if not runtime_role_exists:
        raise RuntimeError(
            "Required least-privilege PostgreSQL role campus_fire_runtime is missing; "
            "provision it before applying tenant RLS."
        )

    organization_predicate = (
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::varchar"
    )
    for table_name in TENANT_TABLES:
        if table_name == "documents":
            read_predicate = (
                "(" + organization_predicate +
                " OR id = NULLIF(current_setting('app.allowed_document_id', true), '')::integer)"
            )
        else:
            read_predicate = organization_predicate

        policy_name = f"{table_name}_organization_isolation"
        op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"'))
        op.execute(sa.text(
            f'CREATE POLICY "{policy_name}" ON "{table_name}" '
            f'FOR ALL TO "{RUNTIME_ROLE}" '
            f'USING ({read_predicate}) '
            f'WITH CHECK ({organization_predicate})'
        ))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table_name in TENANT_TABLES:
        policy_name = f"{table_name}_organization_isolation"
        op.execute(sa.text(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY'))
