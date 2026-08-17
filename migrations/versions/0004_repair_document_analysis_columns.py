"""Repair document-analysis columns for databases that were stamped ahead.

Revision ID: 0004_repair_document_analysis_columns
Revises: 0003_document_validity_analysis

The application model already contains the analysis fields and migration 0003
creates them on a clean database. Some production databases can nevertheless
have an Alembic revision recorded without the physical columns being present.
This migration is intentionally idempotent and repairs that drift without
changing or deleting existing document data.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_repair_document_analysis_columns"
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
            # Existing rows must receive a deterministic safe value while the
            # repair is applied. Remove the server default immediately after.
            kwargs = {"nullable": False, "server_default": sa.false()}

        op.add_column(
            "documents",
            sa.Column(name, column_type, **kwargs),
        )

        if name == "analysis_review_required":
            op.alter_column(
                "documents",
                name,
                server_default=None,
            )

        existing.add(name)


def downgrade():
    # Do not remove columns during downgrade: this migration is a production
    # drift repair and deleting analysis data would be unsafe. Revision 0003
    # remains responsible for the normal schema lifecycle.
    pass
