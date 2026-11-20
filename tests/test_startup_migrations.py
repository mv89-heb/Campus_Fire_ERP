import unittest

from app.services.startup_migrations import validate_direct_migration_url


class DirectMigrationConnectionTests(unittest.TestCase):
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
