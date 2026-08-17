"""Content-aware analysis of fire-safety PDF documents.

The document itself is the primary source for dates. File names are used only
as supporting evidence for form/zone classification. Expiry is calculated as
one calendar year from a reliable inspection/issue date unless the document
contains an explicit expiry/valid-until date.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})(?!\d)")
_FORM_RE = re.compile(r"טופס\s*(?:מס[\u05f3']?\s*)?(\d{1,2})", re.I)

FORM_TYPES = {
    1: ("ציוד כיבוי", "בדיקת ציוד כיבוי אש"),
    2: ("תחזוקת מטפים", "תחזוקת מטפים"),
    3: ("חשמל", "בדיקת מערכת חשמל ותאורת חירום"),
    4: ("גילוי אש", "תחזוקת מערכת גילוי אש"),
    5: ("לוחות חשמל", "מערכת כיבוי בלוחות חשמל"),
    6: ("כריזה", "מערכת מסירת הודעות/כריזת חירום"),
    7: ("ספרינקלרים", "מערכת כיבוי אוטומטית בספרינקלרים"),
    10: ("שחרור עשן", "מערכת שליטה בעשן"),
    13: ("תיק שטח", "תיק שטח"),
    14: ("הדרכת עובדים", "הדרכת עובדים"),
    16: ("מטבח", "מערכת פליטה מבישול מסחרי"),
    18: ("מערכת גז", "בדיקת תקינות מערכת גז"),
}

# Explicit expiry language has the highest priority.
_EXPLICIT_EXPIRY = (
    "תוקף עד", "בתוקף עד", "תקף עד", "תוקף:", "תוקף ",
    "בתוקף:", "תקף:", "valid until", "valid through", "expires",
    "expiry", "expiration",
)

# Inspection/issue language. These are intentionally more specific than a
# generic search for the words "בדיק" or "תאריך".
_INSPECTION = (
    "תאריך בדיקה", "מועד בדיקה", "תאריך ביצוע", "מועד ביצוע",
    "תאריך תחזוקה", "מועד תחזוקה", "תאריך ביקורת", "מועד ביקורת",
    "נבדק בתאריך", "נבדקה בתאריך", "נבדק ביום", "נבדקה ביום",
    "בוצע בתאריך", "בוצעה בתאריך", "בוצע ביום", "בוצעה ביום",
    "תאריך אישור", "מועד אישור", "תאריך הנפקה", "מועד הנפקה",
    "הונפק בתאריך", "הונפק ביום", "תאריך מילוי", "מועד מילוי",
)

_NEGATIVE = (
    "תוקף", "בתוקף", "תקף עד", "רישיון", "היתר", "הבדיקה הבאה",
    "בדיקה הבאה", "תחזוקה הבאה", "התחזוקה הבאה", "ביקורת הבאה",
)


def _today_israel() -> date:
    try:
        return datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    except Exception:
        return date.today()


def add_one_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        # 29/02 -> 28/02 in the following year.
        return value.replace(year=value.year + 1, day=28)


def validity_status(expiry_date: date | None, today: date | None = None) -> str:
    if expiry_date is None:
        return "needs_review"
    today = today or _today_israel()
    if today >= expiry_date:
        return "expired"
    days = (expiry_date - today).days
    if days <= 14:
        return "critical"
    if days <= 30:
        return "warning"
    return "valid"


def _parse_date(match: re.Match) -> date | None:
    day, month, year = (int(x) for x in match.groups())
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _line_contexts(text: str):
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        for match in _DATE_RE.finditer(line):
            value = _parse_date(match)
            if value:
                yield value, line


def extract_dates(text: str) -> list[date]:
    result: list[date] = []
    for value, _ in _line_contexts(text):
        if value not in result:
            result.append(value)
    return result


def extract_explicit_expiry(text: str) -> date | None:
    candidates: list[date] = []
    for value, line in _line_contexts(text):
        low = line.lower()
        if any(token.lower() in low for token in _EXPLICIT_EXPIRY):
            candidates.append(value)
    return min(candidates) if candidates else None


def extract_inspection_date(text: str) -> date | None:
    scored: list[tuple[int, date]] = []
    for value, line in _line_contexts(text):
        low = line.lower()
        score = 0
        for token in _INSPECTION:
            if token.lower() in low:
                score += 10 if "תאריך" in token or "מועד" in token else 7
        if any(token in low for token in _NEGATIVE):
            score -= 20
        if score:
            scored.append((score, value))
    if not scored:
        return None
    # Prefer the strongest semantic label. If several lines have the same
    # label strength, prefer the latest date because forms often contain an
    # old comparison date alongside the current inspection date.
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[0][1]


def detect_form_number(text: str, filename: str = "") -> int | None:
    # Content wins over filename whenever the content explicitly says "טופס N".
    match = _FORM_RE.search(text or "")
    if match:
        return int(match.group(1))
    match = _FORM_RE.search(filename or "")
    if match:
        return int(match.group(1))
    match = re.search(r"(?:^|[/\\])(?:טופס\s*)?(\d{1,2})(?:\s*\([^)]*\))?\.pdf$", filename or "", re.I)
    return int(match.group(1)) if match else None


def detect_zone_code(text: str, filename: str = "") -> str | None:
    combined = f"{text}\n{filename}"
    for code in ("8855-7", "8859-7", "8853-7", "8860-7"):
        if code in combined or code.split("-")[0] in combined:
            return code
    if "אישורי מגורים" in combined or "מגורים" in combined or "פנימייה" in combined:
        return "8855-7"
    if "אישורי מטבח" in combined or "מטבח" in combined or "בישול" in combined:
        return "8859-7"
    if "אולם ספורט" in combined:
        return "8853-7"
    if "בית מדרש" in combined:
        return "8860-7"
    return None


def _extract_text(data: bytes) -> tuple[str, int]:
    import fitz
    with fitz.open(stream=data, filetype="pdf") as document:
        return "\n".join(page.get_text("text") for page in document), len(document)


def analyze_pdf_bytes(data: bytes, filename: str = "") -> dict:
    try:
        text, pages = _extract_text(data)
    except Exception as exc:
        return {
            "status": "needs_review",
            "filename": filename,
            "error": f"PDF text extraction failed: {exc}",
            "text_extracted": False,
            "analysis_notes": "לא ניתן לחלץ טקסט מה-PDF. נדרש OCR/בדיקה ידנית.",
        }

    form = detect_form_number(text, filename)
    category, document_type = FORM_TYPES.get(form, (None, None))
    zone_code = detect_zone_code(text, filename)
    inspection_date = extract_inspection_date(text)
    explicit_expiry = extract_explicit_expiry(text)

    # An explicit expiry is authoritative. Otherwise the user's requested
    # business rule is one calendar year from a reliable inspection/issue date.
    calculated_expiry = add_one_year(inspection_date) if inspection_date else None
    if explicit_expiry:
        effective_expiry = explicit_expiry
        validity_source = "explicit_document_expiry"
    elif calculated_expiry:
        effective_expiry = calculated_expiry
        validity_source = "annual_rule_from_document_date"
    else:
        effective_expiry = None
        validity_source = "unknown"

    if explicit_expiry and calculated_expiry and explicit_expiry != calculated_expiry:
        notes = (
            f"המסמך כולל תוקף מפורש {explicit_expiry.isoformat()}; "
            f"חישוב שנתי מתאריך הבדיקה היה {calculated_expiry.isoformat()}, "
            "ולכן נשמר התוקף המפורש שבמסמך."
        )
    elif effective_expiry:
        notes = (
            "התוקף נקבע מתוכן המסמך: "
            + ("תאריך תוקף מפורש." if explicit_expiry else "שנה קלנדרית מתאריך הבדיקה/ההנפקה.")
        )
    else:
        notes = "לא נמצא בתוכן המסמך תאריך אמין שמאפשר לקבוע תוקף. נדרש עיון ידני."

    confidence = 0.99 if form and explicit_expiry else 0.97 if form and inspection_date else 0.85 if inspection_date else 0.55 if form else 0.25
    status = "analyzed" if effective_expiry else "needs_review"

    return {
        "status": status,
        "filename": filename,
        "form_number": form,
        "category": category,
        "document_type": document_type,
        "zone_code": zone_code,
        "inspection_date": inspection_date,
        "issue_date": inspection_date,
        "explicit_expiry_date": explicit_expiry,
        "calculated_expiry_date": calculated_expiry,
        "expiry_date": effective_expiry,
        "validity_source": validity_source,
        "validity_status": validity_status(effective_expiry),
        "confidence": confidence,
        "analysis_notes": notes,
        "pages": pages,
        "text_length": len(text),
        "text_extracted": bool(text.strip()),
        "analysis_json": json.dumps({
            "form_number": form,
            "category": category,
            "document_type": document_type,
            "zone_code": zone_code,
            "inspection_date": inspection_date.isoformat() if inspection_date else None,
            "explicit_expiry_date": explicit_expiry.isoformat() if explicit_expiry else None,
            "calculated_expiry_date": calculated_expiry.isoformat() if calculated_expiry else None,
            "expiry_date": effective_expiry.isoformat() if effective_expiry else None,
            "validity_source": validity_source,
            "validity_status": validity_status(effective_expiry),
            "confidence": confidence,
        }, ensure_ascii=False),
    }


def apply_analysis_to_document(doc, analysis: dict) -> dict:
    """Apply content-derived values without destroying known data on uncertainty."""
    if analysis.get("inspection_date"):
        doc.issue_date = analysis["inspection_date"]
    if analysis.get("expiry_date"):
        doc.expiry_date = analysis["expiry_date"]
    elif analysis.get("status") == "needs_review":
        # Never erase a known expiry merely because extraction failed.
        if not getattr(doc, "expiry_date", None):
            doc.expiry_date = None

    if analysis.get("category"):
        doc.category = analysis["category"]

    tags = [
        f"form:{analysis['form_number']}" if analysis.get("form_number") else None,
        f"zone:{analysis['zone_code']}" if analysis.get("zone_code") else None,
        f"validity:{analysis.get('validity_source')}" if analysis.get("validity_source") else None,
        f"analysis:{analysis.get('status')}" if analysis.get("status") else None,
        f"validity_status:{analysis.get('validity_status')}" if analysis.get("validity_status") else None,
        f"confidence:{analysis.get('confidence'):.2f}" if isinstance(analysis.get("confidence"), (int, float)) else None,
    ]
    doc.tags = ",".join(x for x in tags if x)
    doc.notes = analysis.get("analysis_notes")
    return analysis
