"""Separate audit summaries from administrative/non-certificate documents."""
from alembic import op
import sqlalchemy as sa
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.document_classification import classify_document
from app.services.document_date_policy_service import calculate_document_status

revision = "0013_document_classification"
down_revision = "0012_date_ocr_edges"
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
    existing = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    if "date_policy_exempt" not in existing:
        op.add_column(
            "documents",
            sa.Column("date_policy_exempt", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    documents = sa.Table("documents", sa.MetaData(), autoload_with=bind)
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    now = datetime.utcnow()

    rows = bind.execute(sa.select(
        documents.c.id,
        documents.c.file_name,
        documents.c.ai_document_type,
        documents.c.ai_actions_json,
        documents.c.issue_date,
        documents.c.expiry_date,
        documents.c.analysis_issue_date,
        documents.c.analysis_expiry_date,
        documents.c.date_reviewed_at,
        documents.c.date_extraction_confidence,
        documents.c.date_extraction_conflict,
    )).mappings()

    for row in rows:
        metadata = {}
        try:
            metadata = json.loads(row["ai_actions_json"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}

        classification = classify_document(
            filename=row["file_name"],
            document_type=row["ai_document_type"],
            document_purpose=metadata.get("document_purpose"),
        )
        is_audit_summary = classification["is_audit_summary"]
        date_policy_exempt = classification["date_policy_exempt"]

        if row["date_reviewed_at"]:
            issue = _parse_date(row["issue_date"])
            expiry = _parse_date(row["expiry_date"])
        else:
            issue = _parse_date(row["issue_date"] or row["analysis_issue_date"])
            expiry = _parse_date(row["expiry_date"] or row["analysis_expiry_date"])

        result = calculate_document_status(
            issue,
            expiry,
            policy_year=2026,
            today=today,
            grace_period_days=0,
            date_extraction_conflict=bool(row["date_extraction_conflict"]),
            date_extraction_confidence=row["date_extraction_confidence"],
            minimum_date_confidence=0.80,
            is_audit_summary=is_audit_summary,
            date_policy_exempt=date_policy_exempt,
        )

        values = {
            "is_audit_summary": is_audit_summary,
            "date_policy_exempt": date_policy_exempt,
            "document_year": issue.year if issue and not is_audit_summary and not date_policy_exempt else None,
            "is_multi_year": bool(result["is_multi_year"]),
            "calculated_status": result["status"],
            "date_verification_status": result["verification"],
            "status_policy_year": 2026,
            "status_calculated_at": now,
        }
        if not is_audit_summary and not date_policy_exempt and result["status"] in {
            "needs_manual_review", "future_issue_date", "date_conflict"
        }:
            values["analysis_review_required"] = True

        bind.execute(
            documents.update().where(documents.c.id == row["id"]).values(**values)
        )


def downgrade():
    # Keep derived classification and policy metadata; never alter source documents.
    pass
