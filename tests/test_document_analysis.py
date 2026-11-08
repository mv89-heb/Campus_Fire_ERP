import unittest
from datetime import date

from app.services.document_analysis_service import (
    extract_explicit_expiry,
    extract_inspection_date,
    detect_form_number,
    validity_status,
)
from app.services.document_validity_rules import (
    ValidityRule,
    add_interval,
    resolve_validity,
)


class DocumentAnalysisTests(unittest.TestCase):
    def test_one_year_boundary_is_calendar_based(self):
        self.assertEqual(
            add_interval(date(2025, 8, 17), ValidityRule('annual', 'שנה', years=1)),
            date(2026, 8, 17),
        )
        # The expiry date itself is still in force, but is flagged as critical.
        self.assertEqual(validity_status(date(2026, 8, 17), date(2026, 8, 17)), 'critical')
        self.assertEqual(validity_status(date(2026, 8, 16), date(2026, 8, 17)), 'expired')

    def test_february_29_has_safe_next_year(self):
        self.assertEqual(
            add_interval(date(2024, 2, 29), ValidityRule('annual', 'שנה', years=1)),
            date(2025, 2, 28),
        )

    def test_extracts_inspection_date_from_fire_form_text(self):
        text = "טופס מס' 7 תאריך: 17/08/2025 בוצעה בדיקת תחזוקה למערכת אוטומטית לכיבוי אש"
        self.assertEqual(detect_form_number(text), 7)
        self.assertEqual(extract_inspection_date(text), date(2025, 8, 17))

    def test_explicit_expiry_overrides_interval(self):
        text = "תאריך: 27/01/2025 תאריך התחזוקה הבאה יהיה ביום: 27/01/2026 תוקף האישור עד 31/12/2025"
        self.assertEqual(extract_inspection_date(text), date(2025, 1, 27))
        self.assertEqual(extract_explicit_expiry(text), date(2025, 12, 31))

    def test_conditional_electrical_requirement_is_not_guessed_without_risk(self):
        result = resolve_validity(
            zone_code='8860-7',
            form_number=3,
            text='בוצעה בדיקת מערכת חשמל בתאריך 10/08/2025',
            inspection_date=date(2025, 8, 10),
            explicit_expiry=None,
        )
        self.assertIsNone(result['expiry_date'])
        self.assertEqual(result['requirement_cycle'], '3 או 5 שנים לפי סיווג')

    def test_conditional_electrical_requirement_uses_explicit_risk_level(self):
        result = resolve_validity(
            zone_code='8860-7',
            form_number=3,
            text='רמת סיכון 4. בדיקת מערכת חשמל בתאריך 10/08/2025',
            inspection_date=date(2025, 8, 10),
            explicit_expiry=None,
        )
        self.assertEqual(result['expiry_date'], date(2028, 8, 10))
        self.assertEqual(result['source'], 'document_condition_rule')

    def test_annual_fixed_requirement_can_calculate_expiry(self):
        result = resolve_validity(
            zone_code='8853-7',
            form_number=2,
            text='בוצעה תחזוקה בתאריך 10/08/2025',
            inspection_date=date(2025, 8, 10),
            explicit_expiry=None,
        )
        self.assertEqual(result['expiry_date'], date(2026, 8, 10))
        self.assertEqual(result['source'], 'requirement_rule')

    def test_annual_word_does_not_create_legal_expiry_for_conditional_sprinkler_rule(self):
        result = resolve_validity(
            zone_code='8855-7',
            form_number=7,
            text='בוצעה תחזוקה שנתית בתאריך 17/08/2025',
            inspection_date=date(2025, 8, 17),
            explicit_expiry=None,
        )
        self.assertIsNone(result['expiry_date'])
        self.assertEqual(result['source'], 'maintenance_cycle_only')


if __name__ == '__main__':
    unittest.main()
