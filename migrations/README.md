# Database migrations

This directory is managed by Flask-Migrate/Alembic.

## Production rule

Production deployments must not call `db.create_all()`. Set `FLASK_ENV=production` (or `ENV=production`) so `AUTO_CREATE_DB` defaults to `false`, then run migrations before starting the web process.

## Existing database bootstrap

The repository historically created its schema with SQLAlchemy `create_all()`. The first migration (`0001`) is therefore a **schema baseline marker** rather than a destructive rebuild. For an existing database whose schema already matches `app/models.py`, stamp it once:

```text
flask --app run.py db stamp head
```

After that, all schema changes must be introduced through:

```text
flask --app run.py db migrate -m "describe change"
flask --app run.py db upgrade
```

Always inspect generated migrations before applying them to production.

## New database

For a completely new production database, create the schema from a freshly generated migration before deployment. Do not use `AUTO_CREATE_DB=true` as a production workaround.
