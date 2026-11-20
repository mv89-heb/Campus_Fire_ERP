from logging.config import fileConfig
from pathlib import Path

from alembic import context
from flask import current_app

from app.extensions import db

config = context.config

# Flask-Migrate executes this file inside the active Flask application context.
# Use that exact app so a dedicated ALEMBIC_DATABASE_URL is not replaced by
# the runtime DATABASE_URL. Creating another app here silently breaks the
# separation between migration and runtime database roles.
if config.config_file_name:
    config_path = Path(config.config_file_name)
    if config_path.is_file():
        fileConfig(str(config_path))

app = current_app._get_current_object()
target_metadata = db.metadata


def get_url():
    return app.config["SQLALCHEMY_DATABASE_URI"]


def run_migrations_offline():
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with db.engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
