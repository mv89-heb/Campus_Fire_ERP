"""Introduce organization membership and tenant keys without losing legacy data.

The upgrade is idempotent so it also tolerates development/test databases where
SQLAlchemy create_all() may already have created some or all of the new schema.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_saas_tenant_foundation"
down_revision = "0015_fire_form_field_mapping"
branch_labels = None
depends_on = None

LEGACY_ORGANIZATION_ID = "00000000-0000-4000-8000-000000000001"
TENANT_TABLES = ["zones","system_requirements","documents","sites","buildings","floors","areas","suppliers","equipment","tasks","audits","deficiencies","document_history","notifications","audit_log","fire_form_templates"]


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _ensure_organization_tables(bind):
    tables = _table_names(bind)
    if "organizations" not in tables:
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

    tables = _table_names(bind)
    if "organization_memberships" not in tables:
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

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("organization_memberships")}
    if "ix_organization_memberships_organization_id" not in indexes:
        op.create_index("ix_organization_memberships_organization_id", "organization_memberships", ["organization_id"])
    if "ix_organization_memberships_user_id" not in indexes:
        op.create_index("ix_organization_memberships_user_id", "organization_memberships", ["user_id"])


def upgrade():
    bind = op.get_bind()
    _ensure_organization_tables(bind)

    bind.execute(
        sa.text(
            "INSERT INTO organizations (id, name, slug, status, created_at) "
            "VALUES (:id, :name, :slug, 'active', CURRENT_TIMESTAMP) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": LEGACY_ORGANIZATION_ID,
            "name": "הארגון הקיים",
            "slug": "legacy-organization",
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO organization_memberships (organization_id, user_id, role, status, created_at) "
            "SELECT :organization_id, users.id, users.role, 'active', CURRENT_TIMESTAMP "
            "FROM users WHERE NOT EXISTS ("
            "SELECT 1 FROM organization_memberships m "
            "WHERE m.organization_id = :organization_id AND m.user_id = users.id"
            ")"
        ),
        {"organization_id": LEGACY_ORGANIZATION_ID},
    )

    for table_name in TENANT_TABLES:
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "organization_id" not in columns:
            op.add_column(
                table_name,
                sa.Column(
                    "organization_id",
                    sa.String(length=36),
                    nullable=False,
                    server_default=LEGACY_ORGANIZATION_ID,
                ),
            )
        bind.execute(
            sa.text(
                f'UPDATE "{table_name}" SET organization_id = :organization_id '
                "WHERE organization_id IS NULL"
            ),
            {"organization_id": LEGACY_ORGANIZATION_ID},
        )

        indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
        index_name = f"ix_{table_name}_organization_id"
        if index_name not in indexes:
            op.create_index(index_name, table_name, ["organization_id"])

        if bind.dialect.name != "sqlite":
            foreign_keys = sa.inspect(bind).get_foreign_keys(table_name)
            has_organization_fk = any(
                item.get("constrained_columns") == ["organization_id"]
                and item.get("referred_table") == "organizations"
                for item in foreign_keys
            )
            if not has_organization_fk:
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
        if "organization_id" not in {
            column["name"] for column in sa.inspect(bind).get_columns(table_name)
        }:
            continue
        if bind.dialect.name != "sqlite":
            foreign_keys = sa.inspect(bind).get_foreign_keys(table_name)
            for foreign_key in foreign_keys:
                if (
                    foreign_key.get("constrained_columns") == ["organization_id"]
                    and foreign_key.get("referred_table") == "organizations"
                ):
                    op.drop_constraint(foreign_key["name"], table_name, type_="foreignkey")
        indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
        index_name = f"ix_{table_name}_organization_id"
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, "organization_id")

    tables = _table_names(bind)
    if "organization_memberships" in tables:
        indexes = {item["name"] for item in sa.inspect(bind).get_indexes("organization_memberships")}
        for index_name in ("ix_organization_memberships_user_id", "ix_organization_memberships_organization_id"):
            if index_name in indexes:
                op.drop_index(index_name, table_name="organization_memberships")
        op.drop_table("organization_memberships")
    if "organizations" in _table_names(bind):
        op.drop_table("organizations")
