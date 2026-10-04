"""Seed the initial fire-safety requirement catalog for a fresh production database."""
from alembic import op
import sqlalchemy as sa

revision = "0009_seed_initial_catalog"
down_revision = "0008_document_links"
branch_labels = None
depends_on = None

ZONES = [
    ("תשתיות כלליות", "ראשי"),
    ("מגורים (פנימייה)", "8855-7"),
    ("מטבח וחדר אוכל", "8859-7"),
    ("אולם ספורט", "8853-7"),
    ("בית מדרש", "8860-7"),
]

REQUIREMENTS = [
    ("מגורים (פנימייה)", "ציוד כיבוי", "טופס 1"),
    ("מגורים (פנימייה)", "תחזוקת מטפים", "טופס 2"),
    ("מגורים (פנימייה)", "חשמל", "טופס 3"),
    ("מגורים (פנימייה)", "גילוי אש", "טופס 4"),
    ("מגורים (פנימייה)", "לוחות חשמל", "טופס 5"),
    ("מגורים (פנימייה)", "כריזה", "טופס 6"),
    ("מגורים (פנימייה)", "ספרינקלרים", "טופס 7"),
    ("מגורים (פנימייה)", "תיק שטח", "טופס 13"),
    ("מגורים (פנימייה)", "הדרכת עובדים", "טופס 14"),
    ("מטבח וחדר אוכל", "מערכת גז", "טופס 18"),
    ("אולם ספורט", "שחרור עשן", "טופס 10"),
    ("בית מדרש", "גילוי אש", "טופס 4"),
]

def upgrade():
    bind = op.get_bind()
    for zone_name, file_number in ZONES:
        bind.execute(
            sa.text("""
                INSERT INTO zones (zone_name, file_number)
                VALUES (:name, :number)
                ON CONFLICT (file_number) DO NOTHING
            """),
            {"name": zone_name, "number": file_number},
        )

    rows = bind.execute(sa.text("SELECT id, zone_name FROM zones")).mappings().all()
    zone_ids = {row["zone_name"]: row["id"] for row in rows}

    for zone_name, system_name, required_form in REQUIREMENTS:
        zone_id = zone_ids.get(zone_name)
        if zone_id is None:
            continue
        exists = bind.execute(
            sa.text("""
                SELECT 1 FROM system_requirements
                WHERE zone_id = :zone_id AND system_name = :system_name
                  AND required_form = :required_form
                LIMIT 1
            """),
            {"zone_id": zone_id, "system_name": system_name, "required_form": required_form},
        ).first()
        if not exists:
            bind.execute(
                sa.text("""
                    INSERT INTO system_requirements (zone_id, system_name, required_form)
                    VALUES (:zone_id, :system_name, :required_form)
                """),
                {"zone_id": zone_id, "system_name": system_name, "required_form": required_form},
            )

def downgrade():
    pass
