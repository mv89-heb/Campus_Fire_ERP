"""Persistent Gemini document-intelligence state."""
from alembic import op
import sqlalchemy as sa

revision = "0005_document_ai"
down_revision = "0004_repair_doc_analysis"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("ai_status", sa.String(20)), ("ai_model", sa.String(80)),
    ("ai_analyzed_at", sa.DateTime()), ("ai_document_type", sa.String(120)),
    ("ai_summary", sa.Text()), ("ai_findings_json", sa.Text()),
    ("ai_actions_json", sa.Text()), ("ai_confidence", sa.Float()), ("ai_error", sa.Text()),
)

def upgrade():
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("documents")}
    for name, typ in _COLUMNS:
        if name in existing:
            continue
        if name == "ai_status":
            op.add_column("documents", sa.Column(name, typ, nullable=False, server_default="not_requested"))
            op.alter_column("documents", name, server_default=None)
        else:
            op.add_column("documents", sa.Column(name, typ, nullable=True))
        existing.add(name)
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("documents")}
    if "ix_documents_ai_status" not in indexes:
        op.create_index("ix_documents_ai_status", "documents", ["ai_status"])
    if "ix_documents_ai_analyzed_at" not in indexes:
        op.create_index("ix_documents_ai_analyzed_at", "documents", ["ai_analyzed_at"])

def downgrade():
    pass
