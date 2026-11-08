import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Document
from app.services import storage
from app.services import storage_health_service as health


class StorageScanConfig:
    ENV = 'testing'
    IS_PRODUCTION = False
    SECRET_KEY = 'storage-scan-test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    MAX_PDF_BYTES = 10 * 1024 * 1024
    UPLOAD_FOLDER = tempfile.gettempdir()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 3600
    TRUSTED_ORIGINS = ()
    RATELIMIT_STORAGE_URI = 'memory://'
    AUTO_CREATE_DB = True

    @classmethod
    def validate(cls):
        return None


class _FakeBucket:
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def list(self, path='', options=None):
        self.calls += 1
        value = self.pages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class _FakeStorage:
    def __init__(self, bucket):
        self.bucket = bucket

    def from_(self, name):
        return self.bucket


class _FakeClient:
    def __init__(self, bucket):
        self.storage = _FakeStorage(bucket)


class StorageInventorySafetyTests(unittest.TestCase):
    def test_strict_inventory_raises_instead_of_returning_partial_page(self):
        first_page = [
            {'name': f'{i}.pdf', 'metadata': {'size': 1}}
            for i in range(100)
        ]
        bucket = _FakeBucket([first_page, RuntimeError('provider timeout')])
        with patch('app.services.storage.is_configured', return_value=True), patch(
            'app.services.storage._get_client', return_value=_FakeClient(bucket)
        ):
            with self.assertRaises(storage.StorageError):
                storage.list_supabase_files(strict=True)

    def test_best_effort_inventory_keeps_legacy_behavior(self):
        first_page = [
            {'name': f'{i}.pdf', 'metadata': {'size': 1}}
            for i in range(100)
        ]
        bucket = _FakeBucket([first_page, RuntimeError('provider timeout')])
        with patch('app.services.storage.is_configured', return_value=True), patch(
            'app.services.storage._get_client', return_value=_FakeClient(bucket)
        ):
            result = storage.list_supabase_files()
        self.assertEqual(len(result), 100)

    def test_failed_storage_scan_is_marked_incomplete_and_has_no_orphan_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            StorageScanConfig.UPLOAD_FOLDER = folder
            app = create_app(StorageScanConfig)
            with app.app_context():
                db.create_all()
                db.session.add(Document(
                    file_name='existing.pdf',
                    file_path='documents/existing.pdf',
                    file_hash='a' * 64,
                    status='active',
                ))
                db.session.commit()
                with patch.object(health.storage, 'is_configured', return_value=True), patch.object(
                    health.storage, 'get_bucket_name', return_value='documents'
                ), patch.object(
                    health.storage, 'list_supabase_files',
                    side_effect=storage.StorageError('provider timeout'),
                ):
                    result = health.scan(folder)
                    self.assertFalse(result['scan_complete'])
                    self.assertIsNone(result['orphaned'])
                    self.assertIsNone(result['missing'])
                    self.assertEqual(result['orphaned_items'], [])
                    with self.assertRaises(storage.StorageError):
                        health.cleanup_preview(folder)
                db.session.remove()
                db.drop_all()


if __name__ == '__main__':
    unittest.main()
