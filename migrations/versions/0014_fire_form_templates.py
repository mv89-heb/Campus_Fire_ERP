"""Create reusable official fire form template library."""
from alembic import op
import sqlalchemy as sa

revision = "0014_fire_form_templates"
down_revision = "0013_document_classification"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "fire_form_templates" not in inspector.get_table_names():
        op.create_table(
            "fire_form_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("original_filename", sa.String(length=255), nullable=False),
            sa.Column("storage_path", sa.String(length=500), nullable=False),
            sa.Column("file_hash", sa.String(length=64), nullable=False),
            sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("storage_path", name="uq_fire_form_templates_storage_path"),
            sa.UniqueConstraint("file_hash", name="uq_fire_form_templates_file_hash"),
        )

    existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("fire_form_templates")}
    if "ix_fire_form_templates_active" not in existing_indexes:
        op.create_index("ix_fire_form_templates_active", "fire_form_templates", ["active"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "fire_form_templates" in inspector.get_table_names():
        indexes = {item["name"] for item in inspector.get_indexes("fire_form_templates")}
        if "ix_fire_form_templates_active" in indexes:
            op.drop_index("ix_fire_form_templates_active", table_name="fire_form_templates")
        op.drop_table("fire_form_templates")
