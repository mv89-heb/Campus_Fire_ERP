#!/usr/bin/env python3
"""
Migration - Commit 2 (Document Storage Management): מוסיף 3 עמודות חדשות
לטבלת documents: file_size, deleted_at, deleted_by.

**זה סקריפט תחזוקה חד-פעמי, לא חלק מהאפליקציה.** לא משתמש ב-db.create_all()
- זה לא עוזר להוספת עמודות לטבלה קיימת (רק יוצר טבלאות חדשות שחסרות
  לגמרי), ולכן שימוש בו כאן היה מטעה.

בטיחות:
- ברירת מחדל: DRY-RUN בלבד. שום ALTER TABLE לא מתבצע ללא --apply במפורש.
- Idempotent: לפני כל ניסיון הוספה, בודק באמצעות SQLAlchemy Inspector
  אילו עמודות כבר קיימות בפועל בטבלה (לא במודל!). עמודה קיימת -> מדווח
  ועובר הלאה, לא מנסה להוסיף שוב. הרצה חוזרת אחרי --apply מוצלח מדווחת
  "הכל כבר קיים" ולא משנה כלום.
- תומך גם ב-SQLite וגם ב-Postgres (Neon) - בוחר טיפוסי עמודה מתאימים
  לכל דיאלקט בנפרד (ר' _COLUMN_TYPES_BY_DIALECT למטה).
- deleted_by נוסף כעמודת INTEGER נלווית בלבד, בלי אילוץ FOREIGN KEY
  ברמת ה-DB: הוספת אילוץ FK רטרואקטיבי דרך ALTER TABLE אינה אמינה
  באופן עקבי בין SQLite ל-Postgres (ב-SQLite ישן זה כלל לא נתמך בלי
  בניית טבלה מחדש). המודל ב-SQLAlchemy (models.py) כן מצהיר על
  ForeignKey('users.id') ברמת ה-ORM, לצורך תיעוד/relationship - זה
  מספיק לצרכי האפליקציה, גם בלי אכיפה קשיחה ב-DB עצמו.

שימוש:
    python scripts/migrate_add_document_columns.py              # DRY-RUN (ברירת מחדל)
    python scripts/migrate_add_document_columns.py --apply       # ביצוע אמיתי
"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import argparse
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db

TABLE_NAME = 'documents'

# טיפוסי עמודה פר-דיאלקט. "DATETIME" תקין ב-SQLite אך אינו טיפוס חוקי
# ב-Postgres (שם צריך TIMESTAMP) - זו בדיוק הסיבה שלא ניתן להשתמש באותה
# מחרוזת SQL גולמית סתם ככה על שני הדיאלקטים.
_COLUMN_TYPES_BY_DIALECT = {
    'sqlite': {
        'file_size': 'INTEGER',
        'deleted_at': 'DATETIME',
        'deleted_by': 'INTEGER',
    },
    'postgresql': {
        'file_size': 'INTEGER',
        'deleted_at': 'TIMESTAMP',
        'deleted_by': 'INTEGER',
    },
}

TARGET_COLUMNS = ['file_size', 'deleted_at', 'deleted_by']


def _get_dialect_name() -> str:
    return db.engine.dialect.name  # 'sqlite' או 'postgresql'


def _existing_columns() -> set:
    """קריאה בלבד: אילו עמודות קיימות היום בפועל בטבלת documents."""
    inspector = inspect(db.engine)
    return {col['name'] for col in inspector.get_columns(TABLE_NAME)}


def run_migration(apply: bool):
    app = create_app()
    with app.app_context():
        dialect = _get_dialect_name()
        if dialect not in _COLUMN_TYPES_BY_DIALECT:
            print(f"[ERROR] דיאלקט לא נתמך: {dialect}. הסקריפט תומך רק ב-sqlite/postgresql. עוצר.")
            sys.exit(1)

        column_types = _COLUMN_TYPES_BY_DIALECT[dialect]
        print(f"DB dialect: {dialect}")
        print(f"טבלת יעד:   {TABLE_NAME}")
        print(f"מצב:        {'--apply (ביצוע אמיתי)' if apply else 'DRY-RUN (ברירת מחדל - לא נוגע ב-DB)'}\n")

        existing = _existing_columns()
        print(f"עמודות קיימות היום בטבלה בפועל ({len(existing)}): {sorted(existing)}\n")

        to_add = []
        already_present = []
        for col in TARGET_COLUMNS:
            if col in existing:
                already_present.append(col)
            else:
                to_add.append(col)

        if already_present:
            print(f"[INFO] כבר קיימות (מדולג, idempotent): {already_present}")
        if not to_add:
            print("\n[DONE] כל 3 העמודות כבר קיימות. אין מה להוסיף. הסקריפט לא ביצע שום שינוי.")
            return

        print(f"\nעמודות שיתווספו: {to_add}\n")

        for col in to_add:
            col_type = column_types[col]
            ddl = f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} {col_type}"
            if not apply:
                print(f"  [DRY-RUN] היה מריץ: {ddl}")
            else:
                try:
                    db.session.execute(text(ddl))
                    db.session.commit()
                    print(f"  [OK] בוצע: {ddl}")
                except Exception as e:
                    db.session.rollback()
                    print(f"  [ERROR] נכשל: {ddl}\n          סיבה: {e}")
                    print("          עוצר - לא ממשיך לעמודות הבאות אחרי כשל.")
                    sys.exit(1)

        if not apply:
            print(f"\nסה\"כ {len(to_add)} עמודות היו מתווספות.")
            print("להרצה אמיתית: python scripts/migrate_add_document_columns.py --apply")
        else:
            print(f"\n[DONE] {len(to_add)} עמודות נוספו בהצלחה.")
            # אימות סופי: קוראים שוב את מבנה הטבלה בפועל (לא סומכים על ההנחה שהצליח)
            final_columns = _existing_columns()
            still_missing = [c for c in TARGET_COLUMNS if c not in final_columns]
            if still_missing:
                print(f"[WARNING] אחרי הביצוע, עדיין חסרות: {still_missing} - יש לבדוק ידנית!")
            else:
                print("[VERIFIED] כל 3 העמודות אכן קיימות עכשיו בטבלה (נבדק מחדש דרך Inspector).")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Migration: הוספת עמודות file_size/deleted_at/deleted_by לטבלת documents")
    parser.add_argument('--apply', action='store_true', help='ביצוע אמיתי. בלעדיו - תמיד DRY-RUN, לא נוגע ב-DB.')
    args = parser.parse_args()

    run_migration(apply=args.apply)
