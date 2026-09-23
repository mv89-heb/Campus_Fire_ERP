"""Add Gemini worker lifecycle fields.

Revision ID: 0006_document_ai_worker
Revises: 0005_document_ai
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_document_ai_worker"
down_revision = "0005_document_ai"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("documents", sa.Column("ai_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("documents", sa.Column("ai_started_at", sa.DateTime(), nullable=True))
    op.create_index("ix_documents_ai_started_at", "documents", ["ai_started_at"])

def downgrade():
    op.drop_index("ix_documents_ai_started_at", table_name="documents")
    op.drop_column("documents", "ai_started_at")
    op.drop_column("documents", "ai_attempts")
