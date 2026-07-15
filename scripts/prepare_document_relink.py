#!/usr/bin/env python3
"""
Document Relink Plan - כלי Preview בלבד. Read-Only לחלוטין.

**לא מבצע שום שינוי**: אין UPDATE למסד הנתונים, אין שינוי/העתקה/מחיקה של
קבצים, אין ייבוא Supabase. הסקריפט רק *מציע* תוכנית (CSV) לבדיקה אנושית -
שום דבר מהתוכנית לא מיושם אוטומטית. יישום בפועל (אם וכאשר יוחלט לבצע) יהיה
סקריפט נפרד, עם אישור מפורש, בשלב הבא - לא כאן.

מה הסקריפט עושה:
1. מתחבר ל-DB באותו מנגנון בדיוק כמו האפליקציה (create_app, DATABASE_URL).
2. סורק את תיקיית ה-uploads הפיזית ובונה אינדקסים (basename, hash).
3. עבור כל Document, מנסה להתאים אותו לקובץ פיזי לפי 3 אסטרטגיות בסדר
   עדיפות: נתיב מלא -> basename -> hash.
4. מייצא תוכנית ל-document_relink_plan.csv (או נתיב אחר, ר' --output).
5. מזהה קונפליקטים - יותר ממסמך אחד שמצביע לאותו קובץ פיזי מוצע.

שימוש:
    python scripts/prepare_document_relink.py
    python scripts/prepare_document_relink.py --output my_plan.csv
"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import argparse
import csv
import hashlib
import os
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import Document


# ============================================================================
# Self-Audit - אותו עיקרון כמו ב-reconcile_documents.py: בדיקה סטטית שהקובץ
# הזה לא מכיל אף אחת מהפעולות האסורות.
# ============================================================================

_FORBIDDEN_PATTERNS = [
    "db.session.commit", "db.session.add(", "db.session.delete(",
    "storage.upload_bytes", "storage.delete_object", "from app.services import storage",
    "from app.services.storage", "import supabase",
    "os.remove(", "os.unlink(", "shutil.rmtree", "os.rmdir(", "os.chmod(",
    "shutil.copy", "shutil.move", "os.rename(",
    "@app.route", "Blueprint(", "flask.Flask(",
]


def _self_audit() -> bool:
    this_file = os.path.abspath(__file__)
    with open(this_file, "r", encoding="utf-8") as f:
        source = f.read()
    source_check = source.split("_FORBIDDEN_PATTERNS = [", 1)[-1]
    source_check = source_check.split("]", 1)[-1] if "]" in source_check else source_check

    violations = [p for p in _FORBIDDEN_PATTERNS if p in source_check]
    print("=" * 70)
    print("Self-Audit - בדיקת בטיחות קוד המקור")
    print("=" * 70)
    if violations:
        print(f"  [FAIL] נמצאו דפוסים אסורים: {violations}")
    else:
        print("  [PASS] לא נמצאה כתיבה ל-DB, שינוי/העתקת קבצים, Supabase, או Flask routes/UI")
    print("=" * 70 + "\n")
    return not violations


# ============================================================================
# אינדקסים (זהה בעיקרון ל-reconcile_documents.py, מוגדר כאן מחדש כדי לשמור
# על כל סקריפט עצמאי ובלתי-תלוי בסקריפטים אחרים)
# ============================================================================

def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_indexes(upload_folder: str):
    basename_index = defaultdict(list)
    hash_index = {}
    if not os.path.isdir(upload_folder):
        return basename_index, hash_index
    for root, dirs, files in os.walk(upload_folder):
        for fname in files:
            full_path = os.path.abspath(os.path.join(root, fname))
            basename_index[fname].append(full_path)
            try:
                hash_index[_sha256_of_file(full_path)] = full_path
            except Exception:
                pass  # קובץ לא קריא - מדלגים, לא עוצרים
    return basename_index, hash_index


# ============================================================================
# לוגיקת התאמה למסמך בודד
# ============================================================================

def _match_document(doc: Document, upload_folder: str, basename_index: dict, hash_index: dict) -> dict:
    """
    מנסה להתאים Document לקובץ פיזי, בסדר עדיפות: נתיב מלא -> basename -> hash.
    מחזיר dict עם match_type ('FULL_PATH'/'BASENAME'/'HASH'/'UNRESOLVED') והנתיב
    האבסולוטי שנמצא (אם נמצא).
    """
    file_path = (doc.file_path or "").strip()
    file_hash = (doc.file_hash or "").strip()

    # א. נתיב מלא
    if file_path:
        candidate = os.path.join(upload_folder, file_path)
        if os.path.isfile(candidate):
            return {"match_type": "FULL_PATH", "resolved_path": os.path.abspath(candidate)}

    # ב. Basename
    if file_path:
        basename = os.path.basename(file_path)
        matches = basename_index.get(basename, [])
        if matches:
            return {"match_type": "BASENAME", "resolved_path": matches[0]}

    # ג. Hash
    if file_hash and file_hash in hash_index:
        return {"match_type": "HASH", "resolved_path": hash_index[file_hash]}

    return {"match_type": "UNRESOLVED", "resolved_path": None}


_CONFIDENCE = {"FULL_PATH": 100, "HASH": 100, "BASENAME": 90, "UNRESOLVED": 0}


def _action_for(match_type: str) -> str:
    if match_type == "FULL_PATH":
        return "NO_ACTION_NEEDED"   # הנתיב הקיים כבר תקין - אין מה לתקן
    if match_type in ("HASH", "BASENAME"):
        return "UPDATE_FILE_PATH"
    return "INVESTIGATE"            # UNRESOLVED


# ============================================================================
# בניית התוכנית המלאה
# ============================================================================

def build_relink_plan(upload_folder: str):
    docs = Document.query.order_by(Document.id).all()
    basename_index, hash_index = _build_indexes(upload_folder)

    plan_rows = []
    hash_verification_failures = []  # בדיקת תקינות: התאמת HASH שבפועל לא תואמת אחרי חישוב חוזר

    for doc in docs:
        match = _match_document(doc, upload_folder, basename_index, hash_index)
        match_type = match["match_type"]
        resolved_path = match["resolved_path"]  # נתיב אבסולוטי מלא בדיסק, או None

        new_file_path = None    # הערך שבאמת אמור להיכתב ל-Document.file_path (basename בלבד)
        physical_file_path = None  # הנתיב המלא בדיסק, לשקיפות/אבחון בלבד - לא נכתב ל-DB
        new_file_hash = None

        if resolved_path:
            physical_file_path = resolved_path
            # הכרעה מבוססת-קוד (ולא ניחוש): Document.file_path חייב תמיד להיות
            # שם קובץ בלבד, יחסית ל-UPLOAD_FOLDER, בלי קידומת "uploads/" -
            # בדיוק כמו שdms_service.ingest_document שומר אותו לכל מסמך תקין,
            # ובדיוק מה שmigrate_documents_to_supabase.py מצפה לו כשהוא בונה
            # os.path.join(upload_folder, doc.file_path). קידומת "uploads/"
            # הייתה יוצרת נתיב כפול (.../uploads/uploads/...) ומפילה מיגרציות.
            new_file_path = os.path.basename(resolved_path)
            try:
                new_file_hash = _sha256_of_file(resolved_path)
            except Exception:
                new_file_hash = None

            # בדיקת תקינות מפורשת: אם ההתאמה היא לפי HASH, מוודאים שהחישוב
            # החוזר של ה-hash על הקובץ שנמצא אכן זהה ל-file_hash שנשמר ב-DB.
            if match_type == "HASH" and new_file_hash != (doc.file_hash or "").strip():
                hash_verification_failures.append(doc.id)

        row = {
            "document_id": doc.id,
            "old_file_path": doc.file_path or "",
            "file_name": doc.file_name or "",
            "old_file_hash": doc.file_hash or "",
            "match_type": match_type,
            "new_file_path": new_file_path or "",
            "physical_file_path": physical_file_path or "",
            "new_file_hash": new_file_hash or "",
            "confidence": _CONFIDENCE[match_type],
            "action": _action_for(match_type),
        }
        plan_rows.append(row)

    # --- זיהוי קונפליקטים: יותר ממסמך אחד שהיה מקבל את אותו new_file_path.
    # זו הגנה קריטית - אם שני Document שונים "מתחרים" על אותו file_path,
    # אסור לאפשר לתוכנית האוטומטית להחליט איזה מהם נכון; מסמנים את שניהם
    # כ-CONFLICT ומשאירים להכרעה ידנית. ---
    target_counts = Counter(r["new_file_path"] for r in plan_rows if r["new_file_path"])
    conflicts = {path for path, count in target_counts.items() if count > 1}
    for row in plan_rows:
        if row["new_file_path"] and row["new_file_path"] in conflicts:
            row["action"] = "CONFLICT"

    return plan_rows, conflicts, hash_verification_failures


def _write_csv(rows: list, csv_path: str):
    fieldnames = [
        "document_id", "old_file_path", "file_name", "old_file_hash",
        "match_type", "new_file_path", "physical_file_path", "new_file_hash",
        "confidence", "action",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _print_summary(rows: list, conflicts: set, hash_failures: list, csv_path: str):
    ready = sum(1 for r in rows if r["action"] == "UPDATE_FILE_PATH")
    no_action = sum(1 for r in rows if r["action"] == "NO_ACTION_NEEDED")
    investigate = sum(1 for r in rows if r["action"] == "INVESTIGATE")
    conflict_rows = sum(1 for r in rows if r["action"] == "CONFLICT")

    print("Document Relink Plan")
    print("=" * 70)
    print(f"Ready for update:      {ready}")
    print(f"Already correct:       {no_action}  (FULL_PATH - אין צורך בפעולה)")
    print(f"Need investigation:    {investigate}")
    print(f"Conflicts:             {conflict_rows}")
    print("=" * 70)

    if hash_failures:
        print(f"\n[WARNING] {len(hash_failures)} התאמות HASH נכשלו באימות חוזר "
              f"(ה-hash שחושב מחדש לא תואם למה שנשמר ב-DB) - Document IDs: {hash_failures}")
        print("          אלה לא סומנו כ-UPDATE_FILE_PATH באמינות מלאה - יש לבדוק ידנית.\n")

    if conflicts:
        print(f"\n[WARNING] נמצאו {len(conflicts)} קבצים שיותר ממסמך אחד מצביע אליהם:")
        for path in conflicts:
            doc_ids = [r["document_id"] for r in rows if r["new_file_path"] == path]
            print(f"    - {path}  <-  Document IDs: {doc_ids}")

    print(f"\nהתוכנית המלאה נשמרה ל: {csv_path}")
    print("\n[NOTE] new_file_path הוא כעת שם קובץ בלבד (basename), ללא קידומת "
          "'uploads/' - זהו הפורמט הנכון שמתאים ישירות לעמודת Document.file_path, "
          "כפי שאומת מול קוד dms_service.py ו-migrate_documents_to_supabase.py. "
          "הנתיב המלא בדיסק (לשקיפות/אבחון בלבד, לא נכתב ל-DB) מופיע בעמודה "
          "הנפרדת physical_file_path.")


def main(output_path: str):
    audit_passed = _self_audit()

    app = create_app()
    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        print(f"UPLOAD_FOLDER: {upload_folder}\n")

        rows, conflicts, hash_failures = build_relink_plan(upload_folder)
        _write_csv(rows, output_path)
        _print_summary(rows, conflicts, hash_failures, output_path)

        print(f"\nSelf-Audit: {'[PASS]' if audit_passed else '[FAIL]'}")

        return rows, conflicts, hash_failures


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Document Relink Plan - Preview בלבד, Read-Only")
    parser.add_argument('--output', type=str, default='document_relink_plan.csv',
                         metavar='PATH', help='נתיב לקובץ ה-CSV הפלט (ברירת מחדל: document_relink_plan.csv)')
    args = parser.parse_args()

    main(output_path=args.output)
