import tempfile
import unittest
from datetime import date

from app import create_app
from app.extensions import db
from app.models import Document, User


class DatePolicyApiTests(unittest.TestCase):
    def setUp(self):
        class TestConfig:
            TESTING = True
            ENV = "testing"
            IS_PRODUCTION = False
            SECRET_KEY = "date-policy-test-secret"
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {}
            UPLOAD_FOLDER = tempfile.gettempdir()
            MAX_CONTENT_LENGTH = 10 * 1024 * 1024
            MAX_PDF_BYTES = 10 * 1024 * 1024
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SECURE = False
            SESSION_COOKIE_SAMESITE = "Lax"
            PERMANENT_SESSION_LIFETIME = 3600
            TRUSTED_ORIGINS = ()
            RATELIMIT_STORAGE_URI = "memory://"
            AUTO_CREATE_DB = True
            DOCUMENT_POLICY_YEAR = 2026
            DOCUMENT_GRACE_PERIOD_DAYS = 0

            @classmethod
            def validate(cls):
                return None

        self.app = create_app(TestConfig)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        with self.app.app_context():
            self.manager = User(username="manager", password_hash="unused", role="manager", active=True)
            self.admin = User(username="admin", password_hash="unused", role="admin", active=True)
            self.document = Document(
                file_name="certificate.pdf", file_path="certificate.pdf",
                file_hash="d" * 64, issue_date=date(2025, 1, 1),
            )
            db.session.add_all([self.manager, self.admin, self.document])
            db.session.commit()
            self.manager_id = self.manager.id
            self.admin_id = self.admin.id
            self.document_id = self.document.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as(self, user_id, username):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = username
            sess["csrf_token"] = "test-csrf"

    def test_future_issue_date_is_rejected_by_manual_review_api(self):
        self.login_as(self.manager_id, "manager")
        response = self.client.post(
            f"/api/documents/{self.document_id}/date-review",
            json={"issue_date": "2026-12-01", "expiry_date": "2027-12-01"},
            headers={"X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "FUTURE_ISSUE_DATE")

    def test_manager_can_correct_dates_and_recalculate(self):
        self.login_as(self.manager_id, "manager")
        response = self.client.post(
            f"/api/documents/{self.document_id}/date-review",
            json={"issue_date": "2026-01-01", "expiry_date": "2027-01-01"},
            headers={"X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["calculated_status"], "active")

    def test_admin_cannot_override_conflicting_date_extraction_as_active(self):
        with self.app.app_context():
            document = db.session.get(Document, self.document_id)
            document.date_extraction_conflict = True
            db.session.commit()
        self.login_as(self.admin_id, "admin")
        response = self.client.post(
            f"/api/documents/{self.document_id}/date-override",
            json={"status": "active", "reason": "נבדק אך קיימת סתירה"},
            headers={"X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "DATE_CORRECTION_REQUIRED")

    def test_only_admin_can_apply_status_override(self):
        self.login_as(self.manager_id, "manager")
        denied = self.client.post(
            f"/api/documents/{self.document_id}/date-override",
            json={"status": "active", "reason": "אישור חריג לבדיקה"},
            headers={"X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(denied.status_code, 403)

        self.login_as(self.admin_id, "admin")
        allowed = self.client.post(
            f"/api/documents/{self.document_id}/date-override",
            json={"status": "active", "reason": "אישור חריג לאחר בדיקה מוסמכת"},
            headers={"X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["effective_status"], "active")


if __name__ == "__main__":
    unittest.main()
