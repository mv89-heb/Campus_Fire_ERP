import os

from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()


# Render starts this module with `gunicorn run:app`. Apply all pending
# Alembic migrations before serving traffic. Do this unconditionally rather
# than relying on FLASK_ENV being set correctly, because production database
# schema must always match the SQLAlchemy models shipped with the release.
try:
    # Invoke the registered Flask-Migrate CLI command through Flask's runner.
    # This follows the exact same code path exercised by `flask db upgrade`
    # in CI, and surfaces Alembic output in Render startup logs.
    with app.app_context():
        migration_result = app.test_cli_runner().invoke(args=['db', 'upgrade'])
        database_backend = db.engine.url.get_backend_name()
        database_host = db.engine.url.host or 'local'
        schema_revision = db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
    if migration_result.exit_code != 0:
        raise RuntimeError(
            'Alembic startup migration failed: '
            + (migration_result.output or 'no diagnostic output')
        )
    print(
        '[startup-migration] '
        f'backend={database_backend} host={database_host} '
        f'revision={schema_revision} '
        f'output={(migration_result.output or "database already at migration head").strip()}',
        flush=True,
    )
except Exception:
    app.logger.exception('Database migration failed during startup')
    raise


if __name__ == '__main__':
    is_production = os.environ.get('FLASK_ENV', os.environ.get('ENV', 'development')).lower() in {'production', 'prod'}
    app.run(
        host=os.environ.get('HOST', '0.0.0.0'),
        port=int(os.environ.get('PORT', '5000')),
        debug=not is_production,
    )
