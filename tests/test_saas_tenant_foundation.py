"""Regression tests for organization membership and tenant isolation."""
from pathlib import Path
import unittest
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (
    LEGACY_ORGANIZATION_ID,
    Organization,
    OrganizationMembership,
    User,
    Document,
    Site,
    Building,
)
from app.services.tenant_context import (
    TENANT_MODELS, TenantAccessError, bind_organization, bind_document_access,
    document_access_token_valid,
)


OTHER_ORGANIZATION_ID = "00000000-0000-4000-8000-000000000002"


class SaaSTenantFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class TestConfig(Config):
            TESTING = True
            DEBUG = False
            IS_RENDER = False
            IS_PRODUCTION = False
            SECRET_KEY = "saas-tenant-tests-secret"
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            AUTO_CREATE_DB = True
            RATELIMIT_STORAGE_URI = "memory://"

        cls.app = create_app(TestConfig)
        with cls.app.app_context():
            if not db.session.get(Organization, OTHER_ORGANIZATION_ID):
                db.session.add(Organization(
                    id=OTHER_ORGANIZATION_ID,
                    name="Other organization",
                    slug="other-organization",
                    status="active",
                ))
                db.session.commit()
            db.session.remove()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()


    def test_production_never_runs_create_all_even_if_legacy_flag_is_enabled(self):
        class ProductionConfig(Config):
            TESTING = True
            DEBUG = False
            IS_RENDER = False
            IS_PRODUCTION = True
            SECRET_KEY = "production-startup-test-secret"
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            AUTO_CREATE_DB = True
            REQUIRE_SUPABASE_STORAGE = False

        with patch("app.extensions.db.create_all") as create_all:
            app = create_app(ProductionConfig)
            self.assertTrue(app.config["IS_PRODUCTION"])
            create_all.assert_not_called()

    def test_every_business_model_is_organization_scoped(self):
        self.assertEqual(len(TENANT_MODELS), 16)
        for model in TENANT_MODELS:
            with self.subTest(model=model.__name__):
                self.assertIn("organization_id", model.__table__.columns)
                foreign_keys = model.__table__.columns.organization_id.foreign_keys
                self.assertTrue(any(fk.target_fullname == "organizations.id" for fk in foreign_keys))

    def test_orm_reads_are_scoped_to_the_active_organization(self):
        with self.app.app_context():
            db.session.info["organization_id"] = LEGACY_ORGANIZATION_ID
            own_site = Site(name="Tenant boundary own site")
            db.session.add(own_site)
            db.session.commit()
            own_id = own_site.id

            db.session.info["organization_id"] = OTHER_ORGANIZATION_ID
            other_site = Site(name="Tenant boundary other site")
            db.session.add(other_site)
            db.session.commit()
            other_id = other_site.id

            db.session.info["organization_id"] = LEGACY_ORGANIZATION_ID
            self.assertIsNotNone(Site.query.filter_by(id=own_id).first())
            self.assertIsNone(Site.query.filter_by(id=other_id).first())

            db.session.info["organization_id"] = OTHER_ORGANIZATION_ID
            self.assertIsNotNone(Site.query.filter_by(id=other_id).first())
            self.assertIsNone(Site.query.filter_by(id=own_id).first())
            db.session.remove()

    def test_cross_organization_foreign_key_is_rejected(self):
        with self.app.app_context():
            db.session.info["organization_id"] = OTHER_ORGANIZATION_ID
            other_site = Site(name="Tenant boundary foreign-key target")
            db.session.add(other_site)
            db.session.commit()
            other_site_id = other_site.id

            db.session.info["organization_id"] = LEGACY_ORGANIZATION_ID
            db.session.add(Building(site_id=other_site_id, name="Forbidden cross-tenant building"))
            with self.assertRaises(TenantAccessError):
                db.session.flush()
            db.session.rollback()
            db.session.remove()


    def test_authenticated_document_download_cannot_cross_organizations(self):
        with self.app.app_context():
            user = User(
                username="tenant-boundary-user",
                password_hash="not-used-by-this-test",
                role="admin",
                active=True,
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(OrganizationMembership(
                organization_id=LEGACY_ORGANIZATION_ID,
                user_id=user.id,
                role="admin",
                status="active",
            ))

            db.session.info["organization_id"] = OTHER_ORGANIZATION_ID
            document = Document(
                file_name="other-tenant.pdf",
                file_path="other-tenant/private.pdf",
                file_hash="tenant-boundary-document-hash",
                status="active",
            )
            db.session.add(document)
            db.session.commit()
            user_id = user.id
            document_id = document.id
            db.session.remove()

        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id
            browser_session["organization_id"] = LEGACY_ORGANIZATION_ID
            browser_session["role"] = "admin"
            browser_session["csrf_token"] = "tenant-boundary-csrf"

        response = client.get(f"/api/documents/{document_id}/file")
        self.assertEqual(response.status_code, 404)


    def test_postgres_tenant_context_helpers_bind_one_organization_or_one_document(self):
        with self.app.app_context():
            bind_organization(db.session, LEGACY_ORGANIZATION_ID)
            self.assertEqual(db.session.info.get("organization_id"), LEGACY_ORGANIZATION_ID)
            self.assertNotIn("allowed_document_id", db.session.info)

            bind_document_access(db.session, 123)
            self.assertNotIn("organization_id", db.session.info)
            self.assertEqual(db.session.info.get("allowed_document_id"), "123")
            db.session.remove()

    def test_signed_document_token_is_scoped_to_its_document_id(self):
        from itsdangerous import URLSafeTimedSerializer

        secret = "signed-document-test-secret"
        serializer = URLSafeTimedSerializer(
            secret,
            salt="campus-fire-document-access-v1",
        )
        token = serializer.dumps({"doc_id": 123})
        self.assertTrue(document_access_token_valid(token, 123, secret))
        self.assertFalse(document_access_token_valid(token, 124, secret))
        self.assertFalse(document_access_token_valid("invalid-token", 123, secret))

    def test_forced_rls_migration_protects_all_tenant_tables(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations" / "versions" / "0017_force_tenant_rls.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ENABLE ROW LEVEL SECURITY", migration)
        self.assertIn("FORCE ROW LEVEL SECURITY", migration)
        self.assertIn("campus_fire_runtime", migration)
        self.assertIn("app.current_organization_id", migration)
        self.assertIn("app.allowed_document_id", migration)
        for model in TENANT_MODELS:
            self.assertIn(f'"{model.__tablename__}"', migration)

    def test_legacy_data_migration_is_additive_and_backfills_all_business_tables(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations" / "versions" / "0016_saas_tenant_foundation.py"
        ).read_text(encoding="utf-8")
        self.assertIn("INSERT INTO organization_memberships", migration)
        self.assertIn("LEGACY_ORGANIZATION_ID", migration)
        for model in TENANT_MODELS:
            self.assertIn(f'"{model.__tablename__}"', migration)
        self.assertNotIn("DROP TABLE", migration.upper().split("DEF DOWNGRADE")[0])


if __name__ == "__main__":
    unittest.main()
