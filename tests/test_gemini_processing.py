import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.gemini_document_service import is_processing_stale


class GeminiProcessingLeaseTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 8, 12, 0, 0)

    def test_recent_processing_is_not_stale(self):
        document = SimpleNamespace(
            ai_status='processing',
            ai_processing_started_at=self.now - timedelta(minutes=10),
            uploaded_at=self.now - timedelta(days=90),
        )
        self.assertFalse(is_processing_stale(document, now=self.now, stale_after_minutes=30))

    def test_expired_processing_lease_is_stale(self):
        document = SimpleNamespace(
            ai_status='processing',
            ai_processing_started_at=self.now - timedelta(minutes=45),
            uploaded_at=self.now - timedelta(days=90),
        )
        self.assertTrue(is_processing_stale(document, now=self.now, stale_after_minutes=30))

    def test_legacy_processing_without_lease_uses_conservative_upload_age(self):
        old_document = SimpleNamespace(
            ai_status='processing',
            ai_processing_started_at=None,
            uploaded_at=self.now - timedelta(days=2),
        )
        recent_document = SimpleNamespace(
            ai_status='processing',
            ai_processing_started_at=None,
            uploaded_at=self.now - timedelta(hours=2),
        )
        self.assertTrue(is_processing_stale(old_document, now=self.now))
        self.assertFalse(is_processing_stale(recent_document, now=self.now))

    def test_non_processing_document_is_never_stale(self):
        document = SimpleNamespace(
            ai_status='failed',
            ai_processing_started_at=self.now - timedelta(days=3),
            uploaded_at=self.now - timedelta(days=90),
        )
        self.assertFalse(is_processing_stale(document, now=self.now))


if __name__ == '__main__':
    unittest.main()
