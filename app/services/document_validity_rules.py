"""Requirement-aware validity rules for fire-safety documents.

The rule engine deliberately does NOT assume that every fire-safety document is
valid for one year. It uses this precedence:

1. An explicit expiry date printed on the document.
2. A validity interval stated in the document (annual / 3 years / 5 years,
   etc.) applied to the strongest inspection/issue date evidence.
3. A requirement-specific rule only when the rule is explicitly configured.
4. Otherwise the document is marked needs_review instead of inventing a date.

This keeps the ERP conservative: lack of evidence never becomes a fake expiry.
"""
from __future__ import annotations

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


# These are deliberately narrow. They are not a substitute for the current
# official requirement dataset; they are fallback rules only when the document
# itself contains the corresponding wording.
DOCUMENT_INTERVAL_RULES = (
    ValidityRule(
        "annual",
        "שנתי",
        years=1,
        evidence_terms=(
            "בדיקה שנתית", "בדיקות שנתיות", "תחזוקה שנתית", "תחזוקה שנתית",
            "אישור שנתי", "דוח שנתי", "אחת לשנה", "כל שנה", "פעם בשנה",
        ),
    ),
    ValidityRule(
        "three_years",
        "3 שנים",
        years=3,
        evidence_terms=(
            "3 שנים", "שלוש שנים", "כל 3 שנים", "אחת ל-3 שנים", "אחת ל 3 שנים",
            "אחת לשלוש שנים",
        ),
    ),
    ValidityRule(
        "five_years",
        "5 שנים",
        years=5,
        evidence_terms=(
            "5 שנים", "חמש שנים", "כל 5 שנים", "אחת ל-5 שנים", "אחת ל 5 שנים",
            "אחת לחמש שנים",
        ),
    ),
)

# Requirement-specific defaults are only used when the requirement itself is
# explicitly known to be annual. Keep this list empty rather than guessing.
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
        import calendar
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    raise ValueError("ValidityRule must define years or months")


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
    """Resolve expiry using document evidence and configured requirement rules."""
    if explicit_expiry:
        return {
            "expiry_date": explicit_expiry,
            "source": "explicit_document_expiry",
            "rule_key": None,
            "rule_label": "תוקף מפורש במסמך",
            "rule_evidence": "תוקף/בתוקף/תקף עד",
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
            "confidence": 0.94,
        }

    requirement_rule = REQUIREMENT_DEFAULTS.get((zone_code, form_number))
    if requirement_rule and inspection_date:
        return {
            "expiry_date": add_interval(inspection_date, requirement_rule),
            "source": "requirement_rule",
            "rule_key": requirement_rule.key,
            "rule_label": requirement_rule.label,
            "rule_evidence": "configured_requirement_rule",
            "confidence": 0.90,
        }

    return {
        "expiry_date": None,
        "source": "unknown",
        "rule_key": None,
        "rule_label": None,
        "rule_evidence": None,
        "confidence": 0.30,
    }
