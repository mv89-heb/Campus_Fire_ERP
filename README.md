# Campus Fire ERP

Campus Fire ERP is a Flask-based fire-safety and compliance management system for sites, buildings, inspections, deficiencies, equipment, permits, suppliers, tasks, documents and audit history.

## Security baseline

The `hardening/security-data-integrity` branch is the current security-hardening workstream. It adds global authentication enforcement, role-based write authorization, CSRF protection for authenticated state-changing requests, browser-origin checks, hardened sessions, production secret validation, PDF validation, storage path hardening, production migration controls, rate limiting for authentication/bootstrap endpoints, password policy validation, security response headers and regression tests.

## Production requirements

Set at minimum:

- `SECRET_KEY`
- `DATABASE_URL`
- `RATELIMIT_STORAGE_URI` pointing to shared Redis or another supported shared limiter backend
- `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` when Supabase storage is enabled
- `AUTO_CREATE_DB=false` (recommended/default in production)

Run reviewed Alembic migrations before starting the production application. Do not use `db.create_all()` as a production schema migration mechanism.

## Development

Development can continue to use the local SQLite database and automatic schema creation. Run tests with:

```text
python -m unittest discover -s tests -p "test_*.py" -v
```

The CI workflow also compiles the application, runs the test suite and checks the Alembic CLI configuration.
