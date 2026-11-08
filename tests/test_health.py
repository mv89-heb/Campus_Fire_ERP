import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import text

from app import create_app
from app.extensions import db


class ProductionHealthConfig:
    ENV = 'production'
    IS_PRODUCTION = True
    SECRET_KEY = 'health-test-secret'
    SECRET_KEY_FROM_ENV = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    MAX_PDF_BYTES = 10 * 1024 * 1024
    UPLOAD_FOLDER = tempfile.gettempdir()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 3600
    TRUSTED_ORIGINS = ()
    RATELIMIT_STORAGE_URI = 'memory://'
    REQUIRE_SUPABASE_STORAGE = True
    GEMINI_API_KEY = 'test-gemini-key'
    AUTO_CREATE_DB = True

    @classmethod
    def validate(cls):
        return None


class SystemHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        ProductionHealthConfig.UPLOAD_FOLDER = self.temp_dir.name
        self.app = create_app(ProductionHealthConfig)
        self.app.config.update(TESTING=True)
        with self.app.app_context():
            db.session.execute(text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            ))
            db.session.execute(text(
                "INSERT INTO alembic_version (version_num) VALUES ('0013_document_classification')"
            ))
            db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def test_ready_requires_database_catalog_storage_and_gemini_configuration(self):
        with patch('app.api.routes.storage.is_configured', return_value=True), patch(
            'app.api.routes.storage.check_connection', return_value=(True, None)
        ):
            response = self.client.get('/api/system/health')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertTrue(payload['production_mode'])
        self.assertTrue(payload['secret_key_from_environment'])
        self.assertTrue(payload['db_connected'])
        self.assertTrue(payload['zones_seeded'])
        self.assertTrue(payload['upload_folder_writable'])
        self.assertTrue(payload['supabase_configured'])
        self.assertTrue(payload['storage_connected'])
        self.assertTrue(payload['gemini_configured'])

    def test_production_is_not_ready_when_alembic_revision_is_missing(self):
        with self.app.app_context():
            db.session.execute(text("DROP TABLE alembic_version"))
            db.session.commit()

        with patch('app.api.routes.storage.is_configured', return_value=True), patch(
            'app.api.routes.storage.check_connection', return_value=(True, None)
        ):
            response = self.client.get('/api/system/health')

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'degraded')
        self.assertTrue(payload['schema_revision_required'])
        self.assertFalse(payload['schema_revision_ready'])

    def test_production_is_not_ready_when_supabase_is_not_configured(self):
        with patch('app.api.routes.storage.is_configured', return_value=False):
            response = self.client.get('/api/system/health')

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'degraded')
        self.assertFalse(payload['supabase_configured'])
        self.assertFalse(payload['storage_connected'])

    def test_production_is_not_ready_when_supabase_storage_is_unavailable(self):
        with patch('app.api.routes.storage.is_configured', return_value=True), patch(
            'app.api.routes.storage.check_connection',
            return_value=(False, 'private provider diagnostic'),
        ):
            response = self.client.get('/api/system/health')

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertFalse(payload['storage_connected'])
        self.assertNotIn('private provider diagnostic', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
