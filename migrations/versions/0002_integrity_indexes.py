"""Add operational indexes for common ERP queries.

Revision ID: 0002_integrity_indexes
Revises: 0001_schema_baseline
Create Date: 2026-08-13
"""

from alembic import op


revision = "0002_integrity_indexes"
down_revision = "0001_schema_baseline"
branch_labels = None
depends_on = None


def upgrade():
    # These indexes are additive and do not alter existing data or semantics.
    # They target the high-frequency filters used by dashboards, expiry lists,
    # notifications and audit history.
    op.create_index("ix_documents_status_expiry", "documents", ["status", "expiry_date"])
    op.create_index("ix_documents_zone_status", "documents", ["zone_id", "status"])
    op.create_index("ix_notifications_ref", "notifications", ["ref_type", "ref_id"])
    op.create_index("ix_notifications_unread", "notifications", ["read_at", "dismissed"])
    op.create_index("ix_audit_log_created", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_tasks_status_due", "tasks", ["status", "due_date"])
    op.create_index("ix_equipment_next_check", "equipment", ["next_check_date", "status"])
    op.create_index("ix_deficiencies_status_due", "deficiencies", ["status", "due_date"])


def downgrade():
    op.drop_index("ix_deficiencies_status_due", table_name="deficiencies")
    op.drop_index("ix_equipment_next_check", table_name="equipment")
    op.drop_index("ix_tasks_status_due", table_name="tasks")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_created", table_name="audit_log")
    op.drop_index("ix_notifications_unread", table_name="notifications")
    op.drop_index("ix_notifications_ref", table_name="notifications")
    op.drop_index("ix_documents_zone_status", table_name="documents")
    op.drop_index("ix_documents_status_expiry", table_name="documents")
