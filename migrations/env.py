from logging.config import fileConfig
from pathlib import Path

from alembic import context
from app import create_app
from app.extensions import db

config = context.config

# Flask-Migrate invokes Alembic with ``migrations/alembic.ini`` as the
# configuration path. Older checkouts may not contain that file, so logging
# configuration must never make the migration command fail merely because the
# optional logging config file is absent.
if config.config_file_name:
    config_path = Path(config.config_file_name)
    if config_path.is_file():
        fileConfig(str(config_path))

app = create_app()
target_metadata = db.metadata


def get_url():
    return app.config['SQLALCHEMY_DATABASE_URI']


def run_migrations_offline():
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with app.app_context():
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
