"""Add deterministic document-date policy and audit-summary metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0011_document_date_policy"
down_revision = "0010_gemini_processing_lease"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    columns = (
        ("document_year", sa.SmallInteger(), True),
        ("is_multi_year", sa.Boolean(), False),
        ("is_audit_summary", sa.Boolean(), False),
        ("audit_year", sa.SmallInteger(), True),
        ("calculated_status", sa.String(length=32), True),
        ("date_verification_status", sa.String(length=32), True),
        ("status_policy_year", sa.SmallInteger(), True),
        ("status_calculated_at", sa.DateTime(), True),
        ("manual_status_override", sa.String(length=32), True),
        ("override_reason", sa.Text(), True),
        ("override_by", sa.Integer(), True),
        ("override_at", sa.DateTime(), True),
        ("override_expires_at", sa.DateTime(), True),
    )
    for name, column_type, nullable in columns:
        if name not in existing:
            if name in {"is_multi_year", "is_audit_summary"}:
                op.add_column("documents", sa.Column(
                    name, column_type, nullable=False, server_default=sa.false()
                ))
                op.alter_column("documents", name, server_default=None)
            elif name == "override_by":
                op.add_column("documents", sa.Column(
                    name, column_type, sa.ForeignKey("users.id"), nullable=nullable
                ))
            else:
                op.add_column("documents", sa.Column(name, column_type, nullable=nullable))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("documents")}
    if "ix_documents_calculated_status" not in indexes:
        op.create_index("ix_documents_calculated_status", "documents", ["calculated_status"])
    if "ix_documents_document_year" not in indexes:
        op.create_index("ix_documents_document_year", "documents", ["document_year"])
    if "ix_documents_audit_summary" not in indexes:
        op.create_index("ix_documents_audit_summary", "documents", ["is_audit_summary", "audit_year"])


def downgrade():
    # Intentionally non-destructive: preserve derived and reviewed metadata.
    pass
