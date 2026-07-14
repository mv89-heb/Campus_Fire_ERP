"""
Service Layer עבור Supabase Storage.
כל קוד ה-Supabase SDK מרוכז כאן בלבד. שאר המערכת (routes, dms_service) לא
מייבאת את supabase-py ישירות, ולא יודעת אם הקובץ מגיע מ-Supabase או מדיסק
מקומי - זו אחריות של המודול הזה ושל serve_upload בלבד.

עקרון תאימות: אם SUPABASE_URL / SUPABASE_SERVICE_KEY לא מוגדרים, is_configured()
מחזיר False והמערכת נופלת בחזרה לאחסון מקומי (uploads/) כמו קודם - שום קריאה
ל-Supabase לא מתבצעת בכלל.
"""
import logging

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
