import os

from app import create_app
from app.config import Config
from app.services.startup_migrations import (
    apply_startup_migrations,
    normalize_migration_database_url,
    validate_direct_migration_url,
)

app = create_app()

# Keep application traffic on DATABASE_URL. Alembic can use a separate,
# direct owner connection so the runtime role does not need schema privileges.
migration_database_url = normalize_migration_database_url(os.environ.get("MIGRATION_DATABASE_URL", ""))
if migration_database_url:
    validate_direct_migration_url(migration_database_url)

    class MigrationConfig(Config):
        SQLALCHEMY_DATABASE_URI = migration_database_url
        AUTO_CREATE_DB = False
        IS_PRODUCTION = True

    migration_app = create_app(MigrationConfig)
else:
    # Backward-compatible fallback until MIGRATION_DATABASE_URL is configured.
    migration_app = app

apply_startup_migrations(app, migration_app)


if __name__ == "__main__":
    is_production = os.environ.get("FLASK_ENV", os.environ.get("ENV", "development")).lower() in {"production", "prod"}
    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
        debug=not is_production,
    )
