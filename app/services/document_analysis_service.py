"""Content-based analysis and one-year validity rules for fire-safety documents."""
from __future__ import annotations

import json
import re
from datetime import date

_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?!\d)")
_FORM_RE = re.compile(r"טופס\s*(?:מס[\u05f3']?\s*)?(\d{1,2})")

FORM_TYPES = {
    2: ("מטפים", "תחזוקת מטפים"),
    3: ("חשמל", "בדיקת מערכת חשמל ותאורת חירום"),
    4: ("גילוי אש", "תחזוקת מערכת גילוי אש"),
    5: ("כיבוי בלוחות חשמל", "מערכת כיבוי בלוחות חשמל"),
    6: ("כריזה", "מערכת מסירת הודעות/כריזת חירום"),
    7: ("ספרינקלרים", "מערכת כיבוי אוטומטית בספרינקלרים"),
    10: ("שחרור עשן", "מערכת שליטה בעשן"),
    13: ("תיק שטח", "הגשת/עדכון תיק שטח"),
    14: ("הדרכת עובדים", "הדרכת עובדים"),
    16: ("מטבח", "ניקוי מערכת פליטה מבישול מסחרי"),
    18: ("מערכת גז", "בדיקת תקינות מערכת גז"),
}


def add_one_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


def validity_status(expiry_date: date | None, today: date | None = None) -> str:
    if expiry_date is None:
        return "needs_review"
    today = today or date.today()
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


def extract_dates(text: str) -> list[date]:
    dates = []
    for m in _DATE_RE.finditer(text or ""):
        value = _parse_date(m)
        if value and value not in dates:
            dates.append(value)
    return dates


def _candidate_dates(text: str):
    for m in _DATE_RE.finditer(text or ""):
        value = _parse_date(m)
        if not value:
            continue
        start = max(0, m.start() - 110)
        end = min(len(text), m.end() + 110)
        yield value, text[start:end]


def extract_inspection_date(text: str) -> date | None:
    scored = []
    positive = ('תאריך', 'בתאריך', 'בדיק', 'ביקור', 'תחזוק', 'מצהיר')
    negative = ('תוקף', 'בתוקף', 'רישיון', 'היתר', 'דרישה', 'הבאה', 'הבא')
    for value, context in _candidate_dates(text or ''):
        score = sum(3 for token in positive if token in context)
        score -= sum(5 for token in negative if token in context)
        if score > 0:
            scored.append((score, value))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1]
    return None


def extract_explicit_expiry(text: str) -> date | None:
    values = []
    for value, context in _candidate_dates(text or ''):
        if any(token in context for token in ('תוקף', 'בתוקף', 'תחזוקה הבאה', 'התחזוקה הבאה', 'תוקף האישור')):
            values.append(value)
    return min(values) if values else None


def detect_form_number(text: str, filename: str = "") -> int | None:
    m = _FORM_RE.search(filename or "")
    if m:
        return int(m.group(1))
    m = re.search(r"(?:טופס\s*)?(\d{1,2})(?:\s*\([^)]*\))?\.pdf$", filename or "", re.I)
    if m:
        return int(m.group(1))
    m = _FORM_RE.search(text or "")
    return int(m.group(1)) if m else None


def detect_zone_code(text: str, filename: str = "") -> str | None:
    combined = f"{text} {filename}"
    for code in ("8855-7", "8859-7", "8853-7", "8860-7"):
        if code.split("-")[0] in combined:
            return code
    if "מגורים" in combined or "פנימייה" in combined:
        return "8855-7"
    if "מטבח" in combined or "בישול" in combined:
        return "8859-7"
    if "אולם ספורט" in combined:
        return "8853-7"
    if "בית מדרש" in combined:
        return "8860-7"
    return None


def analyze_pdf_bytes(data: bytes, filename: str = "") -> dict:
    text = ""
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as document:
            text = "\n".join(page.get_text() for page in document)
    except Exception as exc:
        return {"status": "needs_review", "error": f"PDF text extraction failed: {exc}", "filename": filename}

    form = detect_form_number(text, filename)
    category, document_type = FORM_TYPES.get(form, (None, None))
    inspection_date = extract_inspection_date(text)
    explicit_expiry = extract_explicit_expiry(text)
    expiry_date = None
    validity_source = "unknown"
    if inspection_date:
        expiry_date = add_one_year(inspection_date)
        validity_source = "annual_rule"
    if explicit_expiry and (expiry_date is None or explicit_expiry < expiry_date):
        expiry_date = explicit_expiry
        validity_source = "explicit_expiry"
    confidence = 0.95 if form and inspection_date else 0.75 if form else 0.30
    if not expiry_date:
        status = "needs_review"
        analysis_notes = "לא אותר תאריך בדיקה/הנפקה אמין מתוך הטקסט; אין לחשב תוקף אוטומטי."
    else:
        status = "analyzed"
        analysis_notes = "תוקף מחושב מתאריך הבדיקה לפי כלל שנה קלנדרית; תאריך תוקף מפורש קודם לכלל אם קיים."
    zone_code = detect_zone_code(text, filename)
    return {
        "status": status, "filename": filename, "form_number": form,
        "category": category, "document_type": document_type, "zone_code": zone_code,
        "inspection_date": inspection_date, "issue_date": inspection_date,
        "explicit_expiry_date": explicit_expiry, "expiry_date": expiry_date,
        "validity_source": validity_source, "validity_status": validity_status(expiry_date),
        "confidence": confidence, "analysis_notes": analysis_notes,
        "text_length": len(text), "text_extracted": bool(text.strip()),
        "analysis_json": json.dumps({"form_number": form, "category": category,
            "document_type": document_type, "zone_code": zone_code,
            "inspection_date": inspection_date.isoformat() if inspection_date else None,
            "explicit_expiry_date": explicit_expiry.isoformat() if explicit_expiry else None,
            "validity_source": validity_source}, ensure_ascii=False),
    }


def apply_analysis_to_document(doc, analysis: dict) -> dict:
    if analysis.get('inspection_date'):
        doc.issue_date = analysis['issue_date']
        doc.expiry_date = analysis['expiry_date']
    elif analysis.get('explicit_expiry_date'):
        doc.expiry_date = analysis['explicit_expiry_date']
    else:
        doc.expiry_date = None
    if analysis.get('category'):
        doc.category = analysis['category']
    tags = [x for x in [
        f"form:{analysis['form_number']}" if analysis.get('form_number') else None,
        f"zone:{analysis['zone_code']}" if analysis.get('zone_code') else None,
        f"validity:{analysis.get('validity_source')}" if analysis.get('validity_source') else None,
        f"analysis:{analysis.get('status')}" if analysis.get('status') else None,
    ] if x]
    if tags:
        doc.tags = ','.join(tags)
    doc.notes = analysis.get('analysis_notes')
    return analysis
