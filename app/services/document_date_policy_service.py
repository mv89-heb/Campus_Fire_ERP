"""Deterministic document-date policy and conservative audit/document reconciliation.

OCR and Gemini provide evidence; this module alone applies the policy.
"""
from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.extensions import db
from flask import current_app, has_app_context
from app.models import Audit, Document

DEFAULT_POLICY_YEAR = 2026
DEFAULT_GRACE_DAYS = 0
EXPIRING_SOON_DAYS = 30

STATUS_LABELS = {
    "active": "תקף",
    "expiring_soon": "עומד לפוג בקרוב",
    "expired": "פג תוקף",
    "old_approval": "אישור ישן",
    "needs_manual_review": "דורש בדיקה ידנית",
    "future_issue_date": "תאריך הנפקה עתידי – לא מאושר",
    "date_conflict": "סתירה בתאריכים",
    "grace_period": "בתקופת חסד מאושרת",
}


def today_israel() -> date:
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date()


def add_calendar_years(value: date, years: int) -> date:
    target_year = value.year + years
    return value.replace(
        year=target_year,
        day=min(value.day, monthrange(target_year, value.month)[1]),
    )


def _policy_value(name: str, default: int) -> int:
    try:
        return max(0, int(name if name is not None else default))
    except (TypeError, ValueError):
        return default


def calculate_document_status(
    issue_date: date | None,
    expiry_date: date | None,
    *,
    policy_year: int = DEFAULT_POLICY_YEAR,
    today: date | None = None,
    grace_period_days: int = DEFAULT_GRACE_DAYS,
    date_extraction_conflict: bool = False,
    date_extraction_confidence: float | None = None,
    minimum_date_confidence: float = 0.80,
) -> dict:
    """Return calculated status and reasons without mutating the document."""
    today = today or today_israel()
    grace_period_days = max(0, int(grace_period_days or 0))

    if date_extraction_conflict:
        return {
            "status": "needs_manual_review",
            "verification": "extraction_conflict",
            "is_multi_year": False,
            "reason": "זוהו תאריכים שונים במקורות החילוץ; נדרש אימות מול המסמך המקורי.",
        }
    if date_extraction_confidence is not None and date_extraction_confidence < minimum_date_confidence:
        return {
            "status": "needs_manual_review",
            "verification": "low_date_confidence",
            "is_multi_year": False,
            "reason": "רמת הביטחון בחילוץ התאריכים נמוכה מהסף המאושר.",
        }

    if not issue_date:
        return {
            "status": "needs_manual_review",
            "verification": "missing_issue_date",
            "is_multi_year": False,
            "reason": "לא זוהה תאריך הנפקה מאומת.",
        }

    if issue_date > today:
        return {
            "status": "future_issue_date",
            "verification": "future_issue_date",
            "is_multi_year": False,
            "reason": "תאריך ההנפקה מאוחר מהתאריך הנוכחי.",
        }

    if expiry_date and expiry_date < issue_date:
        return {
            "status": "date_conflict",
            "verification": "date_conflict",
            "is_multi_year": False,
            "reason": "תאריך התפוגה מוקדם מתאריך ההנפקה.",
        }

    if not expiry_date:
        if issue_date.year != int(policy_year):
            return {
                "status": "old_approval",
                "verification": "missing_expiry_date",
                "is_multi_year": False,
                "reason": "המסמך אינו משנת המדיניות ולא הוכח חריג תוקף רב-שנתי.",
            }
        return {
            "status": "needs_manual_review",
            "verification": "missing_expiry_date",
            "is_multi_year": False,
            "reason": "לא זוהה תאריך תפוגה; יש לאמת אם סוג המסמך דורש תאריך כזה.",
        }

    is_multi_year = expiry_date > add_calendar_years(issue_date, 1)

    if today > expiry_date:
        if grace_period_days and today <= expiry_date + timedelta(days=grace_period_days):
            return {
                "status": "grace_period",
                "verification": "verified",
                "is_multi_year": is_multi_year,
                "reason": f"המסמך פג, ונמצא בתקופת חסד מאושרת של {grace_period_days} ימים.",
            }
        return {
            "status": "expired",
            "verification": "verified",
            "is_multi_year": is_multi_year,
            "reason": "תאריך התפוגה חלף.",
        }

    if is_multi_year:
        status = "expiring_soon" if (expiry_date - today).days <= EXPIRING_SOON_DAYS else "active"
        return {
            "status": status,
            "verification": "verified",
            "is_multi_year": True,
            "reason": "אישור רב-שנתי מאומת; תאריך התפוגה טרם חלף.",
        }

    if issue_date.year != int(policy_year):
        return {
            "status": "old_approval",
            "verification": "verified",
            "is_multi_year": False,
            "reason": f"המסמך הונפק בשנת {issue_date.year}, מחוץ לשנת המדיניות {policy_year}, ואינו רב-שנתי.",
        }

    days_left = (expiry_date - today).days
    return {
        "status": "expiring_soon" if days_left <= EXPIRING_SOON_DAYS else "active",
        "verification": "verified",
        "is_multi_year": False,
        "reason": "המסמך הונפק בשנת המדיניות ותאריך התפוגה טרם חלף.",
    }


def document_dates(document):
    """Return effective dates; an explicit manual review may intentionally clear OCR values."""
    if getattr(document, "date_reviewed_at", None):
        return document.issue_date, document.expiry_date
    return (
        document.issue_date or document.analysis_issue_date,
        document.expiry_date or document.analysis_expiry_date,
    )


def apply_document_policy(document, *, policy_year=None, today=None, grace_period_days=None):
    """Persist derived fields while preserving extracted and manually entered dates."""
    from flask import current_app, has_app_context

    if policy_year is None:
        policy_year = current_app.config.get("DOCUMENT_POLICY_YEAR", DEFAULT_POLICY_YEAR) if has_app_context() else DEFAULT_POLICY_YEAR
    if grace_period_days is None:
        grace_period_days = current_app.config.get("DOCUMENT_GRACE_PERIOD_DAYS", DEFAULT_GRACE_DAYS) if has_app_context() else DEFAULT_GRACE_DAYS

    issue_date, expiry_date = document_dates(document)
    result = calculate_document_status(
        issue_date, expiry_date, policy_year=policy_year,
        today=today, grace_period_days=grace_period_days,
        date_extraction_conflict=bool(getattr(document, "date_extraction_conflict", False)),
        date_extraction_confidence=getattr(document, "date_extraction_confidence", None),
        minimum_date_confidence=(
            current_app.config.get("DOCUMENT_DATE_CONFIDENCE_MIN", 0.80)
            if has_app_context() else 0.80
        ),
    )
    document.document_year = issue_date.year if issue_date else None
    document.is_multi_year = bool(result["is_multi_year"])
    document.calculated_status = result["status"]
    document.date_verification_status = result["verification"]
    document.status_policy_year = int(policy_year)
    document.status_calculated_at = datetime.utcnow()
    if result['status'] in {'needs_manual_review', 'future_issue_date', 'date_conflict'}:
        document.analysis_review_required = True
    return result


def _normalise(value):
    value = (value or "").lower()
    value = re.sub(r"[^\w\u0590-\u05ff]+", " ", value)
    return " ".join(value.split())


_DOCUMENT_TYPE_TERMS = {
    "מטפים": ("מטפים", "מטף"),
    "חשמל": ("חשמל", "חשמלאי"),
    "גילוי אש": ("גילוי אש", "גילוי"),
    "לוחות חשמל": ("לוחות חשמל", "לוח חשמל"),
    "כריזה": ("כריזה", "מסירת הודעות"),
    "ספרינקלרים": ("ספרינקלרים", "מתזים"),
    "שחרור עשן": ("שחרור עשן", "שליטה בעשן"),
    "מערכת גז": ("מערכת גז", "גז"),
    "ציוד כיבוי": ("ציוד כיבוי", "ציוד כיבוי אש"),
}


def _matching_terms(finding_text):
    normalized = _normalise(finding_text)
    return [term for terms in _DOCUMENT_TYPE_TERMS.values() for term in terms
            if _normalise(term) in normalized]


def reconcile_audit_summary(summary_document):
    """Dynamically compare Gemini's explicit missing items with uploaded site documents.

    Only explicit document-type terms are matched. Ambiguous free text is sent
    to manual review; the algorithm never silently closes a finding.
    """
    if not getattr(summary_document, "is_audit_summary", False):
        return {"is_audit_summary": False, "items": [], "counts": {}}

    actions = {}
    try:
        actions = json.loads(summary_document.ai_actions_json or "{}")
    except (TypeError, ValueError):
        pass
    if not isinstance(actions, dict):
        actions = {}

    audit = db.session.get(Audit, summary_document.audit_id) if summary_document.audit_id else None
    site_id = summary_document.site_id or (audit.site_id if audit else None)
    query = Document.query.filter(Document.status.notin_(["deleted", "archived"]), Document.id != summary_document.id)
    if site_id:
        from sqlalchemy import or_
        scope = [Document.site_id == site_id]
        if summary_document.audit_id:
            scope.append(Document.audit_id == summary_document.audit_id)
        if summary_document.zone_id:
            scope.append(Document.zone_id == summary_document.zone_id)
        query = query.filter(or_(*scope))
    elif summary_document.audit_id:
        query = query.filter(Document.audit_id == summary_document.audit_id)
    else:
        return {
            "is_audit_summary": True,
            "audit_year": summary_document.audit_year,
            "items": [],
            "counts": {"needs_manual_review": 1},
            "warning": "סיכום הביקורת עדיין אינו משויך לאתר או לביקורת.",
        }

    documents = query.order_by(Document.uploaded_at.desc(), Document.id.desc()).all()
    items = []
    for missing_item in actions.get("missing_items", []) or []:
        item_text = str(missing_item or "").strip()
        terms = _matching_terms(item_text)
        if not item_text or not terms:
            items.append({
                "finding": item_text,
                "status": "needs_manual_review",
                "matched_documents": [],
                "reason": "לא זוהה סוג מסמך חד-משמעי מתוך ניסוח הממצא.",
            })
            continue

        candidates = []
        for doc in documents:
            haystack = _normalise(" ".join([
                doc.category or "", doc.ai_document_type or "", doc.file_name or "",
                doc.tags or "", doc.notes or "",
            ]))
            if any(_normalise(term) in haystack for term in terms):
                policy_year = current_app.config.get("DOCUMENT_POLICY_YEAR", DEFAULT_POLICY_YEAR) if has_app_context() else DEFAULT_POLICY_YEAR
                grace_days = current_app.config.get("DOCUMENT_GRACE_PERIOD_DAYS", DEFAULT_GRACE_DAYS) if has_app_context() else DEFAULT_GRACE_DAYS
                policy = calculate_document_status(
                    doc.issue_date or doc.analysis_issue_date,
                    doc.expiry_date or doc.analysis_expiry_date,
                    policy_year=policy_year,
                    grace_period_days=grace_days,
                )
                candidates.append({
                    "document_id": doc.id,
                    "file_name": doc.file_name,
                    "calculated_status": policy["status"],
                    "status_label": STATUS_LABELS.get(policy["status"], policy["status"]),
                })

        statuses = {x["calculated_status"] for x in candidates}
        if "active" in statuses or "expiring_soon" in statuses:
            status = "conflict"  # Gemini says missing while an apparently valid certificate exists.
            reason = "סיכום הביקורת מציין חוסר, אך בתיק נמצא מסמך שנראה תקף. נדרשת הכרעה אנושית."
        elif "expired" in statuses:
            status, reason = "matched_expired", "נמצא מסמך מתאים, אך תוקפו פג."
        elif "old_approval" in statuses:
            status, reason = "matched_old", "נמצא מסמך מתאים, אך הוא ישן לפי מדיניות 2026."
        elif candidates:
            status, reason = "needs_manual_review", "נמצאו מסמכים מועמדים שאינם מאושרים כתקפים."
        else:
            status, reason = "missing_document", "לא נמצא בתיק מסמך מתאים שהועלה."
        items.append({
            "finding": item_text,
            "status": status,
            "matched_documents": candidates,
            "reason": reason,
        })

    for contradiction in actions.get("contradictions", []) or []:
        contradiction_text = str(contradiction or "").strip()
        terms = _matching_terms(contradiction_text)
        candidates = []
        if terms:
            for doc in documents:
                haystack = _normalise(" ".join([
                    doc.category or "", doc.ai_document_type or "", doc.file_name or "",
                    doc.tags or "", doc.notes or "",
                ]))
                if any(_normalise(term) in haystack for term in terms):
                    policy_year = current_app.config.get("DOCUMENT_POLICY_YEAR", DEFAULT_POLICY_YEAR) if has_app_context() else DEFAULT_POLICY_YEAR
                    grace_days = current_app.config.get("DOCUMENT_GRACE_PERIOD_DAYS", DEFAULT_GRACE_DAYS) if has_app_context() else DEFAULT_GRACE_DAYS
                    policy = calculate_document_status(
                        doc.issue_date or doc.analysis_issue_date,
                        doc.expiry_date or doc.analysis_expiry_date,
                        policy_year=policy_year,
                        grace_period_days=grace_days,
                    )
                    candidates.append({
                        "document_id": doc.id,
                        "file_name": doc.file_name,
                        "calculated_status": policy["status"],
                        "status_label": STATUS_LABELS.get(policy["status"], policy["status"]),
                    })
        items.append({
            "finding": contradiction_text,
            "status": "conflict",
            "matched_documents": candidates,
            "reason": "Gemini זיהה סתירה בסיכום הביקורת; נדרשת בדיקת מנהל גם אם נמצא מסמך תומך.",
        })

    counts = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "is_audit_summary": True,
        "audit_year": summary_document.audit_year or (audit.audit_date.year if audit and audit.audit_date else None),
        "site_id": site_id,
        "documents_checked": len(documents),
        "items": items,
        "counts": counts,
        "evaluated_at": datetime.utcnow().isoformat() + "Z",
    }
