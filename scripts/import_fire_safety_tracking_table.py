#!/usr/bin/env python3
"""Idempotently import the fire-safety tracking spreadsheet into the existing tasks table.

Run from the repository root in an environment with the production DATABASE_URL:
    python scripts/import_fire_safety_tracking_table.py
Preview without writing:
    python scripts/import_fire_safety_tracking_table.py --dry-run

No schema changes are made. Existing tasks are never deleted or overwritten.
"""
import argparse
import logging

from app import create_app
from app.extensions import db
from app.models import Task

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOG = logging.getLogger("fire-safety-import")

SOURCE = "Fire_Safety_Tracking_Table_All_Files (1).xlsx"

# Source row number, phase/week, task, asset, case number, form, owner, notes.
ROWS = [
    (4, "שבוע 1", "פתיחת יציאות חירום חסומות במיטות", "פנימייה א' (>200 מיטות)", "5588-21", "-", "צוות תחזוקה", "קריטי! חסימת דלתות מילוט (חוזר על עצמו)"),
    (5, "שבוע 1", "פינוי מסדרונות (קומה 2) וחדרים טכניים", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 20 (הצהרה)", "צוות תחזוקה", "פינוי סחורה, קרטונים וציוד"),
    (6, "שבוע 1", "הסרת מכשירי בישול וטיגון מחדרי הלינה", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 20 (הצהרה)", "צוות פנימייה", "איסור בישול בחדרים (יש מטבח באתר)"),
    (7, "שבוע 1", "חיבור סוללות ותיקון זליגות ברכזת האש", "פנימייה א' (>200 מיטות)", "5588-21", "-", "צוות תחזוקה / טכנאי", "תקינות רכזת ראשית ואביזרים מנותקים"),
    (8, "שבוע 1", "תיקון/השלמת שלטי יציאה ותאורה", "פנימייה א' (>200 מיטות)", "5588-21", "-", "צוות תחזוקה", "שלטי יציאה שבורים/חסרים במדרגות מתכת"),
    (9, "שבוע 2", "אישור גילוי אש וכיבוי ארונות חשמל", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 4 וטופס 5", "חברת מיגון אש", "כולל נספח ג' לתקן גילוי אש ותיקונים"),
    (10, "שבוע 2", "אישור מערכת ספרינקלרים ורשת מים", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 7 וטופס 10", "מעבדה מוסמכת", "השלמת מתזים בקומה 2, תקן 1928"),
    (11, "שבוע 2", "אישור חשמל ותאורת חירום", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 3", "חשמלאי בודק מוסמך", "כולל מפסק חירום וטבלת לוחות ואמפר"),
    (12, "שבוע 2", "אישור מתקן גז וגלאי גפ״מ", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 20 (הצהרה) / טופס 25", "מתקין גז מורשה", "הצהרה שאין גז בדירת הרב בקומה 2"),
    (13, "שבוע 2", "אישור מערכת כריזת חירום", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 6", "טכנאי כריזה", "לפי התקן הנדרש (טופס 6 לכריזה)"),
    (14, "שבוע 2", "אישור מיזוג אוויר ושחרור עשן", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 10 וטופס 11", "מהנדס / מעבדה", "תעלות ומדפים מרכזיים"),
    (15, "שבוע 3", "הכנה ועדכון תיק שטח (נציב 809)", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 13", "הנהלת הישיבה", "חובה בפנימייה מעל 90 מיטות"),
    (16, "שבוע 3", "ביצוע והחתמת הדרכת אש לעובדים", "פנימייה א' (>200 מיטות)", "5588-21", "טופס 14", "אחראי בטיחות", "הדרכה שנתית לעובדים"),
    (17, "שבוע 3", "חתימה על הצהרת פינוי מסדרונות ותמונות", "פנימייה א' (>200 מיטות)", "5588-21", "הצהרה + תמונות", "הנהלה", "הוכחה ויזואלית למפקח"),
    (18, "שבוע 1", "חיבור והפעלת רכזת אש וקרוואנים", "אולם ספורט", "5588-01", "-", "צוות תחזוקה", "הרכזת והקרוואנים היו מנותקים"),
    (19, "שבוע 1", "השמשת מערכת כיבוי אוטומטית בלוח חשמל", "אולם ספורט", "5588-01", "טופס 5", "טכנאי מיגון אש", "הכיבוי האוטומטי היה מנותק לגמרי"),
    (20, "שבוע 1", "פינוי חסמי גישה מעמדות כיבוי", "אולם ספורט", "5588-01", "-", "צוות תחזוקה", "פינוי ציוד מעבדות"),
    (21, "שבוע 2", "אישור גילוי אש וארונות חשמל", "אולם ספורט", "5588-01", "טופס 4 וטופס 5", "חברת מיגון אש", "כולל נספח ג' וקרוואנים"),
    (22, "שבוע 2", "אישור חשמל ותאורת חירום", "אולם ספורט", "5588-01", "טופס 3", "חשמלאי בודק", "כולל גנרטור ופיקוד כבאים"),
    (23, "שבוע 2", "אישור כריזת חירום", "אולם ספורט", "5588-01", "טופס 6", "טכנאי כריזה", "לפי התקן הנדרש"),
    (24, "שבוע 2", "אישור שחרור עשן ומטפים", "אולם ספורט", "5588-01", "טופס 10 וטופס 2", "מהנדס / מבקר", "חלונות חשמליים ומטפים"),
    (25, "שבוע 1", "הסרת מכסים מעל גלאי העשן", "פנימייה ב' (רש״י)", "333333-1", "-", "צוות תחזוקה", "הסרת מכסים מעל הגלאים"),
    (26, "שבוע 2", "אישורים (גילוי, ספרינקלרים, חשמל, כריזה)", "פנימייה ב' (רש״י)", "333333-1", "טופס 4, 7, 3, 6", "אנשי מקצוע", "הפקת כל הטפסים הנדרשים"),
    (27, "שבוע 2", "אישורים (כריזה, גילוי אש, חשמל)", "בית מדרש + משרדים", "6688-08", "טופס 6, 4, 5, 3", "אנשי מקצוע", "הסרת ליקויים והפקת אישורים"),
    (28, "שבוע 3-4", "העלאה מרוכזת בתיק בקליק", "כל הנכסים", "כל התיקים", "כלל הטפסים", "אחראי מנהלי", "הגשת כל התיקים עם מכתב מלווה"),
]


def import_rows(dry_run=False):
    app = create_app()
    imported = skipped = 0
    with app.app_context():
        try:
            # A single transaction makes the import all-or-nothing.
            with db.session.begin():
                for source_row, phase, title, asset, case_no, forms, owner, notes in ROWS:
                    marker = f"ייבוא טבלת מעקב כבאות והצלה | מקור: {SOURCE} | שורה מקורית: {source_row}"
                    existing = Task.query.filter(Task.description.contains(marker)).first()
                    if existing:
                        LOG.info("SKIP row=%s task_id=%s (already imported)", source_row, existing.id)
                        skipped += 1
                        continue
                    description = "\n".join([
                        f"שלב / שבוע: {phase}",
                        f"נכס רלוונטי: {asset}",
                        f"מספר תיק: {case_no}",
                        f"מספר טופס להגשה: {forms}",
                        f"הערות ודגשים: {notes}",
                        marker,
                    ])
                    task = Task(
                        title=title,
                        description=description,
                        assignee=owner,
                        priority="urgent" if "קריטי!" in notes else "normal",
                        status="open",
                        due_date=None,  # The spreadsheet has no due dates.
                    )
                    db.session.add(task)
                    imported += 1
                    LOG.info("%s row=%s title=%s", "DRY-RUN" if dry_run else "IMPORT", source_row, title)
                if dry_run:
                    db.session.rollback()
        except Exception:
            db.session.rollback()
            LOG.exception("Import failed; transaction rolled back")
            raise
    LOG.info("RESULT source_rows=%s imported=%s skipped_existing=%s errors=0 dry_run=%s",
             len(ROWS), imported, skipped, dry_run)
    return {"source_rows": len(ROWS), "imported": imported, "skipped_existing": skipped, "errors": 0, "dry_run": dry_run}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate and count without persisting rows")
    args = parser.parse_args()
    result = import_rows(dry_run=args.dry_run)
    print(result)
