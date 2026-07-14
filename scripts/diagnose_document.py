#!/usr/bin/env python3
"""
Diagnose Single Document - כלי אבחון Read-Only למסמך בודד לפי ID.

**לא מבצע שום שינוי**: לא UPDATE, לא כתיבה/מחיקה של קבצים, לא שינוי ל-DB.

למה זה קיים בנפרד מ-reconcile_documents.py: reconcile_documents.py בודק
*רק* את הדיסק המקומי - הוא לעולם לא בודק אם קובץ קיים ב-Supabase Storage.
כתוצאה מכך, מסמך עם file_path בפורמט 'documents/uuid.pdf' (שכבר הועבר
בהצלחה ל-Supabase) יופיע תמיד כ"חסר" ב-reconcile, גם אם הוא לגמרי תקין -
כי הבדיקה שם מסתכלת רק בתיקיית uploads/ המקומית. הכלי הזה סוגר את הפער:
בודק גם מול Supabase (אם מוגדר בסביבה), ורק אם גם שם לא נמצא - ממשיך
לחיפוש חלופי מקומי (basename/hash), כמו ב-relink.

שימוש:
    python scripts/diagnose_document.py --id 16
"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import argparse
import hashlib
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models import Document
from app.services import storage


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _search_local_by_basename(upload_folder: str, basename: str):
    matches = []
    if not os.path.isdir(upload_folder):
        return matches
    for root, dirs, files in os.walk(upload_folder):
        for fname in files:
            if fname == basename:
                matches.append(os.path.abspath(os.path.join(root, fname)))
    return matches


def _search_local_by_hash(upload_folder: str, target_hash: str):
    if not os.path.isdir(upload_folder) or not target_hash:
        return None
    for root, dirs, files in os.walk(upload_folder):
        for fname in files:
            full_path = os.path.join(root, fname)
            try:
                if _sha256_of_file(full_path) == target_hash:
                    return os.path.abspath(full_path)
            except Exception:
                pass
    return None


def diagnose(doc_id: int):
    app = create_app()
    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        doc = db.session.get(Document, doc_id)

        if doc is None:
            print(f"[ERROR] Document #{doc_id} לא נמצא ב-DB בכלל.")
            return

        print("=" * 70)
        print(f"אבחון Document #{doc.id}")
        print("=" * 70)
        print(f"  file_name:  {doc.file_name}")
        print(f"  file_path:  {doc.file_path}")
        print(f"  file_hash:  {doc.file_hash}")
        print(f"  status:     {doc.status}")
        print("=" * 70)

        is_supabase_format = storage.is_supabase_path(doc.file_path or "")
        print(f"\n1. פורמט file_path: {'Supabase (documents/...)' if is_supabase_format else 'מקומי (שם קובץ בלבד)'}")

        # --- בדיקה מול Supabase, אם רלוונטי ומוגדר ---
        supabase_result = "לא נבדק"
        if is_supabase_format:
            if not storage.is_configured():
                supabase_result = "לא ניתן לבדוק - Supabase אינו מוגדר בסביבה הנוכחית (SUPABASE_URL/SUPABASE_SERVICE_KEY חסרים כאן)"
            else:
                connected, err = storage.check_connection()
                if not connected:
                    supabase_result = f"לא ניתן להתחבר ל-Supabase: {err}"
                else:
                    signed_url = storage.get_signed_url(doc.file_path)
                    if signed_url:
                        supabase_result = f"[FOUND] הקובץ קיים ב-Supabase! signed URL נוצר בהצלחה: {signed_url[:80]}..."
                    else:
                        supabase_result = "[MISSING] הקובץ לא נמצא ב-Supabase (או שיצירת signed URL נכשלה)"
        print(f"\n2. בדיקה מול Supabase: {supabase_result}")

        # --- חיפוש מקומי לפי basename ---
        basename = os.path.basename(doc.file_path or "")
        local_basename_matches = _search_local_by_basename(upload_folder, basename) if basename else []
        print(f"\n3. חיפוש מקומי לפי שם קובץ ('{basename}'): "
              f"{'נמצא ב-' + str(local_basename_matches) if local_basename_matches else 'לא נמצא'}")

        # --- חיפוש מקומי לפי hash ---
        local_hash_match = _search_local_by_hash(upload_folder, doc.file_hash) if doc.file_hash else None
        print(f"\n4. חיפוש מקומי לפי תוכן (hash): "
              f"{'נמצא ב-' + local_hash_match if local_hash_match else 'לא נמצא'}")

        # --- המלצה סופית ---
        print("\n" + "=" * 70)
        print("המלצה")
        print("=" * 70)
        if "[FOUND]" in supabase_result:
            print("  הקובץ קיים ותקין ב-Supabase. אין בעיה בפועל - reconcile_documents.py")
            print("  מדווח עליו כ'חסר' רק כי הוא בודק דיסק מקומי בלבד ולא Supabase.")
            print("  לא נדרשת פעולה.")
        elif local_hash_match:
            print(f"  נמצא קובץ מקומי עם תוכן זהה ב-hash: {local_hash_match}")
            print("  ניתן לשקול relink ידני (כמו prepare_document_relink.py) לנתיב הזה.")
        elif local_basename_matches:
            print(f"  נמצא קובץ מקומי עם שם זהה (אך תוכן לא אומת): {local_basename_matches}")
            print("  יש לבדוק ידנית שזה אכן אותו מסמך לפני כל פעולה.")
        else:
            print("  לא נמצא הקובץ לא ב-Supabase ולא מקומית, לא לפי שם ולא לפי תוכן.")
            print("  ייתכן שהקובץ אבד לצמיתות. פעולה מומלצת: לתעד זאת ידנית ברשומה")
            print("  (למשל סטטוס 'קובץ לא זמין') ולבדוק אם קיים גיבוי חיצוני נוסף")
            print("  (Render snapshot ישן, גיבוי ידני, וכו'). לא לבצע שינוי אוטומטי.")
        print("=" * 70)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="אבחון Read-Only למסמך בודד")
    parser.add_argument('--id', type=int, required=True, help='Document ID לאבחון')
    args = parser.parse_args()
    diagnose(args.id)
