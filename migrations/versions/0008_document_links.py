"""Add document links to site, audit and supplier.

Revision ID: 0008_document_links
Revises: 0007_remove_document_ai_worker_fields
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_document_links"
down_revision = "0007_remove_document_ai_worker_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("site_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("audit_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_documents_site_id", "documents", "sites", ["site_id"], ["id"])
    op.create_foreign_key("fk_documents_audit_id", "documents", "audits", ["audit_id"], ["id"])
    op.create_foreign_key("fk_documents_supplier_id", "documents", "suppliers", ["supplier_id"], ["id"])
    op.create_index("ix_documents_site_id", "documents", ["site_id"])
    op.create_index("ix_documents_audit_id", "documents", ["audit_id"])
    op.create_index("ix_documents_supplier_id", "documents", ["supplier_id"])


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
