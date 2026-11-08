"""Conservative document classification shared by local analysis, Gemini and migrations."""

import re


_AUDIT_FILENAME_MARKERS = (
    "סיכום ביקורת",
    "דוח ליקויים",
    'דו"ח ליקויים',
    "audit summary",
    "inspection summary",
    "audit findings",
    "inspection findings",
)
_AUDIT_REPORT_MARKERS = (
    "סיכום ביקורת",
    "דוח ליקויים",
    'דו"ח ליקויים',
    "audit summary",
    "inspection summary",
    "audit findings report",
    "inspection findings report",
)
_ADMINISTRATIVE_MARKERS = (
    "שובר אגרת",
    "שובר אגרה",
    "דרישת תשלום אגרה",
    "הצעת מחיר",
    "הזמנת עבודה",
    "חשבונית",
    "קבלה",
    "invoice",
    "receipt",
    "quotation",
    "purchase order",
)
_CERTIFICATE_MARKERS = (
    "טופס",
    "אישור",
    "תחזוקה",
    "תחזוקת",
    "בדיקה תקופתית",
    "בדיקת תקינות",
    "בדיקת",
    "דוח בדיקה",
    'דו"ח בדיקה',
    "certificate",
    "approval",
    "maintenance",
)


def _normalize(value):
    value = str(value or "").lower().replace("׳", "'").replace("״", '"')
    value = re.sub(r"[^\w\u0590-\u05ff]+", " ", value)
    return " ".join(value.split())


def _contains_any(value, markers):
    normalized = _normalize(value)
    return any(_normalize(marker) in normalized for marker in markers)


def classify_document(filename=None, document_type=None, document_purpose=None, body_text=None):
    """Classify documents without mistaking incidental audit wording for an audit summary.

    Only explicit summary filenames/types or a clear findings-report description
    qualify as audit summaries. Payment/administrative documents are separately
    marked as exempt from certificate-expiry policy.
    """
    filename_text = _normalize(str(filename or "").replace("\\", "/").rsplit("/", 1)[-1])
    type_text = _normalize(document_type)
    purpose_text = _normalize(document_purpose)
    body = _normalize(body_text)
    metadata_text = " ".join(part for part in (type_text, purpose_text) if part)

    if _contains_any(filename_text, _AUDIT_FILENAME_MARKERS):
        return {
            "is_audit_summary": True,
            "date_policy_exempt": False,
            "reason": "explicit_audit_summary_filename",
        }

    if _contains_any(metadata_text, _ADMINISTRATIVE_MARKERS) or _contains_any(filename_text, _ADMINISTRATIVE_MARKERS) or _contains_any(body, _ADMINISTRATIVE_MARKERS):
        return {
            "is_audit_summary": False,
            "date_policy_exempt": True,
            "reason": "administrative_document_not_certificate",
        }

    if _contains_any(metadata_text, _AUDIT_REPORT_MARKERS):
        # A maintenance certificate can mention an inspection report without
        # itself being the authority's consolidated audit/finding summary.
        if _contains_any(type_text, _CERTIFICATE_MARKERS):
            return {
                "is_audit_summary": False,
                "date_policy_exempt": False,
                "reason": "certificate_or_maintenance_report",
            }
        return {
            "is_audit_summary": True,
            "date_policy_exempt": False,
            "reason": "explicit_audit_findings_document_type",
        }

    if _contains_any(body, _AUDIT_REPORT_MARKERS) or ("ליקויים" in body and "ביקורת" in body):
        if not _contains_any(type_text, _CERTIFICATE_MARKERS):
            return {
                "is_audit_summary": True,
                "date_policy_exempt": False,
                "reason": "explicit_audit_findings_body",
            }

    return {
        "is_audit_summary": False,
        "date_policy_exempt": False,
        "reason": "certificate_or_unclassified_document",
    }
