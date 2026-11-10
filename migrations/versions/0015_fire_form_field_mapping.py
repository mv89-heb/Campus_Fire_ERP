"""Add field mapping schema to fire form templates."""
from alembic import op
import sqlalchemy as sa

revision = "0015_fire_form_field_mapping"
down_revision = "0014_fire_form_templates"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("fire_form_templates")}
    if "fields_schema" not in columns:
        op.add_column("fire_form_templates", sa.Column("fields_schema", sa.Text(), nullable=False, server_default="[]"))


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("fire_form_templates")}
    if "fields_schema" in columns:
        op.drop_column("fire_form_templates", "fields_schema")
