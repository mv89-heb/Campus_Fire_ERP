"""Baseline/provisioning marker for the production schema.

Revision ID: 0001_schema_baseline
Revises:
Create Date: 2026-08-13

Fresh production databases may be completely empty. The original baseline
only stamped the revision and therefore could not provision a new Postgres
database. This revision now creates the current SQLAlchemy schema
non-destructively; later migrations remain responsible for additive repairs
and indexes. Existing installations that already recorded 0001 are not
re-run.
"""
from alembic import op
from app import create_app
from app.extensions import db

revision = "0001_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    app = create_app()
    with app.app_context():
        db.metadata.create_all(bind=op.get_bind())

def downgrade():
    pass
