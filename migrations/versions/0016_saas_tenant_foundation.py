"""Introduce the first organization and membership records without losing legacy data.

This is a compatibility foundation only. Tenant request scoping and customer
self-service remain disabled until the follow-up isolation release is deployed.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_saas_tenant_foundation"
down_revision = "0015_fire_form_field_mapping"
branch_labels = None
depends_on = None

LEGACY_ORGANIZATION_ID = "00000000-0000-4000-8000-000000000001"
TENANT_TABLES = ["zones","system_requirements","documents","sites","buildings","floors","areas","suppliers","equipment","tasks","audits","deficiencies","document_history","notifications","audit_log","fire_form_templates"]


def upgrade():
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_membership_organization", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_membership_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_membership"),
    )
    op.create_index("ix_organization_memberships_organization_id", "organization_memberships", ["organization_id"])
    op.create_index("ix_organization_memberships_user_id", "organization_memberships", ["user_id"])

    bind = op.get_bind()
    op.execute(
        sa.text(
            "INSERT INTO organizations (id, name, slug, status, created_at) "
            "VALUES (:id, :name, :slug, 'active', CURRENT_TIMESTAMP)"
        ).bindparams(
            id=LEGACY_ORGANIZATION_ID,
            name="הארגון הקיים",
            slug="legacy-organization",
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO organization_memberships (organization_id, user_id, role, status, created_at) "
            "SELECT :organization_id, id, role, 'active', CURRENT_TIMESTAMP FROM users"
        ).bindparams(organization_id=LEGACY_ORGANIZATION_ID)
    )

    for table_name in TENANT_TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "organization_id",
                sa.String(length=36),
                nullable=False,
                server_default=LEGACY_ORGANIZATION_ID,
            ),
        )
        op.create_index(
            f"ix_{table_name}_organization_id",
            table_name,
            ["organization_id"],
        )
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(
                f"fk_{table_name}_organization",
                table_name,
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def downgrade():
    bind = op.get_bind()
    for table_name in reversed(TENANT_TABLES):
        if bind.dialect.name != "sqlite":
            op.drop_constraint(
                f"fk_{table_name}_organization",
                table_name,
                type_="foreignkey",
            )
        op.drop_index(f"ix_{table_name}_organization_id", table_name=table_name)
        op.drop_column(table_name, "organization_id")

    op.drop_index("ix_organization_memberships_user_id", table_name="organization_memberships")
    op.drop_index("ix_organization_memberships_organization_id", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
