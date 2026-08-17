import os

from app import create_app

app = create_app()


# Render starts this module with `gunicorn run:app`. Apply all pending
# Alembic migrations before serving traffic. Do this unconditionally rather
# than relying on FLASK_ENV being set correctly, because production database
# schema must always match the SQLAlchemy models shipped with the release.
try:
    from flask_migrate import upgrade
    with app.app_context():
        upgrade()
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
