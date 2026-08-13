"""Baseline marker for the pre-Alembic production schema.

Revision ID: 0001_schema_baseline
Revises:
Create Date: 2026-08-13
"""

from alembic import op


revision = "0001_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Existing installations were created with SQLAlchemy create_all(). This
    # revision deliberately records that schema as the migration baseline
    # without attempting a destructive rebuild or guessing the live schema.
    pass


def downgrade():
    # The baseline has no reversible schema operation. Dropping every table
    # here would be unsafe and would turn a versioning marker into a destructive
    # database command.
    pass
