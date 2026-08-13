import os
import tempfile
import unittest

from app import create_app
from app.extensions import db


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
            json={'username': 'root', 'password': 'strong-test-password', 'role': 'viewer'},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['role'], 'super_admin')

    def test_viewer_cannot_write(self):
        self.client.post(
            '/api/users',
            json={'username': 'root', 'password': 'strong-test-password'},
        )
        with self.app.app_context():
            from app.models import User
            from flask import session
            user = User.query.filter_by(username='root').first()

        with self.client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['username'] = user.username
            sess['role'] = 'viewer'

        response = self.client.post('/api/sites', json={'name': 'Blocked'})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_write_after_login(self):
        self.client.post(
            '/api/users',
            json={'username': 'root', 'password': 'strong-test-password'},
        )
        response = self.client.post(
            '/api/auth/login',
            json={'username': 'root', 'password': 'strong-test-password'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json().get('csrf_token'))

        response = self.client.post('/api/sites', json={'name': 'Protected Site'})
        self.assertEqual(response.status_code, 201)


if __name__ == '__main__':
    unittest.main()
