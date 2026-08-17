"""Repair document-analysis columns for production schema drift.

Revision ID: 0004_repair_doc_analysis
Revises: 0003_document_validity_analysis

The short revision identifier is intentional: PostgreSQL/Alembic installations
may have an alembic_version.version_num column limited to VARCHAR(32).
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_repair_doc_analysis"
down_revision = "0003_document_validity_analysis"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("analysis_expiry_date", sa.Date()),
    ("analysis_issue_date", sa.Date()),
    ("analysis_validity_status", sa.String(length=30)),
    ("analysis_validity_source", sa.String(length=50)),
    ("analysis_validity_rule", sa.String(length=50)),
    ("analysis_validity_rule_label", sa.String(length=100)),
    ("analysis_validity_rule_evidence", sa.String(length=255)),
    ("requirement_cycle", sa.String(length=255)),
    ("requirement_source", sa.String(length=255)),
    ("requirement_note", sa.Text()),
    ("analysis_confidence", sa.Float()),
    ("analysis_review_required", sa.Boolean()),
    ("previous_expiry_date", sa.Date()),
    ("previous_issue_date", sa.Date()),
)


def _existing_columns(bind):
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("documents")}


def upgrade():
    bind = op.get_bind()
    existing = _existing_columns(bind)

    for name, column_type in _COLUMNS:
        if name in existing:
            continue

        kwargs = {"nullable": True}
        if name == "analysis_review_required":
            kwargs = {"nullable": False, "server_default": sa.false()}

        op.add_column("documents", sa.Column(name, column_type, **kwargs))

        if name == "analysis_review_required":
            op.alter_column("documents", name, server_default=None)

        existing.add(name)


def downgrade():
    # This migration repairs production drift. It must never delete analysis
    # data during a downgrade.
    pass
