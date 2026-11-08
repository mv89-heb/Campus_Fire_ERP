import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import session

from app import create_app
from app.extensions import db
from app.models import Document, User
from app.api.routes import _document_access_allowed
from app.services.permissions import can_write


TEST_PASSWORD = 'Strong-Test-1234'


class TestConfig:
    ENV = 'testing'
    IS_PRODUCTION = False
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = tempfile.gettempdir()
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    MAX_PDF_BYTES = 10 * 1024 * 1024
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


class SecurityGuardTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_api_requires_authentication(self):
        response = self.client.get('/api/sites')
        self.assertEqual(response.status_code, 401)

    def test_first_user_bootstrap_forces_super_admin(self):
        response = self.client.post(
            '/api/users',
            json={'username': 'root', 'password': TEST_PASSWORD, 'role': 'viewer'},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['role'], 'super_admin')

    def test_weak_bootstrap_password_is_rejected(self):
        response = self.client.post(
            '/api/users',
            json={'username': 'root', 'password': 'weak-password'},
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_write(self):
        self.client.post(
            '/api/users',
            json={'username': 'root', 'password': TEST_PASSWORD},
        )
        with self.app.app_context():
            from app.models import User
            user = User.query.filter_by(username='root').first()
            user.role = 'viewer'
            db.session.commit()
            user_id = user.id
            username = user.username

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username
            sess['role'] = 'viewer'
            sess['csrf_token'] = 'viewer-csrf'

        response = self.client.post(
            '/api/sites',
            json={'name': 'Blocked'},
            headers={'X-CSRF-Token': 'viewer-csrf'},
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_csrf_is_rejected(self):
        self.client.post(
            '/api/users',
            json={'username': 'root', 'password': TEST_PASSWORD},
        )
        self.client.post(
            '/api/auth/login',
            json={'username': 'root', 'password': TEST_PASSWORD},
        )
        response = self.client.post('/api/sites', json={'name': 'Missing CSRF'})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_write_after_login(self):
        self.client.post(
            '/api/users',
            json={'username': 'root', 'password': TEST_PASSWORD},
        )
        response = self.client.post(
            '/api/auth/login',
            json={'username': 'root', 'password': TEST_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        csrf_token = response.get_json().get('csrf_token')
        self.assertTrue(csrf_token)

        response = self.client.post(
            '/api/sites',
            json={'name': 'Protected Site'},
            headers={'X-CSRF-Token': csrf_token},
        )
        self.assertEqual(response.status_code, 201)

    def test_rbac_matrix(self):
        self.assertTrue(can_write('inspector', '/api/audits'))
        self.assertTrue(can_write('inspector', '/api/deficiencies/12'))
        self.assertFalse(can_write('inspector', '/api/sites'))
        self.assertFalse(can_write('inspector', '/api/users'))

        self.assertTrue(can_write('technician', '/api/equipment/12'))
        self.assertTrue(can_write('technician', '/api/tasks/12/complete'))
        self.assertFalse(can_write('technician', '/api/equipment'))
        self.assertFalse(can_write('technician', '/api/tasks'))
        self.assertFalse(can_write('technician', '/api/sites'))

        self.assertFalse(can_write('viewer', '/api/audits'))
        self.assertTrue(can_write('manager', '/api/sites'))
        self.assertTrue(can_write('admin', '/api/users/12'))
        self.assertTrue(can_write('super_admin', '/api/admin/storage'))


    def test_inactive_session_user_cannot_access_document_file(self):
        with self.app.test_request_context('/api/documents/1/file'):
            session['user_id'] = 123
            with patch('app.api.routes.db.session.get', return_value=SimpleNamespace(active=False)):
                self.assertFalse(_document_access_allowed(1))
            self.assertNotIn('user_id', session)

    def test_active_session_user_can_access_document_file(self):
        with self.app.test_request_context('/api/documents/1/file'):
            session['user_id'] = 123
            with patch('app.api.routes.db.session.get', return_value=SimpleNamespace(active=True)):
                self.assertTrue(_document_access_allowed(1))

    def test_document_context_get_does_not_persist_automatic_links(self):
        with self.app.app_context():
            user = User(username='context-admin', password_hash='unused', role='admin', active=True)
            document = Document(
                file_name='context.pdf',
                file_path='documents/context.pdf',
                file_hash='c' * 64,
                status='active',
            )
            db.session.add_all([user, document])
            db.session.commit()
            user_id, document_id = user.id, document.id

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = 'context-admin'
            sess['role'] = 'admin'

        with patch('app.api.routes.link_svc.resolve_document', return_value={'site': {'status': 'missing'}}) as resolve:
            response = self.client.get(f'/api/document-intelligence/{document_id}/context')

        self.assertEqual(response.status_code, 200)
        resolve.assert_called_once()
        self.assertFalse(resolve.call_args.kwargs.get('persist', True))


if __name__ == '__main__':
    unittest.main()
