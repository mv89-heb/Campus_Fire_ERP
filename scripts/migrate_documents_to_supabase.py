#!/usr/bin/env python3
"""
סקריפט חד-פעמי: מיגרציית מסמכים קיימים מהדיסק המקומי (uploads/) ל-Supabase
Storage.

**זה סקריפט תחזוקה, לא חלק מהאפליקציה.** מריצים אותו ידנית פעם אחת (או
כמה פעמים - הוא Idempotent: מסמכים שכבר הועברו מדולגים אוטומטית).

שימוש:
    python scripts/migrate_documents_to_supabase.py              # מריץ בפועל
    python scripts/migrate_documents_to_supabase.py --dry-run    # סימולציה בלבד, לא נוגע ב-Neon/Supabase
    python scripts/migrate_documents_to_supabase.py --yes        # מדלג על אישור אינטראקטיבי

דרישות סביבה: אותם משתני סביבה כמו לאפליקציה עצמה - DATABASE_URL,
SUPABASE_URL, SUPABASE_SERVICE_KEY (וכן STORAGE_DIR אם לא ברירת המחדל).

**לא מוחק קבצים מקומיים.** זה מכוון - המשתמש יחליט בנפרד מתי למחוק אותם,
אחרי שיאשר שהמעבר הצליח במלואו.
"""
import argparse
import os
import sys

# מאפשר להריץ את הסקריפט מכל מיקום ועדיין למצוא את חבילת app/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models import Document
from app.services import storage


def _human_report(scanned, migrated, already_done, missing_local, failed, failed_list):
    print("\n" + "=" * 60)
    print("דו\"ח מיגרציה - מסמכים ל-Supabase Storage")
    print("=" * 60)
    print(f"  נסרקו:              {scanned}")
    print(f"  הועברו בהצלחה:      {migrated}")
    print(f"  כבר היו ב-Supabase: {already_done}")
    print(f"  קובץ מקומי חסר:     {missing_local}")
    print(f"  נכשלו:              {failed}")
    if failed_list:
        print("\n  רשימת כשלונות:")
        for item in failed_list:
            print(f"    - Document #{item['id']} ({item['file_name']}): {item['reason']}")
    print("=" * 60 + "\n")


def _verify_all_open(app):
    """
    שלב 8 מהדרישות: אחרי המיגרציה, מוודא שכל המסמכים שסומנו כ-Supabase
    (file_path מתחיל ב-'documents/') אכן ניתנים לפתיחה (signed URL תקין).
    לא בודק מסמכים שנשארו מקומיים בכוונה (למשל כי חסר להם קובץ).
    """
    print("מריץ אימות סופי: בודק שכל המסמכים ב-Supabase נפתחים...")
    with app.app_context():
        docs = Document.query.filter(Document.file_path.like(f"{app.config['SUPABASE_BUCKET']}/%")).all()
        ok, broken = 0, []
        for doc in docs:
            url = storage.get_signed_url(doc.file_path)
            if url:
                ok += 1
            else:
                broken.append({"id": doc.id, "file_name": doc.file_name, "file_path": doc.file_path})
        print(f"  נבדקו {len(docs)} מסמכים ב-Supabase: {ok} נפתחים תקין, {len(broken)} נכשלו.")
        if broken:
            print("  מסמכים שנכשלו באימות (ייתכן שדורשים בדיקה ידנית):")
            for b in broken:
                print(f"    - Document #{b['id']} ({b['file_name']}) -> {b['file_path']}")
        return ok, broken


def migrate(dry_run: bool):
    app = create_app()
    with app.app_context():
        if not storage.is_configured():
            print("שגיאה: Supabase אינו מוגדר (SUPABASE_URL / SUPABASE_SERVICE_KEY חסרים). עוצר.")
            sys.exit(1)

        if not dry_run:
            connected, err = storage.check_connection()
            if not connected:
                print(f"שגיאה: לא ניתן להתחבר ל-Supabase Storage: {err}. עוצר.")
                sys.exit(1)

        upload_folder = app.config['UPLOAD_FOLDER']
        bucket = app.config['SUPABASE_BUCKET']
        print(f"תיקיית מקור מקומית: {upload_folder}")
        print(f"Supabase bucket: {bucket}")
        print(f"מצב: {'סימולציה (dry-run) - לא ישונה כלום' if dry_run else 'הרצה בפועל'}\n")

        docs = Document.query.order_by(Document.id).all()
        scanned = len(docs)
        migrated = already_done = missing_local = failed = 0
        failed_list = []

        for doc in docs:
            if storage.is_supabase_path(doc.file_path):
                already_done += 1
                continue

            if not doc.file_path:
                # רשומת טיוטה בלי קובץ מצורף (למשל שכפול-לחידוש ריק) - לדלג בשקט
                continue

            local_path = os.path.join(upload_folder, doc.file_path)
            if not os.path.exists(local_path):
                print(f"  ⚠️  אזהרה: קובץ מקומי חסר עבור Document #{doc.id} ({doc.file_name}) בנתיב {local_path} - מדלג")
                missing_local += 1
                continue

            if dry_run:
                print(f"  [dry-run] היה מעביר Document #{doc.id} ({doc.file_name}) -> {bucket}/{doc.file_path}")
                migrated += 1
                continue

            try:
                with open(local_path, 'rb') as f:
                    data = f.read()
            except Exception as e:
                print(f"  ❌ שגיאה בקריאת הקובץ המקומי עבור Document #{doc.id}: {e}")
                failed += 1
                failed_list.append({"id": doc.id, "file_name": doc.file_name, "reason": f"קריאת קובץ מקומי נכשלה: {e}"})
                continue

            # שם הקובץ המרוחק נשאר בדיוק כפי שהוא כיום ב-file_path (כפי שנדרש)
            remote_filename = doc.file_path
            try:
                new_path = storage.upload_bytes(remote_filename, data)
            except storage.StorageError as e:
                print(f"  ❌ העלאה ל-Supabase נכשלה עבור Document #{doc.id}: {e}")
                failed += 1
                failed_list.append({"id": doc.id, "file_name": doc.file_name, "reason": f"העלאה ל-Supabase נכשלה: {e}"})
                continue

            old_path = doc.file_path
            doc.file_path = new_path
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                doc.file_path = old_path  # שחזור הערך בזיכרון (למקרה שהאובייקט נשאר בשימוש)
                storage.delete_object(new_path)  # לא משאירים קובץ יתום ב-Supabase
                print(f"  ❌ עדכון Neon נכשל עבור Document #{doc.id} - בוצע cleanup ב-Supabase: {e}")
                failed += 1
                failed_list.append({"id": doc.id, "file_name": doc.file_name, "reason": f"עדכון Neon נכשל (בוצע cleanup): {e}"})
                continue

            print(f"  ✅ Document #{doc.id} ({doc.file_name}) הועבר: {old_path} -> {new_path}")
            migrated += 1

        _human_report(scanned, migrated, already_done, missing_local, failed, failed_list)

        print("שים לב: הקבצים המקומיים ב-uploads/ לא נמחקו. מחיקה היא צעד נפרד ומכוון.\n")

        if not dry_run and migrated > 0:
            _verify_all_open(app)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="מיגרציית מסמכים ל-Supabase Storage")
    parser.add_argument('--dry-run', action='store_true', help='סימולציה בלבד - לא מעלה ל-Supabase ולא כותב ל-Neon')
    parser.add_argument('--yes', action='store_true', help='דלג על אישור אינטראקטיבי')
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        answer = input(
            "פעולה זו תעלה מסמכים ל-Supabase Storage ותעדכן רשומות ב-Neon (production). "
            "הקבצים המקומיים לא יימחקו. להמשיך? [y/N]: "
        )
        if answer.strip().lower() not in ('y', 'yes', 'כן'):
            print("בוטל.")
            sys.exit(0)

    migrate(dry_run=args.dry_run)
