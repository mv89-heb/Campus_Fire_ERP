"""Add deterministic document-date policy and audit-summary metadata."""
from alembic import op
import sqlalchemy as sa
import json
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

revision = "0011_document_date_policy"
down_revision = "0010_gemini_processing_lease"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    columns = (
        ("document_year", sa.SmallInteger(), True),
        ("is_multi_year", sa.Boolean(), False),
        ("is_audit_summary", sa.Boolean(), False),
        ("audit_year", sa.SmallInteger(), True),
        ("calculated_status", sa.String(length=32), True),
        ("date_verification_status", sa.String(length=32), True),
        ("date_reviewed_at", sa.DateTime(), True),
        ("gemini_issue_date", sa.Date(), True),
        ("gemini_expiry_date", sa.Date(), True),
        ("date_extraction_confidence", sa.Float(), True),
        ("date_extraction_source", sa.String(length=32), True),
        ("date_extraction_conflict", sa.Boolean(), False),
        ("status_policy_year", sa.SmallInteger(), True),
        ("status_calculated_at", sa.DateTime(), True),
        ("manual_status_override", sa.String(length=32), True),
        ("override_reason", sa.Text(), True),
        ("override_by", sa.Integer(), True),
        ("override_at", sa.DateTime(), True),
        ("override_expires_at", sa.DateTime(), True),
    )
    for name, column_type, nullable in columns:
        if name not in existing:
            if name in {"is_multi_year", "is_audit_summary", "date_extraction_conflict"}:
                op.add_column("documents", sa.Column(
                    name, column_type, nullable=False, server_default=sa.false()
                ))
                op.alter_column("documents", name, server_default=None)
            elif name == "override_by":
                op.add_column("documents", sa.Column(
                    name, column_type, sa.ForeignKey("users.id"), nullable=nullable
                ))
            else:
                op.add_column("documents", sa.Column(name, column_type, nullable=nullable))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("documents")}
    if "ix_documents_calculated_status" not in indexes:
        op.create_index("ix_documents_calculated_status", "documents", ["calculated_status"])
    if "ix_documents_document_year" not in indexes:
        op.create_index("ix_documents_document_year", "documents", ["document_year"])
    if "ix_documents_audit_summary" not in indexes:
        op.create_index("ix_documents_audit_summary", "documents", ["is_audit_summary", "audit_year"])

    # Backfill derived metadata for existing records without changing source dates/files.
    documents = sa.Table("documents", sa.MetaData(), autoload_with=bind)
    audits = sa.Table("audits", sa.MetaData(), autoload_with=bind)
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    audit_dates = {}
    for row in bind.execute(sa.select(audits.c.id, audits.c.audit_date)):
        audit_dates[row.id] = row.audit_date

    rows = bind.execute(sa.select(
        documents.c.id, documents.c.issue_date, documents.c.expiry_date,
        documents.c.analysis_issue_date, documents.c.analysis_expiry_date,
        documents.c.ai_document_type, documents.c.ai_summary,
        documents.c.ai_actions_json, documents.c.audit_id,
    )).mappings()
    for row in rows:
        issue = row["issue_date"] or row["analysis_issue_date"]
        expiry = row["expiry_date"] or row["analysis_expiry_date"]
        if isinstance(issue, str):
            issue = date.fromisoformat(issue[:10])
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry[:10])
        multi_year = False
        verification = "missing_issue_date"
        if not issue:
            status = "needs_manual_review"
        elif issue > today:
            status, verification = "future_issue_date", "future_issue_date"
        elif expiry and expiry < issue:
            status, verification = "date_conflict", "date_conflict"
        elif expiry and today > expiry:
            status, verification = "expired", "verified"
        elif not expiry:
            status = "old_approval" if issue.year != 2026 else "needs_manual_review"
            verification = "missing_expiry_date"
        else:
            target_year = issue.year + 1
            anniversary = issue.replace(
                year=target_year,
                day=min(issue.day, monthrange(target_year, issue.month)[1]),
            )
            multi_year = expiry > anniversary
            verification = "verified"
            if multi_year:
                status = "expiring_soon" if (expiry - today).days <= 30 else "active"
            elif issue.year != 2026:
                status = "old_approval"
            else:
                status = "expiring_soon" if (expiry - today).days <= 30 else "active"

        metadata = {}
        try:
            metadata = json.loads(row["ai_actions_json"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        text = " ".join(str(value or "") for value in (
            row["ai_document_type"], row["ai_summary"], row["ai_actions_json"]
        )).lower()
        is_audit_summary = any(term in text for term in (
            "סיכום ביקורת", "דוח ביקורת", 'דו"ח ביקורת', "audit report", "inspection report"
        ))
        audit_year = None
        audit_date = metadata.get("audit_date") if isinstance(metadata, dict) else None
        if audit_date:
            try:
                audit_year = date.fromisoformat(str(audit_date)[:10]).year
            except (TypeError, ValueError):
                pass
        linked_audit_date = audit_dates.get(row["audit_id"])
        if not audit_year and linked_audit_date:
            audit_year = linked_audit_date.year if hasattr(linked_audit_date, "year") else date.fromisoformat(str(linked_audit_date)[:10]).year

        bind.execute(documents.update().where(documents.c.id == row["id"]).values(
            document_year=issue.year if issue else None,
            is_multi_year=multi_year,
            is_audit_summary=is_audit_summary,
            audit_year=audit_year,
            calculated_status=status,
            date_verification_status=verification,
            status_policy_year=2026,
            status_calculated_at=datetime.utcnow(),
            date_extraction_source="local_pdf_text" if (row["analysis_issue_date"] or row["analysis_expiry_date"]) else None,
        ))


def downgrade():
    # Intentionally non-destructive: preserve derived and reviewed metadata.
    pass
