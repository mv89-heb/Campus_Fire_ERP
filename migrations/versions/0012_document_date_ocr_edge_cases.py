"""Correct OCR-impossible dates and detect audit summaries by filename."""
from alembic import op
import sqlalchemy as sa
import json
from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

revision = "0012_document_date_ocr_edge_cases"
down_revision = "0011_document_date_policy"
branch_labels = None
depends_on = None


def _parse_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return value


def upgrade():
    bind = op.get_bind()
    documents = sa.Table("documents", sa.MetaData(), autoload_with=bind)
    audits = sa.Table("audits", sa.MetaData(), autoload_with=bind)
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    audit_dates = {row.id: row.audit_date for row in bind.execute(sa.select(audits.c.id, audits.c.audit_date))}

    rows = bind.execute(sa.select(
        documents.c.id, documents.c.file_name,
        documents.c.issue_date, documents.c.expiry_date,
        documents.c.analysis_issue_date, documents.c.analysis_expiry_date,
        documents.c.ai_document_type, documents.c.ai_summary,
        documents.c.ai_actions_json, documents.c.audit_id, documents.c.audit_year,
    )).mappings()

    for row in rows:
        issue = _parse_date(row["issue_date"] or row["analysis_issue_date"])
        expiry = _parse_date(row["expiry_date"] or row["analysis_expiry_date"])
        multi_year = False
        if issue and expiry and issue.year >= 1900 and expiry.year >= 1900:
            anniversary_year = issue.year + 1
            anniversary = issue.replace(
                year=anniversary_year,
                day=min(issue.day, monthrange(anniversary_year, issue.month)[1]),
            )
            multi_year = expiry > anniversary

        if not issue:
            status, verification = "needs_manual_review", "missing_issue_date"
        elif issue.year > today.year or issue > today:
            status, verification = "future_issue_date", "future_issue_date"
        elif issue.year < 1900 or (expiry and expiry.year < 1900):
            status, verification = "needs_manual_review", "implausible_date"
            multi_year = False
        elif expiry and expiry < issue:
            status, verification = "date_conflict", "date_conflict"
        elif expiry and today > expiry:
            status, verification = "expired", "verified"
        elif not expiry:
            status = "old_approval" if issue.year != 2026 else "needs_manual_review"
            verification = "missing_expiry_date"
        elif multi_year:
            status = "expiring_soon" if (expiry - today).days <= 30 else "active"
            verification = "verified"
        elif issue.year != 2026:
            status, verification = "old_approval", "verified"
        else:
            status = "expiring_soon" if (expiry - today).days <= 30 else "active"
            verification = "verified"

        metadata = {}
        try:
            metadata = json.loads(row["ai_actions_json"] or "{}")
        except (TypeError, ValueError):
            metadata = {}

        classification_text = " ".join(str(value or "") for value in (
            row["file_name"], row["ai_document_type"], row["ai_summary"], row["ai_actions_json"]
        )).lower()
        is_audit_summary = any(term in classification_text for term in (
            "סיכום ביקורת", "דוח ביקורת", 'דו"ח ביקורת', "audit report", "inspection report"
        ))

        audit_year = row["audit_year"]
        audit_date = metadata.get("audit_date") if isinstance(metadata, dict) else None
        if not audit_year and audit_date:
            try:
                audit_year = _parse_date(str(audit_date)).year
            except (TypeError, ValueError):
                pass
        linked_audit_date = audit_dates.get(row["audit_id"])
        if not audit_year and linked_audit_date:
            audit_year = _parse_date(linked_audit_date).year

        values = {
            "document_year": issue.year if issue else None,
            "is_multi_year": multi_year,
            "is_audit_summary": is_audit_summary,
            "audit_year": audit_year,
            "calculated_status": status,
            "date_verification_status": verification,
            "status_policy_year": 2026,
            "status_calculated_at": datetime.utcnow(),
        }
        if verification in {"missing_issue_date", "implausible_date", "future_issue_date", "date_conflict"}:
            values["analysis_review_required"] = True
        bind.execute(documents.update().where(documents.c.id == row["id"]).values(**values))


def downgrade():
    # Derived metadata corrections are intentionally retained; no source data is changed.
    pass
