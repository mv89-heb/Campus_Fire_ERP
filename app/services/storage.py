"""
Service Layer עבור Supabase Storage.
כל קוד ה-Supabase SDK מרוכז כאן בלבד. שאר המערכת (routes, dms_service) לא
מייבאת את supabase-py ישירות, ולא יודעת אם הקובץ מגיע מ-Supabase או מדיסק
מקומי - זו אחריות של המודול הזה ושל serve_upload בלבד.

עקרון תאימות: אם SUPABASE_URL / SUPABASE_SERVICE_KEY לא מוגדרים, is_configured()
מחזיר False והמערכת נופלת בחזרה לאחסון מקומי (uploads/) כמו קודם - שום קריאה
ל-Supabase לא מתבצעת בכלל.
"""
import hashlib
import logging
import os
from datetime import datetime

from flask import current_app

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """שגיאה עסקית צפויה בהעלאה/הורדה מ-Supabase - חוזרת ללקוח עם הודעה ברורה."""
    pass


_client_cache = {}


def _get_client():
    """
    יוצר (ומקבץ במטמון per-process) לקוח Supabase. לא נוצר עד לשימוש בפועל,
    כדי שסביבות בלי Supabase מוגדר לא ייכשלו רק מלייבא את המודול הזה.
    """
    url = current_app.config.get('SUPABASE_URL')
    key = current_app.config.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        raise StorageError("Supabase אינו מוגדר (חסרים SUPABASE_URL / SUPABASE_SERVICE_KEY)")

    cache_key = (url, key)
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    from supabase import create_client
    client = create_client(url, key)
    _client_cache[cache_key] = client
    return client


def _bucket_name():
    return current_app.config.get('SUPABASE_BUCKET', 'documents')


def get_bucket_name() -> str:
    """גרסה ציבורית של _bucket_name(), לשימוש מודולים אחרים (כמו storage_health_service)."""
    return _bucket_name()


def is_configured() -> bool:
    return bool(current_app.config.get('SUPABASE_URL')) and bool(current_app.config.get('SUPABASE_SERVICE_KEY'))


def check_connection():
    """
    בדיקת חיבור קלה (לשימוש ב-/api/system/health): מנסה לרשום את תוכן
    ה-bucket. מחזיר (True, None) בהצלחה או (False, "הודעת שגיאה") בכישלון.
    """
    if not is_configured():
        return False, "Supabase לא מוגדר"
    try:
        client = _get_client()
        client.storage.from_(_bucket_name()).list()
        return True, None
    except Exception as e:
        logger.error(f"Supabase connection check failed: {e}")
        return False, str(e)


def is_supabase_path(file_path: str) -> bool:
    """
    האם file_path (כפי שנשמר בעמודת documents.file_path) מצביע על Supabase
    (בפורמט 'documents/uuid.pdf') להבדיל מפורמט מקומי ישן ('uuid.pdf' בלבד).
    """
    if not file_path:
        return False
    return file_path.startswith(f"{_bucket_name()}/")


def upload_bytes(remote_filename: str, data: bytes, content_type: str = 'application/pdf') -> str:
    """
    מעלה בייטים ל-Supabase Storage תחת ה-bucket המוגדר.
    מחזיר את הנתיב היחסי לשמירה ב-DB, לדוגמה: 'documents/uuid.pdf'.
    מעלה StorageError בכישלון - הקריאה בצד הלקוח (dms_service) אחראית לא
    ליצור רשומת Document אם הפעולה הזו נכשלה.
    """
    client = _get_client()
    bucket = _bucket_name()
    try:
        client.storage.from_(bucket).upload(
            path=remote_filename,
            file=data,
            file_options={"content-type": content_type},
        )
    except Exception as e:
        logger.error(f"Supabase upload failed for {remote_filename}: {e}")
        raise StorageError(f"העלאה ל-Supabase Storage נכשלה: {e}")
    return f"{bucket}/{remote_filename}"


def delete_object(stored_path: str):
    """
    מוחק אובייקט מ-Supabase (cleanup, לדוגמה אחרי כשל בכתיבה ל-Neon).
    לא מעלה חריגה בכישלון - רק רושם ללוג, כדי לא להסתיר את השגיאה המקורית
    שבגללה בוצע ה-cleanup מלכתחילה.
    """
    if not stored_path:
        return
    bucket = _bucket_name()
    remote_filename = stored_path[len(bucket) + 1:] if stored_path.startswith(f"{bucket}/") else stored_path
    try:
        client = _get_client()
        client.storage.from_(bucket).remove([remote_filename])
    except Exception as e:
        logger.error(f"Supabase cleanup delete failed for {stored_path}: {e}")


def get_signed_url(stored_path: str, expires_in: int = 300):
    """
    מייצר signed URL זמני לפתיחת קובץ מ-bucket פרטי.
    stored_path יכול להיות 'documents/uuid.pdf' (עם ה-bucket) או שם קובץ בלבד.
    מחזיר את ה-URL, או None אם הפעולה נכשלה (הקורא אחראי ל-fallback).
    """
    bucket = _bucket_name()
    remote_filename = stored_path[len(bucket) + 1:] if stored_path.startswith(f"{bucket}/") else stored_path
    try:
        client = _get_client()
        res = client.storage.from_(bucket).create_signed_url(remote_filename, expires_in)
        # גרסאות שונות של supabase-py מחזירות מפתחות שונים (signedURL/signedUrl/signed_url)
        if isinstance(res, dict):
            return res.get('signedURL') or res.get('signedUrl') or res.get('signed_url')
        return getattr(res, 'signed_url', None)
    except Exception as e:
        logger.error(f"Supabase signed URL failed for {stored_path}: {e}")
        return None


# ============================================================================
# Commit 3 (Document Storage Management) - פונקציות מרוכזות ל-hash/scan/exists.
# הרחבה בלבד: לא נוגעות/לא משנות אף פונקציה שהוגדרה מעל. מטרתן למצות לוגיקה
# שהייתה משוכפלת ב-5 מקומות שונים (dms_service.py וסקריפטי scripts/) למקור
# אמת אחד. שימו לב: reconcile_documents.py ו-prepare_document_relink.py
# *במכוון* לא הועברו להשתמש בפונקציות האלה - יש להם Self-Audit שאוסר
# עליהם לייבא את המודול הזה בכלל, כדי להבטיח שהם Read-Only באופן מבני
# (לא רק בהצהרה). זו תכונת בטיחות ששימור שלה חשוב יותר ממיצוי הכפילות שם.
# ============================================================================

def calculate_hash(data: bytes) -> str:
    """SHA-256 של בייטים בזיכרון (למשל תוכן קובץ שכבר נקרא/הועלה)."""
    return hashlib.sha256(data).hexdigest()


def calculate_file_hash(local_path: str) -> str:
    """SHA-256 של קובץ בדיסק, בקריאה זורמת (streaming) - לא טוען הכל לזיכרון בבת אחת."""
    h = hashlib.sha256()
    with open(local_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_exists(file_path: str, upload_folder: str) -> dict:
    """
    בודק אם קובץ קיים בפועל - Supabase (אם הפורמט מתאים ו-Supabase מוגדר)
    או דיסק מקומי, בהתאם לפורמט ה-file_path (תואם ל-serve_upload).
    Result envelope אחיד: {"status": True/False, "location": "local"/"supabase"/None, "error": ...}
    """
    if not file_path:
        return {"status": False, "location": None, "error": "file_path ריק"}

    if is_supabase_path(file_path) and is_configured():
        signed_url = get_signed_url(file_path)
        if signed_url:
            return {"status": True, "location": "supabase", "error": None}
        # לא נמצא ב-Supabase - עדיין בודקים fallback מקומי לפני שמכריזים "לא קיים"

    local_full_path = os.path.join(upload_folder, os.path.basename(file_path))
    if os.path.isfile(local_full_path):
        return {"status": True, "location": "local", "error": None}

    return {"status": False, "location": None, "error": "לא נמצא לא ב-Supabase ולא מקומית"}


def list_local_files(upload_folder: str) -> list:
    """
    סורק את תיקיית ה-uploads המקומית (רקורסיבית) ומחזיר רשימת
    {"filename": ..., "path": <אבסולוטי>, "size": ..., "modified_at": ...} לכל קובץ.
    לא נוגע ב-Supabase בכלל - זו סריקה מקומית בלבד.
    """
    results = []
    if not os.path.isdir(upload_folder):
        return results
    for root, dirs, files in os.walk(upload_folder):
        for fname in files:
            full_path = os.path.join(root, fname)
            try:
                stat = os.stat(full_path)
                size = stat.st_size
                modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError:
                size = None
                modified_at = None
            results.append({"filename": fname, "path": os.path.abspath(full_path), "size": size, "modified_at": modified_at})
    return results


def build_local_hash_index(upload_folder: str) -> dict:
    """ממפה SHA-256 -> נתיב אבסולוטי, לכל קובץ מקומי. נבנה פעם אחת, נסרק פעם אחת."""
    index = {}
    for entry in list_local_files(upload_folder):
        try:
            index[calculate_file_hash(entry["path"])] = entry["path"]
        except Exception as e:
            logger.warning(f"Could not hash {entry['path']}: {e}")
    return index


def build_local_basename_index(upload_folder: str) -> dict:
    """ממפה שם קובץ (basename) -> רשימת נתיבים אבסולוטיים תואמים."""
    index = {}
    for entry in list_local_files(upload_folder):
        index.setdefault(entry["filename"], []).append(entry["path"])
    return index


# ============================================================================
# Commit 4 (Safe Delete) - מחיקת קובץ פיזי, מקומי או Supabase, לפי פורמט
# ה-file_path (תואם ל-file_exists/serve_upload). Result envelope אחיד,
# לא מעלה חריגה - הקורא (permit_service.safe_delete_document) מחליט מה
# לעשות בכשל (בפרט: לא לעצור את התהליך, כי ה-DB כבר עודכן בשלב הזה).
# ============================================================================

def delete_file(file_path: str, upload_folder: str) -> dict:
    """
    מוחק קובץ פיזי בפועל. תמיד מחזיר dict, אף פעם לא מעלה חריגה:
    {"status": True, "error": None} או {"status": False, "error": "..."}
    """
    if not file_path:
        return {"status": False, "error": "file_path ריק"}

    if is_supabase_path(file_path) and is_configured():
        try:
            delete_object(file_path)
        except Exception as e:
            return {"status": False, "error": f"מחיקת Supabase נכשלה: {e}"}
        # delete_object עצמו לא מעלה חריגה גם בכשל (מתועד ב-docstring שלו) -
        # לכן מוודאים בפועל שהקובץ אכן נעלם, ולא רק "מניחים" שהצליח.
        still_accessible = get_signed_url(file_path) is not None
        if still_accessible:
            return {"status": False, "error": "הקובץ עדיין נגיש ב-Supabase אחרי ניסיון המחיקה"}
        return {"status": True, "error": None}

    local_full_path = os.path.join(upload_folder, os.path.basename(file_path))
    if not os.path.isfile(local_full_path):
        return {"status": False, "error": f"קובץ מקומי לא נמצא: {local_full_path}"}
    try:
        os.remove(local_full_path)
        return {"status": True, "error": None}
    except Exception as e:
        return {"status": False, "error": f"מחיקה מקומית נכשלה: {e}"}


# ============================================================================
# Commit 5 (Safe Replace) - העלאת קובץ "חדש" לפני נגיעה ב-DB, ואימות בסיסי
# שזה בכלל PDF. תמיד Result envelope, אף פעם לא מעלה חריגה.
# ============================================================================

def upload_temp(data: bytes, filename: str, upload_folder: str) -> dict:
    """
    מעלה בייטים לאחסון - Supabase אם מוגדר, אחרת דיסק מקומי (תואם ל-
    dms_service.ingest_document: כשאין Supabase, הקובץ נשמר ב-upload_folder
    ו-file_path נשמר כשם קובץ שטוח בלי קידומת). משמש בזרימת Replace כדי
    להעלות את הקובץ החדש *לפני* שנוגעים ב-DB בכלל.
    Result: {"status": True, "path": <לשמירה ב-file_path>, "hash": ..., "size": ...}
         או {"status": False, "error": ...}
    """
    file_hash = calculate_hash(data)
    file_size = len(data)
    try:
        if is_configured():
            stored_path = upload_bytes(filename, data)
        else:
            local_path = os.path.join(upload_folder, filename)
            with open(local_path, 'wb') as f:
                f.write(data)
            stored_path = filename
        return {"status": True, "path": stored_path, "hash": file_hash, "size": file_size, "error": None}
    except Exception as e:
        logger.error(f"upload_temp failed for {filename}: {e}")
        return {"status": False, "path": None, "hash": None, "size": None, "error": str(e)}


def verify_pdf_bytes(data: bytes) -> dict:
    """
    בדיקת תקינות בסיסית - האם זה בכלל קובץ PDF (בדיקת magic bytes, לא
    פענוח מלא). Result envelope: {"status": True} או {"status": False, "error": ...}
    """
    if not data:
        return {"status": False, "error": "קובץ ריק"}
    if not data[:5] == b'%PDF-':
        return {"status": False, "error": "הקובץ אינו PDF תקין (חסר header %PDF-)"}
    return {"status": True, "error": None}


# ============================================================================
# Commit 6 (Storage Health Check) - קריאה בלבד. רשימת כל הקבצים ב-Supabase,
# עם pagination (Supabase מגביל כברירת מחדל ל-100 פריטים לקריאה). לא מוחקת,
# לא משנה כלום - רק סורקת ומדווחת.
# ============================================================================

def list_supabase_files() -> list:
    """
    רשימת כל הקבצים ב-Supabase bucket. מחזירה [] אם Supabase לא מוגדר או
    שהקריאה נכשלת - לא מעלה חריגה, זו פעולת דיווח בלבד ואסור לה לעצור
    סריקה שלמה בגלל תקלת רשת חולפת.
    """
    if not is_configured():
        return []
    results = []
    bucket = _bucket_name()
    try:
        client = _get_client()
        limit = 100
        offset = 0
        while True:
            page = client.storage.from_(bucket).list(options={"limit": limit, "offset": offset})
            if not page:
                break
            for item in page:
                name = item.get('name') if isinstance(item, dict) else getattr(item, 'name', None)
                if not name:
                    continue
                size = None
                metadata = item.get('metadata') if isinstance(item, dict) else None
                if isinstance(metadata, dict):
                    size = metadata.get('size')
                results.append({"filename": name, "size": size})
            if len(page) < limit:
                break
            offset += limit
    except Exception as e:
        logger.error(f"list_supabase_files failed: {e}")
    return results
