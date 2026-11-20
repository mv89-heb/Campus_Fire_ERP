"""Run Alembic migrations using a dedicated direct connection when configured."""
from urllib.parse import urlparse

from sqlalchemy import text

from app.extensions import db


def normalize_migration_database_url(database_url):
    """Select the installed psycopg2 driver for plain PostgreSQL URLs."""
    database_url = str(database_url or "").strip()
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + database_url[len("postgresql://"):]
    return database_url


def validate_direct_migration_url(database_url):
    """Require a direct Postgres endpoint for migration work; never log the URL."""
    parsed = urlparse(str(database_url or "").strip())
    if parsed.scheme not in {"postgresql", "postgresql+psycopg2"} or not parsed.hostname:
        raise RuntimeError("MIGRATION_DATABASE_URL must be a valid PostgreSQL connection URL")
    if "-pooler" in parsed.hostname:
        raise RuntimeError("MIGRATION_DATABASE_URL must use Neon's direct endpoint, not the pooler")
    return parsed.hostname


def verify_migration_connection_owner():
    """Ensure the migration connection is actually the owner of application tables."""
    if db.engine.url.get_backend_name() != "postgresql":
        return None
    row = db.session.execute(
        text(
            "SELECT current_user, pg_get_userbyid(c.relowner) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname='zones'"
        )
    ).first()
    if not row:
        raise RuntimeError("Could not verify ownership of public.zones for Alembic")
    current_role, table_owner = row
    if current_role != table_owner:
        raise RuntimeError(
            f"ALEMBIC_DATABASE_URL must use the table owner; "
            f"connected role {current_role!r} does not own public.zones"
        )
    return current_role


def apply_startup_migrations(runtime_app, migration_app):
    """Apply migrations with the migration app, then report its resulting revision."""
    try:
        with migration_app.app_context():
            migration_role = verify_migration_connection_owner()
            if migration_role:
                runtime_app.logger.info(
                    "[startup-migration-connection] role=%s host=%s",
                    migration_role,
                    db.engine.url.host or "unknown",
                )
            migration_result = migration_app.test_cli_runner().invoke(args=["db", "upgrade"])
            if migration_result.exit_code != 0:
                details = (migration_result.output or "").strip()
                if migration_result.exception is not None:
                    exception = migration_result.exception
                    exception_detail = f"{type(exception).__name__}: {exception}"
                    details = f"{details}\n{exception_detail}".strip()
                    if migration_result.exc_info:
                        migration_app.logger.error(
                            "Alembic CLI traceback during startup migration",
                            exc_info=migration_result.exc_info,
                        )
                raise RuntimeError(
                    "Alembic startup migration failed: "
                    + (details or "no diagnostic output or exception details")
                )

            database_backend = db.engine.url.get_backend_name()
            database_host = db.engine.url.host or "local"
            schema_revision = db.session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            migration_output = (
                migration_result.output or "database already at migration head"
            ).strip()

        message = (
            "[startup-migration] "
            f"backend={database_backend} host={database_host} "
            f"revision={schema_revision} output={migration_output}"
        )
        print(message, flush=True)
        runtime_app.logger.info(message)
        return schema_revision
    except Exception:
        runtime_app.logger.exception("Database migration failed during startup")
        raise
