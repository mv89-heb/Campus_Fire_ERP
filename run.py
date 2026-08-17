import os

from app import create_app

app = create_app()


# Render starts this module directly with `gunicorn run:app`. Apply pending
# Alembic migrations before serving traffic so additive schema changes are
# never silently skipped in production.
if os.environ.get('FLASK_ENV', os.environ.get('ENV', 'development')).lower() in {'production', 'prod'}:
    try:
        from flask_migrate import upgrade
        with app.app_context():
            upgrade()
    except Exception:
        app.logger.exception('Production database migration failed during startup')
        raise


if __name__ == '__main__':
    is_production = os.environ.get('FLASK_ENV', os.environ.get('ENV', 'development')).lower() in {'production', 'prod'}
    app.run(
        host=os.environ.get('HOST', '0.0.0.0'),
        port=int(os.environ.get('PORT', '5000')),
        debug=not is_production,
    )
