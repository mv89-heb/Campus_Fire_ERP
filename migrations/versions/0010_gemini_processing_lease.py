"""Track Gemini processing leases so interrupted requests can be retried safely.

Revision ID: 0010_gemini_processing_lease
Revises: 0009_seed_initial_catalog
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_gemini_processing_lease"
down_revision = "0009_seed_initial_catalog"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    if "ai_processing_started_at" not in columns:
        op.add_column("documents", sa.Column("ai_processing_started_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    if "ai_processing_started_at" in columns:
        op.drop_column("documents", "ai_processing_started_at")
