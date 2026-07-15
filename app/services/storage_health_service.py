"""
Service Layer עבור Storage Health Check (Commit 6, Document Storage
Management). זרימה מחייבת: Scan -> Report -> Preview Cleanup -> Approve
-> Delete. שלב ה-Scan (וגם ה-Preview) הם קריאה בלבד לחלוטין - שום מחיקה
לא מתבצעת עד לקריאה מפורשת ל-cleanup_confirm() עם רשימת נתיבים מאושרת.
"""
import logging
import os
from datetime import datetime

from app.extensions import db
from app.models import Document
from app.services import storage
from app.services import auth_service
from app.services import audit_log_service as alog

logger = logging.getLogger(__name__)


def scan(upload_folder: str) -> dict:
    """
    סריקה מלאה, קריאה בלבד. שלושה כיוונים:
    1. DB -> Storage: רשומות עם file_path שאין להן קובץ פיזי תואם (missing).
    2. Storage -> DB: קבצים פיזיים (מקומיים + Supabase) שאין אף רשומה
       *פעילה* (לא deleted) שמפנה אליהם (orphaned).
    3. Hash validation: לקבצים מקומיים שנמצאו - השוואת ה-hash שחושב בפועל
       מול מה שרשום ב-DB (hash_errors).

    מסמכים עם status='deleted' *לא* נספרים כ"טוענים בעלות" על קובץ - אם
    יש עדיין קובץ פיזי בנתיב שלהם (למשל כי מחיקת ה-Storage נכשלה - התרחיש
    שתועד ב-Commit 4/5), הוא *כן* צריך להופיע כ-orphan, כי הוא אמור היה
    להימחק.
    """
    all_docs = Document.query.all()
    relevant_docs = [d for d in all_docs if d.status != 'deleted' and d.file_path]

    missing_items = []
    hash_error_items = []
    healthy_count = 0
    referenced_paths = set()

    for doc in relevant_docs:
        referenced_paths.add(doc.file_path)
        result = storage.file_exists(doc.file_path, upload_folder)
        if not result["status"]:
            missing_items.append({
                "document_id": doc.id, "file_name": doc.file_name, "file_path": doc.file_path,
            })
            continue

        if result["location"] == "local":
            try:
                actual_hash = storage.calculate_file_hash(os.path.join(upload_folder, os.path.basename(doc.file_path)))
            except Exception as e:
                missing_items.append({
                    "document_id": doc.id, "file_name": doc.file_name, "file_path": doc.file_path,
                    "note": f"נמצא אך לא ניתן לקריאה: {e}",
                })
                continue
            if actual_hash != doc.file_hash:
                hash_error_items.append({
                    "document_id": doc.id, "file_name": doc.file_name,
                    "expected_hash": doc.file_hash, "actual_hash": actual_hash,
                })
                continue
        # קבצי Supabase: אימות hash ידרוש הורדת התוכן המלא (יקר) - לא
        # מבוצע בשלב זה. נחשבים "healthy" אם signed URL תקין (result["status"]).

        healthy_count += 1

    # --- Storage -> DB: איתור orphans (קבצים בלי רשומה *פעילה* שמפנה אליהם) ---
    orphaned_items = []

    local_files = storage.list_local_files(upload_folder)
    for f in local_files:
        if f["filename"] not in referenced_paths:
            orphaned_items.append({
                "path": f["filename"], "size": f["size"], "location": "local",
                "modified_at": f.get("modified_at"),
                "reason": "קובץ פיזי בדיסק המקומי ללא רשומת Document שמפנה אליו",
            })

    bucket = None
    if storage.is_configured():
        bucket_files = storage.list_supabase_files()
        bucket = storage.get_bucket_name()
        for f in bucket_files:
            full_ref = f"{bucket}/{f['filename']}"
            if full_ref not in referenced_paths:
                orphaned_items.append({
                    "path": full_ref, "size": f.get("size"), "location": "supabase",
                    "modified_at": f.get("modified_at"),
                    "reason": "קובץ ב-Supabase Storage ללא רשומת Document שמפנה אליו",
                })

    return {
        "scanned_at": datetime.utcnow().isoformat(),
        "total_documents": len(relevant_docs),
        "healthy": healthy_count,
        "missing": len(missing_items),
        "orphaned": len(orphaned_items),
        "hash_errors": len(hash_error_items),
        "missing_items": missing_items,
        "orphaned_items": orphaned_items,
        "hash_error_items": hash_error_items,
    }


def cleanup_preview(upload_folder: str) -> list:
    """
    Preview בלבד - מריץ סריקה טרייה ומחזיר רק את רשימת ה-orphans.
    קריאה בלבד, בדיוק כמו scan() - שום דבר לא נמחק כאן.
    """
    result = scan(upload_folder)
    return result["orphaned_items"]


def cleanup_confirm(orphan_paths: list, acting_user_id, upload_folder: str) -> dict:
    """
    השלב היחיד בכל המודול שבאמת מוחק קבצים. חייב רשימת נתיבים מפורשת
    (מה שהוצג ב-Preview לאדמין ואושר על ידו) - לא "מוחק את כל מה שנמצא
    orphan עכשיו" באופן עיוור.

    לפני מחיקה בפועל, מריץ סריקה טרייה נוספת ומוודא שכל נתיב עדיין
    באמת orphan *עכשיו* (הגנה מפני מצב שבו בין ה-Preview לאישור נוצרה
    רשומה חדשה שכן מצביעה לקובץ הזה). ממשיך פריט-אחר-פריט - כשל במחיקת
    קובץ אחד לא עוצר את השאר ולא הופך את הפעולה לכישלון גורף.
    """
    auth_service.require_role(acting_user_id, ['admin', 'super_admin'])

    fresh_orphans = {item["path"] for item in cleanup_preview(upload_folder)}

    deleted, skipped, failed = [], [], []

    for path in orphan_paths:
        if path not in fresh_orphans:
            skipped.append({"path": path, "reason": "כבר לא orphan בפועל (כנראה קושר לרשומה חדשה בינתיים)"})
            continue

        alog.log('orphan_cleanup_pending', 'storage_file', None, entity_label=path, old_value={"path": path})
        db.session.commit()

        result = storage.delete_file(path, upload_folder)
        if result["status"]:
            deleted.append(path)
            alog.log('orphan_cleanup', 'storage_file', None, entity_label=path)
        else:
            failed.append({"path": path, "error": result["error"]})
            logger.warning(f"Orphan cleanup failed for {path}: {result['error']}")
            alog.log('orphan_cleanup_failed', 'storage_file', None, entity_label=path,
                     new_value={"error": result["error"]})
        db.session.commit()

    global _last_cleanup_at
    _last_cleanup_at = datetime.utcnow().isoformat()

    return {"deleted": deleted, "skipped": skipped, "failed": failed}


# ============================================================================
# Commit 7 (Admin UI) - נתוני סיכום לדשבורד. לא משנה את scan()/report הקיימים
# (עדיין באותו contract בדיוק) - עוטף אותם ומוסיף פילוח status + חותמות זמן,
# כדי שהמסך יוכל להציג Total/Active/Archived/Deleted/Last Scan/Last Cleanup.
# ============================================================================

_last_scan_at = None      # in-memory, מתאפס בהפעלה מחדש של השרת - כמו ה-cache של org_dashboard_service
_last_cleanup_at = None   # מתעדכן גם דרך AuditLog (persisted), אבל נשמר גם כאן לתצוגה מהירה בלי שאילתה נוספת


def get_status_counts() -> dict:
    """קריאה בלבד: כמה מסמכים בכל status (כולל deleted, שלא נכלל ב-scan())."""
    rows = db.session.query(Document.status, db.func.count(Document.id)).group_by(Document.status).all()
    counts = {status: count for status, count in rows}
    return {
        "active": counts.get('active', 0),
        "archived": counts.get('archived', 0),
        "deleted": counts.get('deleted', 0),
        "draft": counts.get('draft', 0),
        "total": sum(counts.values()),
    }


def dashboard_summary(upload_folder: str) -> dict:
    """
    מריץ scan() טרי ומעשיר אותו בפילוח status + זמני scan/cleanup אחרונים,
    לצורך מסך Admin Storage Dashboard. לא מחליף את scan()/report - אלה
    נשארים כפי שהם (עדיין בשימוש ע"י cleanup_preview/cleanup_confirm).
    """
    global _last_scan_at
    result = scan(upload_folder)
    _last_scan_at = result["scanned_at"]

    status_counts = get_status_counts()
    result.update(status_counts)
    result["last_scan_at"] = _last_scan_at
    result["last_cleanup_at"] = _last_cleanup_at
    return result
