"""Persist content-based validity analysis separately from effective expiry."""
from alembic import op
import sqlalchemy as sa

revision = "0003_document_validity_analysis"
down_revision = "0002_integrity_indexes"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("analysis_expiry_date", sa.Date()), ("analysis_issue_date", sa.Date()),
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
    ("previous_expiry_date", sa.Date()), ("previous_issue_date", sa.Date()),
)

def upgrade():
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("documents")}
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
    pass
