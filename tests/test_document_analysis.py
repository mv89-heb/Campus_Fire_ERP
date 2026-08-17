from datetime import date

from app.services.document_analysis_service import add_one_year, validity_status, extract_inspection_date, extract_explicit_expiry, detect_form_number


def test_one_year_boundary_is_calendar_based():
    assert add_one_year(date(2025, 8, 17)) == date(2026, 8, 17)
    assert validity_status(date(2026, 8, 17), date(2026, 8, 17)) == 'expired'
    assert validity_status(date(2026, 8, 18), date(2026, 8, 17)) == 'valid'


def test_february_29_has_safe_next_year():
    assert add_one_year(date(2024, 2, 29)) == date(2025, 2, 28)


def test_extracts_inspection_date_from_fire_form_text():
    text = "טופס מס' 7 תאריך: 17/08/2025 בוצעה בדיקת תחזוקה למערכת אוטומטית לכיבוי אש"
    assert detect_form_number(text) == 7
    assert extract_inspection_date(text) == date(2025, 8, 17)


def test_explicit_expiry_can_override_annual_date_when_earlier():
    text = "תאריך: 27/01/2025 תאריך התחזוקה הבאה יהיה ביום: 27/01/2026 תוקף האישור עד 31/12/2025"
    assert extract_inspection_date(text) == date(2025, 1, 27)
    assert extract_explicit_expiry(text) == date(2025, 12, 31)
