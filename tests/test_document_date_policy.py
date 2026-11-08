import unittest
from datetime import date

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Audit, Document, Site
from app.services.document_date_policy_service import (
    calculate_document_status,
    apply_document_policy,
    document_dates,
    reconcile_audit_summary,
)


class DocumentDatePolicyTests(unittest.TestCase):
    def test_2025_document_without_multiyear_proof_is_old(self):
        result = calculate_document_status(
            date(2025, 4, 10), None,
            policy_year=2026, today=date(2026, 11, 8),
        )
        self.assertEqual(result["status"], "old_approval")

    def test_2024_verified_multiyear_document_remains_active(self):
        result = calculate_document_status(
            date(2024, 1, 1), date(2027, 1, 1),
            policy_year=2026, today=date(2026, 11, 8),
        )
        self.assertEqual(result["status"], "active")
        self.assertTrue(result["is_multi_year"])

    def test_missing_issue_date_requires_manual_review(self):
        result = calculate_document_status(
            None, date(2027, 1, 1),
            policy_year=2026, today=date(2026, 11, 8),
        )
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(result["verification"], "missing_issue_date")

    def test_future_issue_date_is_not_accepted(self):
        result = calculate_document_status(
            date(2026, 11, 9), date(2027, 11, 9),
            policy_year=2026, today=date(2026, 11, 8),
        )
        self.assertEqual(result["status"], "future_issue_date")

    def test_expiry_before_issue_is_conflict(self):
        result = calculate_document_status(
            date(2026, 6, 1), date(2026, 5, 31),
            policy_year=2026, today=date(2026, 11, 8),
        )
        self.assertEqual(result["status"], "date_conflict")

    def test_expired_document_enters_only_explicit_grace_period(self):
        without_grace = calculate_document_status(
            date(2025, 1, 1), date(2026, 11, 1),
            policy_year=2026, today=date(2026, 11, 8), grace_period_days=0,
        )
        with_grace = calculate_document_status(
            date(2025, 1, 1), date(2026, 11, 1),
            policy_year=2026, today=date(2026, 11, 8), grace_period_days=10,
        )
        self.assertEqual(without_grace["status"], "expired")
        self.assertEqual(with_grace["status"], "grace_period")

    def test_expiration_date_is_valid_through_the_day_itself(self):
        result = calculate_document_status(
            date(2026, 1, 1), date(2026, 11, 8),
            policy_year=2026, today=date(2026, 11, 8),
        )
        self.assertEqual(result["status"], "expiring_soon")

    def test_low_confidence_date_extraction_requires_manual_review(self):
        result = calculate_document_status(
            date(2026, 1, 1), date(2027, 1, 1),
            policy_year=2026, today=date(2026, 11, 8),
            date_extraction_confidence=0.62, minimum_date_confidence=0.80,
        )
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(result["verification"], "low_date_confidence")

    def test_ocr_year_1212_is_implausible_and_requires_manual_review(self):
        result = calculate_document_status(
            date(1212, 2, 28), date(1217, 2, 28),
            policy_year=2026, today=date(2026, 11, 8),
        )
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(result["verification"], "implausible_date")
        self.assertFalse(result["is_multi_year"])

    def test_conflicting_local_and_gemini_dates_require_manual_review(self):
        result = calculate_document_status(
            date(2026, 1, 1), date(2027, 1, 1),
            policy_year=2026, today=date(2026, 11, 8),
            date_extraction_conflict=True,
        )
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(result["verification"], "extraction_conflict")

    def test_manual_date_review_is_authoritative_without_erasing_gemini_evidence(self):
        from datetime import datetime
        document = Document(
            file_name="reviewed.pdf", file_path="reviewed.pdf",
            file_hash="e" * 64, issue_date=date(2026, 1, 1),
            expiry_date=None, analysis_expiry_date=date(2027, 1, 1),
            gemini_expiry_date=date(2027, 2, 1),
            date_reviewed_at=datetime(2026, 11, 8),
        )
        self.assertEqual(document_dates(document), (date(2026, 1, 1), None))


    def test_february_29_multiyear_boundary_uses_calendar_year(self):
        result = calculate_document_status(
            date(2024, 2, 29), date(2025, 2, 28),
            policy_year=2026, today=date(2024, 3, 1),
        )
        self.assertFalse(result["is_multi_year"])


class AuditSummaryReconciliationTests(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING = True
            SECRET_KEY = "test-secret"
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            AUTO_CREATE_DB = True
            DOCUMENT_POLICY_YEAR = 2026
            DOCUMENT_GRACE_PERIOD_DAYS = 0
        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_2026_audit_missing_item_conflicts_with_uploaded_valid_certificate(self):
        site = Site(name="קמפוס בדיקה")
        db.session.add(site)
        db.session.flush()
        audit = Audit(audit_number="AUD-2026-01", site_id=site.id, audit_date=date(2026, 10, 1))
        summary = Document(
            file_name="סיכום ביקורת 2026.pdf",
            file_path="summary.pdf",
            file_hash="a" * 64,
            site_id=site.id,
            audit_id=None,
            is_audit_summary=True,
            audit_year=2026,
            ai_actions_json='{"missing_items":["אישור חשמל"]}',
        )
        certificate = Document(
            file_name="אישור חשמל.pdf",
            file_path="certificate.pdf",
            file_hash="b" * 64,
            site_id=site.id,
            category="חשמל",
            issue_date=date(2024, 1, 1),
            expiry_date=date(2027, 1, 1),
        )
        db.session.add_all([audit, summary, certificate])
        db.session.commit()

        result = reconcile_audit_summary(summary)
        self.assertEqual(result["audit_year"], 2026)
        self.assertEqual(result["documents_checked"], 1)
        self.assertEqual(result["items"][0]["status"], "conflict")
        self.assertEqual(result["items"][0]["matched_documents"][0]["document_id"], certificate.id)

    def test_audit_summary_is_detected_from_local_pdf_text(self):
        from unittest.mock import patch
        from app.services.document_analysis_service import analyze_pdf_bytes
        with patch(
            "app.services.document_analysis_service._extract_text",
            return_value=("סיכום ביקורת\nתאריך ביקורת: 01/11/2026", 1),
        ):
            result = analyze_pdf_bytes(b"fake-pdf", "audit.pdf")
        self.assertTrue(result["is_audit_summary"])
        self.assertEqual(result["audit_year"], 2026)
        self.assertEqual(result["audit_date"], date(2026, 11, 1))


    def test_audit_summary_is_detected_from_file_name_without_text_layer(self):
        from unittest.mock import patch
        from app.services.document_analysis_service import analyze_pdf_bytes
        with patch(
            "app.services.document_analysis_service._extract_text",
            return_value=("", 0),
        ):
            result = analyze_pdf_bytes(b"fake-pdf", "סיכום ביקורת תקופתית.pdf")
        self.assertTrue(result["is_audit_summary"])


    def test_unlinked_audit_summary_requires_manual_site_link(self):
        summary = Document(
            file_name="סיכום ביקורת.pdf",
            file_path="summary.pdf",
            file_hash="c" * 64,
            is_audit_summary=True,
            audit_year=2026,
            ai_actions_json='{"missing_items":["אישור חשמל"]}',
        )
        db.session.add(summary)
        db.session.commit()
        result = reconcile_audit_summary(summary)
        self.assertEqual(result["warning"], "סיכום הביקורת עדיין אינו משויך לאתר או לביקורת.")


if __name__ == "__main__":
    unittest.main()
