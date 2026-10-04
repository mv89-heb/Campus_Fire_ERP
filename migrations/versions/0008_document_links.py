"""Add document links to site, audit and supplier."""
from alembic import op
import sqlalchemy as sa

revision = "0008_document_links"
down_revision = "0007_remove_ai_worker"
branch_labels = None
depends_on = None

_COLUMNS = (("site_id", "sites"), ("audit_id", "audits"), ("supplier_id", "suppliers"))

def upgrade():
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("documents")}
    missing = [(name, table) for name, table in _COLUMNS if name not in existing]
    if not missing:
        return
    with op.batch_alter_table("documents", schema=None) as batch:
        for name, _table in missing:
            batch.add_column(sa.Column(name, sa.Integer(), nullable=True))
        for name, table in missing:
            batch.create_foreign_key(f"fk_documents_{name}", table, [name], ["id"])
        indexes = {i["name"] for i in sa.inspect(bind).get_indexes("documents")}
        for name, _table in missing:
            index_name = f"ix_documents_{name}"
            if index_name not in indexes:
                batch.create_index(index_name, [name])

def downgrade():
    pass
