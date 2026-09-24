"""Add document links to site, audit and supplier.

Revision ID: 0008_document_links
Revises: 0007_remove_ai_worker
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_document_links"
down_revision = "0007_remove_ai_worker"
branch_labels = None
depends_on = None


def upgrade():
    # batch_alter_table keeps this migration portable to SQLite (CI/test) and
    # PostgreSQL (production). SQLite cannot add a foreign-key constraint to
    # an existing table using plain ALTER TABLE.
    with op.batch_alter_table("documents", schema=None) as batch:
        batch.add_column(sa.Column("site_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("audit_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("supplier_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_documents_site_id", "sites", ["site_id"], ["id"])
        batch.create_foreign_key("fk_documents_audit_id", "audits", ["audit_id"], ["id"])
        batch.create_foreign_key("fk_documents_supplier_id", "suppliers", ["supplier_id"], ["id"])
        batch.create_index("ix_documents_site_id", ["site_id"])
        batch.create_index("ix_documents_audit_id", ["audit_id"])
        batch.create_index("ix_documents_supplier_id", ["supplier_id"])

def downgrade():
    op.drop_index("ix_documents_supplier_id", table_name="documents")
    op.drop_index("ix_documents_audit_id", table_name="documents")
    op.drop_index("ix_documents_site_id", table_name="documents")
    op.drop_constraint("fk_documents_supplier_id", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_audit_id", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_site_id", "documents", type_="foreignkey")
    op.drop_column("documents", "supplier_id")
    op.drop_column("documents", "audit_id")
    op.drop_column("documents", "site_id")
