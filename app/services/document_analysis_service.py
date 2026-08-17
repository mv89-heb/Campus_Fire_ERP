"""Content-aware analysis of fire-safety PDF documents."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.document_validity_rules import resolve_validity

_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})(?!\d)")
_FORM_RE = re.compile(r"\bטופס\s*(?:מס[\u05f3']?\s*)?(\d{1,2})\b", re.I)
_CODE_RE = re.compile(r"\b(8855|8859|8853|8860)(?:\s*[-–/]\s*\d+)?\b")

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

ZONE_INFO = {
    "8855-7": ("מגורים (פנימייה)", ("אישורי מגורים", "מגורים", "פנימייה")),
    "8859-7": ("מטבח וחדר אוכל", ("אישורי מטבח", "מטבח", "בישול", "חדר אוכל")),
    "8853-7": ("אולם ספורט", ("אולם ספורט", "ספורט")),
    "8860-7": ("בית מדרש", ("בית מדרש", "מדרש")),
}

_EXPLICIT_EXPIRY_PATTERNS = (
    re.compile(r"(?:תוקף|בתוקף|תקף)\s*(?:עד|ליום|בתאריך)?\s*[:\-]?\s*" + _DATE_RE.pattern, re.I),
    re.compile(r"(?:valid\s+(?:until|through)|expires?|expiry|expiration)\s*[:\-]?\s*" + _DATE_RE.pattern, re.I),
)

_INSPECTION_LABELS = (
    "תאריך בדיקה", "מועד בדיקה", "תאריך ביצוע", "מועד ביצוע", "תאריך תחזוקה", "מועד תחזוקה",
    "תאריך ביקורת", "מועד ביקורת", "נבדק בתאריך", "נבדקה בתאריך", "נבדק ביום", "נבדקה ביום",
    "בוצע בתאריך", "בוצעה בתאריך", "בוצע ביום", "בוצעה ביום", "תאריך אישור", "מועד אישור",
    "תאריך הנפקה", "מועד הנפקה", "הונפק בתאריך", "הונפק ביום", "תאריך מילוי", "מועד מילוי",
    "בדיקה אחרונה",
)

_NEGATIVE_DATE_CONTEXT = (
    "בדיקה הבאה", "הבדיקה הבאה", "תחזוקה הבאה", "התחזוקה הבאה",
    "ביקורת הבאה", "הביקורת הבאה", "תוקף", "בתוקף", "תקף עד", "רישיון", "היתר",
)


def _today_israel():
    try:
        return datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    except Exception:
        return date.today()


def add_one_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


def validity_status(expiry_date, today=None):
    if expiry_date is None:
        return "needs_review"
    today = today or _today_israel()
    if today >= expiry_date:
        return "expired"
    days = (expiry_date - today).days
    return "critical" if days <= 14 else "warning" if days <= 30 else "valid"


def _parse_date_match(match):
    try:
        day, month, year = (int(x) for x in match.groups()[-3:])
        if year < 100:
            year += 2000 if year < 70 else 1900
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _normalise_lines(text):
    return [re.sub(r"\s+", " ", x).strip() for x in (text or "").splitlines() if x.strip()]


def _date_matches(line):
    result = []
    for match in _DATE_RE.finditer(line):
        value = _parse_date_match(match)
        if value and value not in result:
            result.append(value)
    return result


def extract_dates(text):
    result = []
    for line in _normalise_lines(text):
        for value in _date_matches(line):
            if value not in result:
                result.append(value)
    return result


def _semantic_expiry_candidates(text):
    lines = _normalise_lines(text)
    candidates = []
    for i in range(len(lines)):
        context = " ".join(lines[max(0, i - 1):min(len(lines), i + 2)])
        low = context.lower()
        for value in _date_matches(context):
            score = sum(100 for pattern in _EXPLICIT_EXPIRY_PATTERNS if pattern.search(context))
            if any(t in low for t in ("תוקף", "בתוקף", "תקף עד", "valid until", "valid through", "expires")):
                score += 25
            if any(t in low for t in ("בדיקה הבאה", "תחזוקה הבאה", "ביקורת הבאה")):
                score -= 30
            if score > 0:
                candidates.append((score, value, context))
    return candidates


def extract_explicit_expiry(text):
    candidates = _semantic_expiry_candidates(text)
    if not candidates:
        return None
    best_score = max(x[0] for x in candidates)
    return min(x[1] for x in candidates if x[0] == best_score)


def extract_inspection_date_evidence(text):
    lines = _normalise_lines(text)
    candidates = []
    for i in range(len(lines)):
        context = " ".join(lines[max(0, i - 1):min(len(lines), i + 2)])
        low = context.lower()
        for value in _date_matches(context):
            score = 0
            for label in _INSPECTION_LABELS:
                if label.lower() in low:
                    score += 30 if ("תאריך" in label or "מועד" in label) else 20
            if any(t in low for t in _NEGATIVE_DATE_CONTEXT):
                score -= 35
            if any(t in low for t in ("חתימה", "אישור", "נבדק", "בוצע", "תחזוקה")):
                score += 5
            if score > 0:
                candidates.append((score, value, context))
    if not candidates:
        return None
    score, value, context = sorted(candidates, key=lambda x: (x[0], x[1]), reverse=True)[0]
    return {"date": value, "score": score, "context": context}


def extract_inspection_date(text):
    evidence = extract_inspection_date_evidence(text)
    return evidence["date"] if evidence else None


def _filename_form(filename):
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    match = re.search(r"(?:^|\b)טופס\s*(?:מס[\u05f3']?\s*)?(\d{1,2})(?:\b|\.)", basename, re.I)
    return int(match.group(1)) if match else None


def _content_form_evidence(text):
    evidence = []
    for i, line in enumerate(_normalise_lines(text)[:80]):
        for match in _FORM_RE.finditer(line):
            score = 10 + (10 if i < 15 else 0) + (5 if any(t in line.lower() for t in ("אישור", "בדיק", "טופס")) else 0)
            evidence.append((score, int(match.group(1)), line))
    return evidence


def detect_form_number(text, filename=""):
    file_form = _filename_form(filename)
    content = _content_form_evidence(text)
    if file_form is not None:
        if not content:
            return file_form
        best = sorted(content, reverse=True)[0][1]
        same_count = sum(1 for _, number, _ in content if number == best)
        if best != file_form and same_count >= 2 and sorted(content, reverse=True)[0][0] >= 25:
            return best
        return file_form
    return sorted(content, key=lambda x: (x[0], x[2]), reverse=True)[0][1] if content else None


def _filename_zone(filename):
    low = (filename or "").lower()
    for code, (_, aliases) in ZONE_INFO.items():
        if any(alias.lower() in low for alias in aliases):
            return code
    match = _CODE_RE.search(filename or "")
    return f"{match.group(1)}-7" if match else None


def _content_zone_scores(text):
    low = (text or "").lower()
    scores = {code: 0 for code in ZONE_INFO}
    for code, (_, aliases) in ZONE_INFO.items():
        scores[code] += sum(10 for alias in aliases if alias.lower() in low)
        if code in low:
            scores[code] += 50
        if code.split("-")[0] in low:
            scores[code] += 30
    return scores


def detect_zone_evidence(text, filename=""):
    filename_zone = _filename_zone(filename)
    scores = _content_zone_scores(text)
    content_zone = max(scores, key=scores.get) if max(scores.values(), default=0) else None
    content_score = scores.get(content_zone, 0) if content_zone else 0

    # A strong content signal may override a filename. Otherwise the filename
    # remains the primary source because legacy uploads are often scanned PDFs
    # whose extracted text contains little identifying metadata.
    if filename_zone:
        if content_zone and content_zone != filename_zone and content_score >= 60:
            return {
                "zone_code": content_zone,
                "source": "strong_document_content",
                "filename_zone": filename_zone,
                "content_scores": scores,
            }
        return {
            "zone_code": filename_zone,
            "source": "filename_verified_by_content" if content_score else "filename",
            "filename_zone": filename_zone,
            "content_scores": scores,
        }
    return {
        "zone_code": content_zone,
        "source": "document_content" if content_zone else "unknown",
        "filename_zone": None,
        "content_scores": scores,
    }


def detect_zone_code(text, filename=""):
    return detect_zone_evidence(text, filename).get("zone_code")


def _extract_text(data):
    import fitz
    with fitz.open(stream=data, filetype="pdf") as document:
        return "\n".join(page.get_text("text") for page in document), len(document)


def _json_safe_evidence(evidence):
    if not evidence:
        return None
    return {
        "date": evidence.get("date").isoformat() if evidence.get("date") else None,
        "score": evidence.get("score"),
        "context": evidence.get("context"),
    }


def analyze_pdf_bytes(data: bytes, filename=""):
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
    zone_evidence = detect_zone_evidence(text, filename)
    zone_code = zone_evidence.get("zone_code")
    explicit_expiry = extract_explicit_expiry(text)
    inspection_evidence = extract_inspection_date_evidence(text)
    inspection_date = inspection_evidence["date"] if inspection_evidence else None

    validity = resolve_validity(
        zone_code=zone_code,
        form_number=form,
        text=text,
        inspection_date=inspection_date,
        explicit_expiry=explicit_expiry,
    )
    effective_expiry = validity.get("expiry_date")
    validity_source = validity.get("source") or "unknown"
    validity_status_value = validity_status(effective_expiry)
    status = "analyzed" if effective_expiry else "needs_review"

    notes = []
    if explicit_expiry:
        notes.append(f"נמצא תוקף מפורש במסמך: {explicit_expiry.isoformat()}.")
    elif validity_source == "document_stated_interval":
        notes.append(
            f"לא נמצא תאריך תוקף מפורש; המסמך מציין כלל תדירות '{validity.get('rule_label')}' "
            f"({validity.get('rule_evidence')}), ולכן התוקף חושב מתאריך הבדיקה/ההנפקה: {effective_expiry.isoformat()}."
        )
    elif validity_source == "requirement_rule":
        notes.append(
            f"התוקף חושב לפי כלל דרישה מוגדר: {validity.get('rule_label')} -> {effective_expiry.isoformat()}."
        )
    else:
        notes.append(
            "לא נמצא בתוכן המסמך תוקף מפורש או כלל תדירות מספיק אמין לחישוב תוקף. נדרש עיון ידני."
        )

    if inspection_evidence:
        notes.append(f"מקור תאריך הבדיקה: {inspection_evidence['context']}")
    if zone_code:
        notes.append(f"המתחם שויך ל-{ZONE_INFO[zone_code][0]} ({zone_code}) לפי {zone_evidence['source']}.")
    else:
        notes.append("לא ניתן לקבוע מתחם בביטחון מתוכן המסמך/שם הקובץ.")

    confidence = validity.get("confidence", 0.30)
    if form and zone_code:
        confidence = min(0.99, confidence + 0.02)
    if inspection_date and effective_expiry:
        confidence = min(0.99, confidence + 0.01)

    inspection_json = _json_safe_evidence(inspection_evidence)
    payload = {
        "form_number": form,
        "category": category,
        "document_type": document_type,
        "zone_code": zone_code,
        "zone_evidence": zone_evidence,
        "inspection_date": inspection_date.isoformat() if inspection_date else None,
        "inspection_evidence": inspection_json,
        "explicit_expiry_date": explicit_expiry.isoformat() if explicit_expiry else None,
        "calculated_expiry_date": effective_expiry.isoformat() if effective_expiry and validity_source != "explicit_document_expiry" else None,
        "expiry_date": effective_expiry.isoformat() if effective_expiry else None,
        "validity_source": validity_source,
        "validity_rule": validity.get("rule_key"),
        "validity_rule_label": validity.get("rule_label"),
        "validity_rule_evidence": validity.get("rule_evidence"),
        "validity_status": validity_status_value,
        "confidence": confidence,
        "all_dates": [d.isoformat() for d in extract_dates(text)],
    }

    return {
        "status": status,
        "filename": filename,
        "form_number": form,
        "category": category,
        "document_type": document_type,
        "zone_code": zone_code,
        "zone_evidence": zone_evidence,
        "inspection_date": inspection_date,
        "issue_date": inspection_date,
        "inspection_evidence": inspection_evidence,
        "explicit_expiry_date": explicit_expiry,
        "calculated_expiry_date": effective_expiry if effective_expiry and validity_source != "explicit_document_expiry" else None,
        "expiry_date": effective_expiry,
        "validity_source": validity_source,
        "validity_rule": validity.get("rule_key"),
        "validity_rule_label": validity.get("rule_label"),
        "validity_rule_evidence": validity.get("rule_evidence"),
        "validity_status": validity_status_value,
        "confidence": confidence,
        "analysis_notes": " ".join(notes),
        "pages": pages,
        "text_length": len(text),
        "text_extracted": bool(text.strip()),
        "analysis_json": json.dumps(payload, ensure_ascii=False),
    }


def apply_analysis_to_document(doc, analysis):
    if analysis.get("inspection_date"):
        doc.issue_date = analysis["inspection_date"]
    if analysis.get("expiry_date"):
        doc.expiry_date = analysis["expiry_date"]
    if analysis.get("category"):
        doc.category = analysis["category"]

    tags = [
        f"form:{analysis['form_number']}" if analysis.get("form_number") else None,
        f"zone:{analysis['zone_code']}" if analysis.get("zone_code") else None,
        f"validity:{analysis.get('validity_source')}" if analysis.get("validity_source") else None,
        f"validity_rule:{analysis.get('validity_rule')}" if analysis.get("validity_rule") else None,
        f"analysis:{analysis.get('status')}" if analysis.get("status") else None,
        f"validity_status:{analysis.get('validity_status')}" if analysis.get("validity_status") else None,
        f"confidence:{analysis.get('confidence'):.2f}" if isinstance(analysis.get('confidence'), (int, float)) else None,
    ]
    doc.tags = ",".join(x for x in tags if x)
    doc.notes = analysis.get("analysis_notes")
    return analysis
