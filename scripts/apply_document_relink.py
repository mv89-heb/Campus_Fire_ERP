#!/usr/bin/env python3
"""
Apply Document Relink - מבצע בפועל עדכון Document.file_path לפי תוכנית
שנוצרה ע"י prepare_document_relink.py ואושרה ע"י אדם.

בטיחות (בהתאם לדרישות מפורשות):
1. ברירת מחדל = DRY-RUN. שום UPDATE לא מתבצע ללא --apply במפורש.
2. מעדכן אך ורק רשומות עם match_type=HASH ו-confidence=100 (בדיוק כפי
   שמופיע בתוכנית שאושרה). UNRESOLVED ו-CONFLICT לעולם לא מעודכנים.
3. לפני כל UPDATE אמיתי: נוצר קובץ גיבוי CSV עם המצב לפני השינוי, כדי
   שאפשר יהיה לדעת בדיוק מה היה ולשחזר ידנית אם צריך.
4. כל העדכונים רצים כ-Transaction יחיד: כשל באחד -> ROLLBACK מלא, אף
   שינוי לא נשמר בכלל.
5. אימות "drift" לפני כל UPDATE בפועל: מוודא מחדש (ברגע ההרצה, לא רק לפי
   מה שהיה כתוב ב-CSV בזמן ה-Preview) שה-hash הנוכחי ברשומה עדיין תואם,
   ושהקובץ המוצע עדיין קיים ותוכנו עדיין זהה. אם לא - הרשומה מדולגת
   (SKIPPED), לא מעודכנת על בסיס מידע מיושן.
6. לא נוגע בשום קובץ פיזי בשום שלב - רק בעמודת Document.file_path.

שימוש:
    python scripts/apply_document_relink.py                       # DRY-RUN (ברירת מחדל, לא נוגע ב-DB)
    python scripts/apply_document_relink.py --apply                # ביצוע אמיתי (עם אישור אינטראקטיבי)
    python scripts/apply_document_relink.py --apply --yes          # ביצוע אמיתי, ללא אישור אינטראקטיבי
    python scripts/apply_document_relink.py --plan other_plan.csv  # קובץ תוכנית אחר (ברירת מחדל: document_relink_plan.csv)
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
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models import Document


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================================================
# שלב 1: טעינת התוכנית שאושרה, וסינון לרשומות שמותר לעדכן אותן בלבד
# ============================================================================

def _load_eligible_rows(plan_csv_path: str) -> list:
    """
    קורא את document_relink_plan.csv ומחזיר רק את השורות שמותר לעדכן:
    match_type=HASH, confidence=100, action=UPDATE_FILE_PATH בלבד.
    UNRESOLVED ו-CONFLICT (ובאופן מכוון גם BASENAME, שהוא confidence=90)
    לעולם לא נכללים כאן.
    """
    if not os.path.isfile(plan_csv_path):
        raise FileNotFoundError(
            f"קובץ התוכנית לא נמצא: {plan_csv_path}. "
            f"יש להריץ קודם python scripts/prepare_document_relink.py"
        )
    eligible = []
    with open(plan_csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("match_type") == "HASH" and row.get("confidence") == "100" \
                    and row.get("action") == "UPDATE_FILE_PATH":
                eligible.append(row)
    return eligible


# ============================================================================
# שלב 2: אימות drift - בדיקה חוזרת ברגע ההרצה שהמידע עדיין נכון, לפני שנוגעים ב-DB
# ============================================================================

def _verify_row_still_valid(row: dict, upload_folder: str) -> tuple:
    """
    מוודא שהמידע בשורת התוכנית עדיין תקף *עכשיו* (לא רק כשה-CSV נוצר).
    מחזיר (True, doc) אם תקין, או (False, סיבה) אם לא.
    """
    doc = db.session.get(Document, int(row["document_id"]))
    if doc is None:
        return False, "הרשומה כבר לא קיימת ב-DB"

    if (doc.file_hash or "").strip() != row["old_file_hash"].strip():
        return False, f"file_hash ברשומה השתנה מאז ה-Preview (drift)"

    target_path = os.path.join(upload_folder, row["new_file_path"])
    if not os.path.isfile(target_path):
        return False, f"הקובץ המוצע כבר לא קיים: {target_path}"

    try:
        current_hash = _sha256_of_file(target_path)
    except Exception as e:
        return False, f"שגיאה בקריאת הקובץ המוצע: {e}"

    if current_hash != row["new_file_hash"].strip():
        return False, "תוכן הקובץ המוצע השתנה מאז ה-Preview (drift)"

    return True, doc


# ============================================================================
# שלב 3: גיבוי לפני עדכון
# ============================================================================

def _write_backup(rows: list, backup_path: str):
    fieldnames = ["document_id", "old_file_path", "new_file_path", "old_hash", "new_hash"]
    with open(backup_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "document_id": row["document_id"],
                "old_file_path": row["old_file_path"],
                "new_file_path": row["new_file_path"],
                "old_hash": row["old_file_hash"],
                "new_hash": row["new_file_hash"],
            })


# ============================================================================
# שלב 4: מדידת "Matched" (כמה מסמכים כרגע פותרים לקובץ קיים בפועל) - משמש
# להשוואת לפני/אחרי, כמו reconcile_documents.py.
# ============================================================================

def _count_matched(upload_folder: str) -> int:
    docs = Document.query.all()
    count = 0
    for doc in docs:
        if doc.file_path and os.path.isfile(os.path.join(upload_folder, doc.file_path)):
            count += 1
    return count


# ============================================================================
# הרצה ראשית
# ============================================================================

def main(plan_path: str, apply: bool, skip_confirm: bool):
    app = create_app()
    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        print(f"UPLOAD_FOLDER: {upload_folder}")
        print(f"קובץ תוכנית:    {plan_path}")
        print(f"מצב:            {'--apply (ביצוע אמיתי)' if apply else 'DRY-RUN (ברירת מחדל - לא נוגע ב-DB)'}\n")

        eligible_rows = _load_eligible_rows(plan_path)
        print(f"נמצאו {len(eligible_rows)} רשומות זכאיות לעדכון (match_type=HASH, confidence=100) בתוכנית.\n")

        matched_before = _count_matched(upload_folder)

        if not eligible_rows:
            print("אין רשומות לעדכון. מסיים.")
            return

        # --- DRY-RUN: מציג מה היה משתנה, לא נוגע ב-DB בכלל ---
        if not apply:
            print("=" * 70)
            print("DRY-RUN - להלן מה היה משתנה (לא בוצע שום שינוי בפועל):")
            print("=" * 70)
            for row in eligible_rows:
                print(f"  Document #{row['document_id']}: "
                      f"'{row['old_file_path']}' -> '{row['new_file_path']}'")
            print("=" * 70)
            print(f"\nסה\"כ {len(eligible_rows)} מסמכים היו מתעדכנים.")
            print("להרצה אמיתית: python scripts/apply_document_relink.py --apply\n")
            return

        # --- ממשיכים ל-APPLY בפועל: קודם מאמתים drift על כל שורה ---
        verified_rows = []
        skipped = []
        for row in eligible_rows:
            ok, result = _verify_row_still_valid(row, upload_folder)
            if ok:
                verified_rows.append((row, result))  # result = doc object
            else:
                skipped.append((row, result))  # result = סיבת הדילוג

        if skipped:
            print(f"[INFO] {len(skipped)} רשומות דולגו כבר בשלב האימות (drift מאז ה-Preview):")
            for row, reason in skipped:
                print(f"    - Document #{row['document_id']}: {reason}")
            print()

        if not verified_rows:
            print("אחרי אימות drift - אין אף רשומה תקפה לעדכון. מסיים בלי לגעת ב-DB.")
            return

        # --- אישור אינטראקטיבי מפורש ---
        print("About to update:")
        print(f"{len(verified_rows)} documents")
        if not skip_confirm:
            answer = input("Continue? [yes/no]: ").strip().lower()
            if answer not in ("yes", "y", "כן"):
                print("בוטל על ידי המשתמש. לא בוצע שום שינוי.")
                return
        else:
            print("(--yes סופק, מדלג על אישור אינטראקטיבי)")

        # --- גיבוי לפני כל שינוי ---
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"document_relink_backup_{timestamp}.csv"
        _write_backup([row for row, _ in verified_rows], backup_path)
        print(f"\nגיבוי נשמר ל: {backup_path}")

        # --- UPDATE בתוך Transaction יחיד ---
        updated_ids = []
        failed = []
        try:
            for row, doc in verified_rows:
                doc.file_path = row["new_file_path"]
                updated_ids.append(row["document_id"])
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"\n[ERROR] העדכון נכשל, בוצע ROLLBACK מלא - אף שינוי לא נשמר: {e}")
            failed = updated_ids
            updated_ids = []

        matched_after = _count_matched(upload_folder)

        print("\n" + "=" * 70)
        print("תוצאות")
        print("=" * 70)
        print(f"Updated: {len(updated_ids)}")
        print(f"Failed:  {len(failed)}")
        print(f"Skipped: {len(skipped)}")
        print("=" * 70)

        print(f"\nבדיקת אימות (Matched, לפי reconcile logic):")
        print(f"  לפני העדכון: {matched_before}")
        print(f"  אחרי העדכון: {matched_after}")
        print(f"  שינוי:       {matched_after - matched_before:+d}")
        if updated_ids and matched_after < matched_before + len(updated_ids):
            print("  [WARNING] העלייה ב-Matched נמוכה ממספר הרשומות שעודכנו - כדאי לבדוק ידנית.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Apply Document Relink - ביצוע התוכנית, DRY-RUN כברירת מחדל")
    parser.add_argument('--plan', type=str, default='document_relink_plan.csv',
                         metavar='PATH', help='נתיב לקובץ התוכנית (ברירת מחדל: document_relink_plan.csv)')
    parser.add_argument('--apply', action='store_true',
                         help='ביצוע אמיתי. בלעדיו - תמיד DRY-RUN בלבד, לא נוגע ב-DB.')
    parser.add_argument('--yes', action='store_true',
                         help='דלג על אישור אינטראקטיבי לפני commit (לשימוש אוטומטי/CI)')
    args = parser.parse_args()

    main(plan_path=args.plan, apply=args.apply, skip_confirm=args.yes)
