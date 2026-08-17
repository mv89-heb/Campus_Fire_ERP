"""Requirement-aware validity / inspection-cycle rules for fire-safety documents.

Important distinction:
* A document's *printed validity/expiry date* is authoritative when present.
* A maintenance/inspection cycle is not automatically the same thing as a
  legal certificate validity period.
* Where the current official requirement is conditional (for example electrical
  inspections: 3 or 5 years depending on risk/route), the ERP stores the cycle
  as a requirement rule and does NOT invent an expiry date until the condition
  is known.

The catalog below is based on current Israel Fire & Rescue Authority material
and is deliberately conservative. It is a compliance aid, not a replacement
for the specific fire-safety conditions attached to the campus/property.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ValidityRule:
    key: str
    label: str
    years: int | None = None
    months: int | None = None
    evidence_terms: tuple[str, ...] = ()
    source_note: str = ""


# Explicit wording found inside the actual certificate wins over this catalog.
DOCUMENT_INTERVAL_RULES = (
    ValidityRule(
        "annual", "שנה / אחת לשנה", years=1,
        evidence_terms=(
            "בדיקה שנתית", "בדיקות שנתיות", "תחזוקה שנתית", "אישור שנתי",
            "דוח שנתי", "אחת לשנה", "כל שנה", "פעם בשנה", "שנתי",
        ),
        source_note="המסמך עצמו מציין מחזור שנתי.",
    ),
    ValidityRule(
        "three_years", "3 שנים", years=3,
        evidence_terms=(
            "3 שנים", "שלוש שנים", "כל 3 שנים", "אחת ל-3 שנים",
            "אחת ל 3 שנים", "אחת לשלוש שנים",
        ),
        source_note="המסמך עצמו מציין מחזור של 3 שנים.",
    ),
    ValidityRule(
        "five_years", "5 שנים", years=5,
        evidence_terms=(
            "5 שנים", "חמש שנים", "כל 5 שנים", "אחת ל-5 שנים",
            "אחת ל 5 שנים", "אחת לחמש שנים",
        ),
        source_note="המסמך עצמו מציין מחזור של 5 שנים.",
    ),
)


@dataclass(frozen=True)
class RequirementCycle:
    form_number: int
    label: str
    cycle: str
    years: int | None = None
    conditional: bool = False
    source: str = ""
    note: str = ""


# This is a requirement-cycle catalog, NOT a blanket expiry table.
# "no_fixed_period" means the form is evidence of inspection/approval and the
# applicable validity depends on the underlying system, standard, installation,
# risk classification, or explicit date printed on the certificate.
REQUIREMENT_CATALOG: dict[int, RequirementCycle] = {
    1: RequirementCycle(
        1, "ציוד כיבוי", "אין תקופת תוקף אחידה", None,
        note="הטופס מרכז ציוד; תדירות התחזוקה תלויה בסוג הציוד ובדרישות התקן. אין להמציא תוקף אחיד.",
    ),
    2: RequirementCycle(
        2, "תחזוקת מטפים", "שנתי", 1,
        source="ת""י 129 חלק 1 / כבאות והצלה",
        note="מטפים נדרשים בתחזוקה שוטפת ובביקורת שנתית; הטופס הרשמי כולל מועד בדיקה שנתית ומועד בדיקה יסודית הבא.",
    ),
    3: RequirementCycle(
        3, "חשמל", "3 או 5 שנים לפי סיווג", None, True,
        source="מאגר דרישות בטיחות אש לרישוי עסקים, 04-05-2026",
        note="מסלול תצהיר ורמות סיכון 1–3: אחת ל-5 שנים; רמות סיכון 4–5: אחת ל-3 שנים.",
    ),
    4: RequirementCycle(
        4, "גילוי אש", "לפי תחזוקת המערכת והדרישה הספציפית", None, True,
        source="ת""י 1220 חלק 11 / דרישות כבאות",
        note="אין לקבוע אוטומטית שנה לכל אישור. יש לבדוק את סוג המערכת, דרישת הנכס והתאריך/מחזור המופיעים באישור.",
    ),
    5: RequirementCycle(
        5, "לוחות חשמל", "לפי מערכת הכיבוי/גילוי והדרישה הספציפית", None, True,
        source="ת""י 1220 / ת""י 5210 / ת""י 1597",
        note="אישור התקנה למערכת חדשה אינו תחליף למחזור התחזוקה של המערכת המותקנת.",
    ),
    6: RequirementCycle(
        6, "כריזה", "אין תקופת תוקף אחידה", None, True,
        source="ת""י 1220 / הוראות הנכס",
        note="אישור התקנה הוא ראיה להתאמה; תדירות התחזוקה נקבעת לפי המערכת והדרישה הספציפית.",
    ),
    7: RequirementCycle(
        7, "ספרינקלרים", "לפי תכנית התחזוקה של המערכת", None, True,
        source="ת""י 1928 / ת""י 1596",
        note="אישור תקינות תחזוקה אינו מקבל אוטומטית תוקף של שנה. לדוגמה, אפיון רשת מים (גרף) מופיע במאגר כבאות כאישור הניתן אחת ל-5 שנים במקרים הרלוונטיים.",
    ),
    10: RequirementCycle(
        10, "שחרור עשן", "אין תקופת תוקף אחידה", None, True,
        source="דרישות כבאות, טופס 10",
        note="הדרישה העדכנית שמצאנו מחייבת אישור מהנדס כאשר נדרשת מערכת; היא אינה קובעת בפלט זה תוקף אחיד של שנה.",
    ),
    13: RequirementCycle(
        13, "תיק שטח", "לפי דרישת הנכס ולעדכון בעת שינוי", None, True,
        note="אין לקבוע תוקף שנתי אוטומטי בלי דרישה ספציפית/גרסה/תאריך במסמך.",
    ),
    14: RequirementCycle(
        14, "הדרכת עובדים", "שנתי", 1,
        source="מאגר דרישות בטיחות אש לרישוי עסקים",
        note="בדרישות כבאות מופיעה הדרכת עובדים אחת לשנה במקרים הרלוונטיים.",
    ),
    16: RequirementCycle(
        16, "מערכת פליטה מבישול מסחרי", "לפי דרישת המערכת והתקן", None, True,
        source="ת""י 1001 חלק 6 / ת""י 5356 חלק 2",
        note="אישור התקנה למערכת חדשה אינו בהכרח תעודת תוקף שנתית.",
    ),
    18: RequirementCycle(
        18, "מערכת גז", "לפי סוג המתקן והדרישה הספציפית", None, True,
        note="לא נקבע תוקף אחיד ללא זיהוי סוג מערכת הגז והדרישה החלה על הנכס.",
    ),
}

# Kept for backwards compatibility with callers that expect this symbol.
REQUIREMENT_DEFAULTS: dict[tuple[str | None, int | None], ValidityRule] = {}


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def add_interval(value: date, rule: ValidityRule) -> date:
    if rule.years:
        return _add_years(value, rule.years)
    if rule.months:
        total = value.year * 12 + (value.month - 1) + rule.months
        year, month0 = divmod(total, 12)
        month = month0 + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    raise ValueError("ValidityRule must define years or months")


def requirement_cycle(form_number: int | None) -> RequirementCycle | None:
    return REQUIREMENT_CATALOG.get(form_number) if form_number is not None else None


def detect_document_interval(text: str) -> tuple[ValidityRule | None, str | None]:
    """Find an explicit validity interval in the document text."""
    normalized = re.sub(r"\s+", " ", text or "").lower()
    candidates: list[tuple[int, ValidityRule, str]] = []
    for rule in DOCUMENT_INTERVAL_RULES:
        for term in rule.evidence_terms:
            if term.lower() in normalized:
                score = 30 + (10 if any(ch.isdigit() for ch in term) else 0)
                candidates.append((score, rule, term))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (x[0], x[1].years or 0), reverse=True)
    _, rule, evidence = candidates[0]
    return rule, evidence


def resolve_validity(*, zone_code: str | None, form_number: int | None,
                     text: str, inspection_date: date | None,
                     explicit_expiry: date | None) -> dict:
    """Resolve expiry while exposing the applicable requirement cycle."""
    catalog = requirement_cycle(form_number)

    if explicit_expiry:
        return {
            "expiry_date": explicit_expiry,
            "source": "explicit_document_expiry",
            "rule_key": "explicit_expiry",
            "rule_label": "תוקף מפורש במסמך",
            "rule_evidence": "תוקף/בתוקף/תקף עד",
            "requirement_cycle": catalog.cycle if catalog else None,
            "requirement_source": catalog.source if catalog else None,
            "requirement_note": catalog.note if catalog else None,
            "confidence": 0.99,
        }

    interval, evidence = detect_document_interval(text)
    if interval and inspection_date:
        return {
            "expiry_date": add_interval(inspection_date, interval),
            "source": "document_stated_interval",
            "rule_key": interval.key,
            "rule_label": interval.label,
            "rule_evidence": evidence,
            "requirement_cycle": catalog.cycle if catalog else interval.label,
            "requirement_source": catalog.source if catalog else interval.source_note,
            "requirement_note": catalog.note if catalog else interval.source_note,
            "confidence": 0.94,
        }

    # Only fixed catalog cycles are allowed to calculate an expiry.
    if catalog and catalog.years and inspection_date and not catalog.conditional:
        rule = ValidityRule(catalog.label, catalog.label, years=catalog.years)
        return {
            "expiry_date": add_interval(inspection_date, rule),
            "source": "requirement_rule",
            "rule_key": rule.key,
            "rule_label": catalog.label,
            "rule_evidence": "configured_requirement_rule",
            "requirement_cycle": catalog.cycle,
            "requirement_source": catalog.source,
            "requirement_note": catalog.note,
            "confidence": 0.90,
        }

    return {
        "expiry_date": None,
        "source": "unknown",
        "rule_key": None,
        "rule_label": None,
        "rule_evidence": None,
        "requirement_cycle": catalog.cycle if catalog else None,
        "requirement_source": catalog.source if catalog else None,
        "requirement_note": catalog.note if catalog else None,
        "confidence": 0.30,
    }
