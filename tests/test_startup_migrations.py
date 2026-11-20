import unittest
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.services.startup_migrations import normalize_migration_database_url, validate_direct_migration_url


class DirectMigrationConnectionTests(unittest.TestCase):
    def test_normalizes_plain_postgres_url_to_installed_psycopg2_driver(self):
        normalized = normalize_migration_database_url(
            "postgresql://owner:secret@ep-example.c-1.us-east-1.aws.neon.tech/neondb"
        )
        self.assertTrue(normalized.startswith("postgresql+psycopg2://"))
        self.assertIn("ep-example.c-1.us-east-1.aws.neon.tech", normalized)

    def test_keeps_explicit_psycopg2_driver_unchanged(self):
        url = "postgresql+psycopg2://owner:secret@ep-example.c-1.us-east-1.aws.neon.tech/neondb"
        self.assertEqual(normalize_migration_database_url(url), url)


    def test_migration_app_database_url_override_wins_over_runtime_url(self):
        owner_url = "postgresql+psycopg2://owner:secret@ep-owner.c-1.us-east-1.aws.neon.tech/neondb"
        runtime_url = "postgresql+psycopg2://runtime:secret@ep-runtime-pooler.c-1.us-east-1.aws.neon.tech/neondb"

        class MigrationConfig(Config):
            TESTING = True
            DEBUG = False
            IS_RENDER = False
            IS_PRODUCTION = True
            SECRET_KEY = "migration-config-test-secret"
            DATABASE_URL = owner_url
            SQLALCHEMY_DATABASE_URI = owner_url
            AUTO_CREATE_DB = False
            REQUIRE_SUPABASE_STORAGE = False

        class RuntimeConfig(Config):
            TESTING = True
            DEBUG = False
            IS_RENDER = False
            IS_PRODUCTION = True
            SECRET_KEY = "runtime-config-test-secret"
            DATABASE_URL = runtime_url
            SQLALCHEMY_DATABASE_URI = runtime_url
            AUTO_CREATE_DB = False
            REQUIRE_SUPABASE_STORAGE = False

        with patch("app.extensions.db.create_all"):
            migration_app = create_app(MigrationConfig)
            runtime_app = create_app(RuntimeConfig)

        self.assertEqual(migration_app.config["SQLALCHEMY_DATABASE_URI"], owner_url)
        self.assertEqual(runtime_app.config["SQLALCHEMY_DATABASE_URI"], runtime_url)

    def test_accepts_direct_neon_postgres_endpoint(self):
        host = validate_direct_migration_url(
            "postgresql://runtime:secret@ep-example.c-1.us-east-1.aws.neon.tech/neondb?sslmode=require"
        )
        self.assertEqual(host, "ep-example.c-1.us-east-1.aws.neon.tech")

    def test_rejects_pooled_neon_endpoint_for_migrations(self):
        with self.assertRaisesRegex(RuntimeError, "direct endpoint"):
            validate_direct_migration_url(
                "postgresql://runtime:secret@ep-example-pooler.c-1.us-east-1.aws.neon.tech/neondb"
            )

    def test_rejects_non_postgres_or_malformed_urls_without_echoing_secrets(self):
        with self.assertRaises(RuntimeError) as context:
            validate_direct_migration_url("sqlite:///tmp/test.db")
        self.assertNotIn("secret", str(context.exception))


if __name__ == "__main__":
    unittest.main()
