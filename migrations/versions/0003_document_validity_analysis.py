"""Persist content-based validity analysis separately from effective expiry.

Revision ID: 0003_document_validity_analysis
Revises: 0002_integrity_indexes
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_document_validity_analysis"
down_revision = "0002_integrity_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("analysis_expiry_date", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("analysis_issue_date", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("analysis_validity_status", sa.String(length=30), nullable=True))
    op.add_column("documents", sa.Column("analysis_validity_source", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("analysis_validity_rule", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("analysis_validity_rule_label", sa.String(length=100), nullable=True))
    op.add_column("documents", sa.Column("analysis_validity_rule_evidence", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("requirement_cycle", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("requirement_source", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("requirement_note", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("analysis_confidence", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("analysis_review_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("documents", sa.Column("previous_expiry_date", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("previous_issue_date", sa.Date(), nullable=True))
    op.alter_column("documents", "analysis_review_required", server_default=None)


def downgrade():
    for name in (
        "previous_issue_date", "previous_expiry_date", "analysis_review_required",
        "analysis_confidence", "requirement_note", "requirement_source",
        "requirement_cycle", "analysis_validity_rule_evidence",
        "analysis_validity_rule_label", "analysis_validity_rule",
        "analysis_validity_source", "analysis_validity_status",
        "analysis_issue_date", "analysis_expiry_date",
    ):
        op.drop_column("documents", name)
