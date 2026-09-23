"""Remove obsolete Gemini worker lifecycle fields.

Revision ID: 0007_remove_document_ai_worker_fields
Revises: 0006_document_ai_worker
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_remove_document_ai_worker_fields"
down_revision = "0006_document_ai_worker"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Jobs left in the old queue/worker states must become manually runnable
    # by the web UI after the architecture switch.
    op.execute(sa.text("UPDATE documents SET ai_status = 'not_requested' WHERE ai_status IN ('queued', 'processing')"))
    columns = {c["name"] for c in sa.inspect(bind).get_columns("documents")}
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("documents")}

    if "ix_documents_ai_started_at" in indexes:
        op.drop_index("ix_documents_ai_started_at", table_name="documents")
    if "ai_started_at" in columns:
        op.drop_column("documents", "ai_started_at")
    if "ai_attempts" in columns:
        op.drop_column("documents", "ai_attempts")


def downgrade():
    op.add_column(
        "documents",
        sa.Column("ai_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("documents", sa.Column("ai_started_at", sa.DateTime(), nullable=True))
    op.create_index("ix_documents_ai_started_at", "documents", ["ai_started_at"])
