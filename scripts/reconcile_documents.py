#!/usr/bin/env python3
"""
דו"ח התאמה (Reconciliation Report) - סקריפט Read-Only לחלוטין.

**לא מבצע שום שינוי**: לא כותב ל-DB (אין אפילו קריאה אחת ל-db.session.commit
בכל הקובץ), לא מעלה/מוחק קבצים ב-Supabase (לא מייבא את app.services.storage
בכלל), ולא נוגע בדיסק המקומי מלבד קריאה. בטוח להרצה מספר בלתי מוגבל של
פעמים, בכל סביבה (מקומית / Render Shell), כולל בסביבת Production, לצורך
אבחון בלבד.

שימוש:
    python scripts/reconcile_documents.py                    # סיכום בלבד
    python scripts/reconcile_documents.py --verbose          # פירוט מלא לכל מסמך
    python scripts/reconcile_documents.py --csv report.csv   # ייצוא ל-CSV (בנוסף לפלט הרגיל)

ראו scripts/README_reconcile.md למדריך שימוש מלא, כולל הסבר איך להריץ
ב-Render, איך לקרוא כל שדה בדוח, ותרחישים אפשריים ומשמעותם.

הערת תאימות Windows: הפלט מוגבל במכוון לתווי ASCII בלבד (למשל [PASS] במקום
סימן וי ירוק) כי PowerShell 5.1 עם קידוד ברירת המחדל (cp1252/cp1255) לא יודע
להדפיס אמוג'י ונכשל עם UnicodeEncodeError. בנוסף, מנסים (best-effort, לא
חובה) להגדיר את ה-stdout ל-UTF-8 כדי שטקסט בעברית (שאינו אמוג'י) עדיין יעבוד
תקין בטרמינלים שתומכים בכך.
"""
import sys

try:
    # רשת ביטחון: מנסה להבטיח פלט UTF-8 גם ב-PowerShell ישן. לא קריטי אם
    # נכשל (למשל בגרסאות Python ישנות בלי reconfigure) - הפתרון המרכזי הוא
    # שהפלט לא מכיל תווים מחוץ ל-ASCII שדורשים UTF-8 בכלל.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import argparse
import csv
import hashlib
import os
import platform
import socket
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.config import BASE_DIR
from app.models import Document


# ============================================================================
# שלב 0: אימות עצמי (Self-Audit) - בדיקה סטטית שהקובץ הזה לא מכיל אף אחת
# מהפעולות ה"מסוכנות" שאסורות לו. רץ בתחילת כל הרצה ומדפיס PASS/FAIL, כדי
# שהבטיחות לא תהיה רק הצהרה אלא בדיקה בפועל על קוד המקור של הסקריפט עצמו.
# ============================================================================

_FORBIDDEN_PATTERNS = [
    "db.session.commit", "db.session.add(", "db.session.delete(",
    "storage.upload_bytes", "storage.delete_object", "from app.services import storage",
    "from app.services.storage", "import supabase",
    "os.remove(", "os.unlink(", "shutil.rmtree", "os.rmdir(", "os.chmod(",
]


def _self_audit() -> bool:
    """קורא את קובץ המקור של הסקריפט עצמו ומוודא שאין בו אף אחד מהדפוסים האסורים."""
    this_file = os.path.abspath(__file__)
    with open(this_file, "r", encoding="utf-8") as f:
        source = f.read()

    # לא סופרים את ההגדרה של _FORBIDDEN_PATTERNS עצמה כ"שימוש" בדפוס האסור
    source_without_list_def = source.split("_FORBIDDEN_PATTERNS = [", 1)[-1]
    source_without_list_def = source_without_list_def.split("]", 1)[-1] if "]" in source_without_list_def else source_without_list_def

    violations = [p for p in _FORBIDDEN_PATTERNS if p in source_without_list_def]

    print("=" * 70)
    print("אימות עצמי (Self-Audit) - בדיקת בטיחות קוד המקור")
    print("=" * 70)
    if violations:
        print(f"  [FAIL] - נמצאו דפוסים אסורים בקוד: {violations}")
    else:
        print("  [PASS] - לא נמצאה אף פעולת כתיבה/מחיקה/העלאה בקובץ")
        print("     (נבדק: ללא commit ל-DB, ללא ייבוא Supabase, ללא מחיקת/שינוי קבצים)")
    print("=" * 70 + "\n")
    return not violations


# ============================================================================
# שלב 1: מידע סביבה מלא
# ============================================================================

def _print_environment_info(upload_folder: str) -> dict:
    storage_dir_env = os.environ.get('STORAGE_DIR')
    abs_upload_folder = os.path.abspath(upload_folder)
    folder_exists = os.path.isdir(abs_upload_folder)
    folder_readable = os.access(abs_upload_folder, os.R_OK) if folder_exists else False

    env_info = {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "cwd": os.getcwd(),
        "base_dir": BASE_DIR,
        "upload_folder_config": upload_folder,
        "storage_dir_env": storage_dir_env,
        "storage_dir_explicitly_set": bool(storage_dir_env),
        "upload_folder_absolute": abs_upload_folder,
        "upload_folder_exists": folder_exists,
        "upload_folder_readable": folder_readable,
    }

    print("=" * 70)
    print("Reconciliation Report - דו\"ח התאמה (Read-Only)")
    print("=" * 70)
    print(f"  זמן ריצה:                 {datetime.now().isoformat(timespec='seconds')}")
    print(f"  Hostname:                 {env_info['hostname']}")
    print(f"  מערכת הפעלה:              {env_info['os']}")
    print(f"  Python version:           {env_info['python_version']}")
    print(f"  Current Working Dir:      {env_info['cwd']}")
    print(f"  Base Directory (פרויקט):  {env_info['base_dir']}")
    print(f"  UPLOAD_FOLDER (config):   {env_info['upload_folder_config']}")
    print(f"  STORAGE_DIR (env var):    {storage_dir_env or '<לא מוגדר>'}")
    print(f"  STORAGE_DIR הוגדר במפורש: {'כן' if env_info['storage_dir_explicitly_set'] else 'לא (נופל לברירת מחדל BASE_DIR/uploads)'}")
    print(f"  נתיב אבסולוטי:            {env_info['upload_folder_absolute']}")
    print(f"  התיקייה קיימת:            {'כן' if folder_exists else 'לא'}")
    print(f"  הרשאות קריאה:             {'כן' if folder_readable else 'לא'}")
    print(f"  DATABASE_URL מוגדר:       {'כן (' + os.environ.get('DATABASE_URL', '')[:30] + '...)' if os.environ.get('DATABASE_URL') else 'לא (SQLite מקומי)'}")
    print("=" * 70)

    return env_info


# ============================================================================
# שלב 2: סטטיסטיקת תיקיית uploads (סריקה, ללא כתיבה)
# ============================================================================

def _scan_upload_folder(upload_folder: str) -> dict:
    stats = {
        "total_files": 0, "total_dirs": 0, "pdf_count": 0, "other_count": 0,
        "total_size_bytes": 0, "avg_size_bytes": 0.0,
        "first_10": [], "last_10": [],
    }
    if not os.path.isdir(upload_folder):
        return stats

    all_filenames = []
    for root, dirs, files in os.walk(upload_folder):
        stats["total_dirs"] += len(dirs)
        for fname in files:
            full_path = os.path.join(root, fname)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                size = 0
            stats["total_files"] += 1
            stats["total_size_bytes"] += size
            if fname.lower().endswith(".pdf"):
                stats["pdf_count"] += 1
            else:
                stats["other_count"] += 1
            all_filenames.append(fname)

    if stats["total_files"]:
        stats["avg_size_bytes"] = stats["total_size_bytes"] / stats["total_files"]

    sorted_names = sorted(all_filenames)
    stats["first_10"] = sorted_names[:10]
    stats["last_10"] = sorted_names[-10:]
    return stats


def _print_folder_stats(stats: dict):
    def _fmt_size(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    print("\n" + "=" * 70)
    print("סטטיסטיקת תיקיית uploads (סריקת דיסק)")
    print("=" * 70)
    print(f"  סה\"כ קבצים:            {stats['total_files']}")
    print(f"  סה\"כ תת-תיקיות:        {stats['total_dirs']}")
    print(f"  קבצי PDF:              {stats['pdf_count']}")
    print(f"  קבצים מסוג אחר:        {stats['other_count']}")
    print(f"  גודל כולל:             {_fmt_size(stats['total_size_bytes'])}")
    print(f"  גודל ממוצע לקובץ:      {_fmt_size(stats['avg_size_bytes'])}")
    if stats["first_10"]:
        print(f"  10 הקבצים הראשונים (לפי שם): {stats['first_10']}")
    if stats["last_10"]:
        print(f"  10 הקבצים האחרונים (לפי שם): {stats['last_10']}")
    print("=" * 70)


# ============================================================================
# בדיקת מסמך בודד (קריאה בלבד)
# ============================================================================

def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================================================
# אינדקסים לצורך התאמות חלופיות (שלב אבחון נוסף - עדיין קריאה בלבד).
# נבנים פעם אחת בתחילת ההרצה, כדי לא לסרוק/לחשב hash לכל קובץ מחדש עבור כל
# רשומה בנפרד. המטרה: להבין אם file_path בפורמט ישן/שונה עדיין ניתן למיפוי
# לקובץ הפיזי הנכון - לפי basename או לפי תוכן (hash) - גם כשההתאמה
# המדויקת של הנתיב המלא נכשלת.
# ============================================================================

def _build_basename_index(upload_folder: str) -> dict:
    """ממפה שם קובץ (basename בלבד, בלי תיקיות) -> רשימת נתיבים אבסולוטיים תואמים."""
    index = {}
    if not os.path.isdir(upload_folder):
        return index
    for root, dirs, files in os.walk(upload_folder):
        for fname in files:
            index.setdefault(fname, []).append(os.path.abspath(os.path.join(root, fname)))
    return index


def _build_hash_index(upload_folder: str) -> dict:
    """ממפה SHA-256 של תוכן הקובץ -> נתיב אבסולוטי. סורק את כל התיקייה פעם אחת."""
    index = {}
    if not os.path.isdir(upload_folder):
        return index
    for root, dirs, files in os.walk(upload_folder):
        for fname in files:
            full_path = os.path.join(root, fname)
            try:
                h = _sha256_of_file(full_path)
                index[h] = os.path.abspath(full_path)
            except Exception:
                pass  # קובץ לא קריא - מדלגים, לא עוצרים את כל הסריקה
    return index


def _try_alternate_matches(doc: Document, upload_folder: str, basename_index: dict, hash_index: dict) -> dict:
    """
    מנסה 3 אסטרטגיות התאמה בסדר הזה, ועוצר בראשונה שמצליחה:
    1. נתיב מלא (file_path כפי שהוא, ביחס ל-UPLOAD_FOLDER)
    2. Basename בלבד (רק שם הקובץ מתוך file_path, בכל מקום בתיקייה)
    3. Hash (תוכן הקובץ, לפי file_hash שנשמר ב-DB)
    לא משנה שום דבר - כולן פעולות קריאה/חישוב בלבד.
    """
    result = {
        "attempted": [],
        "full_path_found": False, "full_path_result": None,
        "basename_found": False, "basename_result": None,
        "hash_found": False, "hash_result": None,
        "resolution": "UNRESOLVED",
    }

    file_path = (doc.file_path or "").strip()

    # 1. נתיב מלא
    if file_path:
        result["attempted"].append("full_path")
        candidate = os.path.join(upload_folder, file_path)
        if os.path.isfile(candidate):
            result["full_path_found"] = True
            result["full_path_result"] = os.path.abspath(candidate)
            result["resolution"] = "FULL_PATH"
            return result

    # 2. Basename בלבד
    if file_path:
        result["attempted"].append("basename")
        basename = os.path.basename(file_path)
        matches = basename_index.get(basename, [])
        if matches:
            result["basename_found"] = True
            result["basename_result"] = matches[0] if len(matches) == 1 else matches
            result["resolution"] = "BASENAME"
            return result

    # 3. Hash תוכן
    file_hash = (doc.file_hash or "").strip()
    if file_hash:
        result["attempted"].append("hash")
        match = hash_index.get(file_hash)
        if match:
            result["hash_found"] = True
            result["hash_result"] = match
            result["resolution"] = "HASH"
            return result

    return result


def _inspect_document(doc: Document, upload_folder: str, path_counts: Counter,
                       basename_index: dict, hash_index: dict) -> dict:
    row = {
        "id": doc.id,
        "file_name": doc.file_name or "",
        "file_path": doc.file_path or "",
        "file_hash": doc.file_hash or "",
        "absolute_path": "",
        "path_valid": bool(doc.file_path and doc.file_path.strip()),
        "exists": False,
        "size_bytes": None,
        "created_at": None,
        "modified_time": None,
        "sha256": None,
        "is_symlink": False,
        "readable": False,
        "duplicate": False,
        "error": None,
        # --- שדות התאמה חלופית (אבחון בלבד) ---
        "match_attempted": "",
        "match_resolution": "UNRESOLVED",
        "match_resolved_path": None,
    }

    if row["path_valid"]:
        row["duplicate"] = path_counts.get(doc.file_path, 0) > 1

    # --- ניסיונות התאמה חלופית - תמיד מתבצעים, גם אם path_valid=False,
    # כי ייתכן שאין file_path תקין אך יש file_hash שממנו אפשר עדיין לאתר
    # את הקובץ (למשל אם רק file_path פגום). לא משנה כלום, קריאה בלבד.
    alt = _try_alternate_matches(doc, upload_folder, basename_index, hash_index)
    row["match_attempted"] = ",".join(alt["attempted"]) if alt["attempted"] else "none"
    row["match_resolution"] = alt["resolution"]
    row["match_resolved_path"] = alt["full_path_result"] or alt["basename_result"] or alt["hash_result"]

    if not row["path_valid"]:
        row["error"] = "file_path ריק או לא תקין"
        return row

    full_path = os.path.join(upload_folder, doc.file_path)
    row["absolute_path"] = os.path.abspath(full_path)

    try:
        row["is_symlink"] = os.path.islink(full_path)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            row["exists"] = True
            row["readable"] = os.access(full_path, os.R_OK)
            stat = os.stat(full_path)
            row["size_bytes"] = stat.st_size
            # הערה: st_ctime בלינוקס הוא זמן שינוי metadata אחרון, לא זמן יצירה
            # אמיתי (אין כזה ב-POSIX סטנדרטי) - זהו הקירוב הזמין הכי טוב.
            row["created_at"] = datetime.fromtimestamp(stat.st_ctime).isoformat(timespec='seconds')
            row["modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')
            if row["readable"]:
                row["sha256"] = _sha256_of_file(full_path)
            else:
                row["error"] = "הקובץ קיים אך אין הרשאת קריאה"
        else:
            row["error"] = "קובץ לא נמצא בנתיב הצפוי"
    except Exception as e:
        row["error"] = f"שגיאה בקריאת הקובץ: {e}"

    return row


def _print_verbose_row(row: dict):
    status = "[FOUND]" if row["exists"] else "[MISSING]"
    print(f"\nDocument #{row['id']} - {status}")
    print(f"  file_name:            {row['file_name']}")
    print(f"  file_path:            {row['file_path']}")
    print(f"  file_hash:            {row['file_hash']}")
    print(f"  נתיב אבסולוטי:        {row['absolute_path']}")
    print(f"  קיים (נתיב מלא):      {'כן' if row['exists'] else 'לא'}")
    if row["exists"]:
        size_kb = row["size_bytes"] / 1024 if row["size_bytes"] else 0
        print(f"  גודל:                 {size_kb:.1f} KB ({row['size_bytes']} bytes)")
        print(f"  זמן יצירה (קירוב):    {row['created_at']}")
        print(f"  זמן עדכון אחרון:      {row['modified_time']}")
        print(f"  SHA-256:              {row['sha256']}")
        print(f"  symlink:              {'כן' if row['is_symlink'] else 'לא'}")
        print(f"  הרשאת קריאה:          {'כן' if row['readable'] else 'לא'}")
    print(f"  כפילות file_path:     {'כן' if row['duplicate'] else 'לא'}")
    print(f"  ניסיונות התאמה:       {row['match_attempted']}")
    print(f"  תוצאת התאמה:          {row['match_resolution']}")
    if row["match_resolved_path"]:
        print(f"  נמצא בפועל בנתיב:     {row['match_resolved_path']}")
    if row["error"]:
        print(f"  הערה:                 {row['error']}")


def _write_csv(rows: list, csv_path: str, hostname: str, upload_folder: str):
    fieldnames = [
        "id", "file_name", "file_path", "file_hash", "absolute_path", "path_valid",
        "exists", "size_bytes", "created_at", "modified_time", "sha256",
        "is_symlink", "readable", "duplicate", "match_attempted",
        "match_resolution", "match_resolved_path", "error", "hostname", "upload_folder",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out_row = dict(row)
            out_row["hostname"] = hostname
            out_row["upload_folder"] = upload_folder
            writer.writerow(out_row)


# ============================================================================
# הרצה ראשית
# ============================================================================

def run_reconciliation(verbose: bool, csv_path):
    audit_passed = _self_audit()

    app = create_app()
    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        env_info = _print_environment_info(upload_folder)

        folder_stats = _scan_upload_folder(upload_folder)
        _print_folder_stats(folder_stats)

        print("\nבונה אינדקס Basename ו-Hash לכל הקבצים הפיזיים (לצורך התאמה חלופית)...")
        basename_index = _build_basename_index(upload_folder)
        hash_index = _build_hash_index(upload_folder)
        print(f"  אינדוקס הושלם: {len(basename_index)} שמות קובץ ייחודיים, {len(hash_index)} hash-ים ייחודיים.\n")

        docs = Document.query.order_by(Document.id).all()
        path_counts = Counter(d.file_path for d in docs if d.file_path and d.file_path.strip())
        rows = [_inspect_document(doc, upload_folder, path_counts, basename_index, hash_index) for doc in docs]

        if verbose:
            print()
            for row in rows:
                _print_verbose_row(row)
            print()

        # --- בדיקת עקביות ---
        total = len(rows)
        found = sum(1 for r in rows if r["exists"])
        missing = [r for r in rows if r["path_valid"] and not r["exists"]]
        invalid_path = [r for r in rows if not r["path_valid"]]
        empty_file_name = [r for r in rows if not r["file_name"].strip()]
        unique_paths = len(path_counts)
        duplicates = {path: count for path, count in path_counts.items() if count > 1}

        print("\n" + "=" * 70)
        print("בדיקת עקביות")
        print("=" * 70)
        print(f"  ערכי file_path ייחודיים:     {unique_paths}")
        print(f"  ערכי file_path כפולים:       {len(duplicates)}")
        print(f"  רשומות עם file_path ריק:     {len(invalid_path)}")
        print(f"  רשומות עם file_name ריק:     {len(empty_file_name)}")
        print(f"  רשומות שמצביעות לקובץ קיים:  {found}")
        print(f"  רשומות שמצביעות לקובץ חסר:   {len(missing)}")

        if missing:
            print(f"\n  רשימת קבצים חסרים ({len(missing)}):")
            for r in missing:
                print(f"    - Document #{r['id']} | {r['file_name']} | מצפה ל: {r['absolute_path']}")

        if invalid_path:
            print(f"\n  רשימת רשומות עם file_path ריק/לא תקין ({len(invalid_path)}):")
            for r in invalid_path:
                print(f"    - Document #{r['id']} | {r['file_name']}")

        if duplicates:
            print(f"\n  ערכי file_path כפולים ({len(duplicates)}):")
            for path, count in duplicates.items():
                dup_ids = [r['id'] for r in rows if r['file_path'] == path]
                print(f"    - '{path}' מופיע {count} פעמים ברשומות: {dup_ids}")

        # --- סיכום השוואה (Coverage) ---
        docs_in_db = total
        files_on_disk = folder_stats["total_files"]
        matched = found
        coverage_pct = (matched / docs_in_db * 100) if docs_in_db else 0.0

        print("\n" + "=" * 70)
        print("סיכום השוואה")
        print("=" * 70)
        print(f"  Documents in DB:  {docs_in_db:,}")
        print(f"  Files on Disk:    {files_on_disk:,}")
        print(f"  Matched:          {matched:,}")
        print(f"  Coverage:         {coverage_pct:.2f}%")
        print("=" * 70)

        # --- פילוח תוצאות ההתאמה החלופית (אבחון: נתיב ישן מול DB שגוי מול קובץ אבוד) ---
        resolution_counts = Counter(r["match_resolution"] for r in rows)
        print("\n" + "=" * 70)
        print("פילוח התאמה חלופית (אבחון)")
        print("=" * 70)
        print(f"  נפתר לפי נתיב מלא (FULL_PATH):    {resolution_counts.get('FULL_PATH', 0)}")
        print(f"  נפתר לפי שם קובץ בלבד (BASENAME):  {resolution_counts.get('BASENAME', 0)}")
        print(f"  נפתר לפי תוכן/Hash (HASH):         {resolution_counts.get('HASH', 0)}")
        print(f"  לא נפתר בכלל (UNRESOLVED):         {resolution_counts.get('UNRESOLVED', 0)}")

        resolved_by_basename = [r for r in rows if r["match_resolution"] == "BASENAME"]
        resolved_by_hash = [r for r in rows if r["match_resolution"] == "HASH"]
        unresolved = [r for r in rows if r["match_resolution"] == "UNRESOLVED"]

        if resolved_by_basename:
            print(f"\n  נפתרו לפי BASENAME בלבד ({len(resolved_by_basename)}) - "
                  f"סימן לנתיב ישן/שונה שבכל זאת ניתן למיפוי:")
            for r in resolved_by_basename:
                print(f"    - Document #{r['id']} | file_path='{r['file_path']}' -> נמצא ב: {r['match_resolved_path']}")

        if resolved_by_hash:
            print(f"\n  נפתרו לפי HASH בלבד ({len(resolved_by_hash)}) - "
                  f"סימן שהקובץ קיים בפועל אך שמו/מיקומו שונה לגמרי מ-file_path:")
            for r in resolved_by_hash:
                print(f"    - Document #{r['id']} | file_path='{r['file_path']}' -> נמצא ב: {r['match_resolved_path']}")

        if unresolved:
            print(f"\n  לא נפתרו באף אסטרטגיה ({len(unresolved)}) - "
                  f"ייתכן שהקובץ הפיזי לא קיים בכלל בתיקייה הזו:")
            for r in unresolved:
                print(f"    - Document #{r['id']} | file_name='{r['file_name']}' | file_path='{r['file_path']}' | file_hash='{r['file_hash']}'")

        print("=" * 70 + "\n")

        if csv_path:
            _write_csv(rows, csv_path, env_info["hostname"], upload_folder)
            print(f"הפלט המלא יוצא ל-CSV: {csv_path}\n")

        print(f"אימות עצמי (Self-Audit): {'[PASS]' if audit_passed else '[FAIL] - עצור ובדוק!'}\n")

        return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="דו\"ח התאמה - קריאה בלבד, לא משנה כלום")
    parser.add_argument('--verbose', action='store_true', help='הדפס פירוט מלא לכל מסמך (לא רק סיכום)')
    parser.add_argument('--csv', type=str, default=None, metavar='PATH', help='ייצוא התוצאות המלאות לקובץ CSV')
    args = parser.parse_args()

    run_reconciliation(verbose=args.verbose, csv_path=args.csv)
