"""
Service Layer עבור הרחבת מודול האישורים (שלב 2) ומודול מסמכים (שלב 9).
מטפל בעריכת מטא-דאטה של אישור קיים (Document), שכפול אישור לצורך חידוש,
חיפוש/סינון/מיון, נעילה מפני עריכה, וארכוב, עם תיעוד היסטוריית שינויים.
"""
import logging
import uuid
from datetime import date, datetime

from app.extensions import db
from app.models import Document, Zone, SystemRequirement, DocumentHistory, User
from app.services import audit_log_service as alog
from app.services import auth_service
from app.services import storage

logger = logging.getLogger(__name__)


class PermitServiceError(Exception):
    """שגיאה עסקית צפויה שצריכה לחזור ללקוח כ-400/404."""
    pass


EDITABLE_FIELDS = [
    'permit_number', 'issuing_body', 'issue_date', 'expiry_date',
    'contact_name', 'notes', 'category', 'tags', 'status',
]

_DATE_FIELDS = {'issue_date', 'expiry_date'}
_TRACKED_FIELDS = {'expiry_date', 'status', 'permit_number', 'category'}  # שדות שהשינוי בהם נרשם בהיסטוריה


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise PermitServiceError(f"פורמט תאריך לא תקין: {value} (נדרש YYYY-MM-DD)")


def get_document_or_404(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc:
        raise PermitServiceError(f"אישור {doc_id} לא נמצא")
    return doc


def _ensure_unlocked(doc):
    if doc.locked:
        raise PermitServiceError("האישור נעול לעריכה. יש לשחרר את הנעילה תחילה")


def update_permit(doc_id, data):
    doc = get_document_or_404(doc_id)
    _ensure_unlocked(doc)
    if doc.status == 'deleted':
        raise PermitServiceError("לא ניתן לערוך מסמך שנמחק - הוא במצב תצוגה בלבד")
    for field in EDITABLE_FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            old_value = getattr(doc, field)
            if field in _TRACKED_FIELDS and str(old_value) != str(value):
                db.session.add(DocumentHistory(
                    document_id=doc.id, field_name=field,
                    old_value=str(old_value) if old_value is not None else None,
                    new_value=str(value) if value is not None else None,
                ))
            setattr(doc, field, value)
    alog.log('update', 'permit', doc.id, entity_label=doc.file_name, new_value=data)
    db.session.commit()
    return doc


def set_locked(doc_id, locked):
    doc = get_document_or_404(doc_id)
    doc.locked = bool(locked)
    alog.log('lock' if locked else 'unlock', 'permit', doc.id, entity_label=doc.file_name)
    db.session.commit()
    return doc


def get_history(doc_id):
    get_document_or_404(doc_id)
    return (DocumentHistory.query.filter_by(document_id=doc_id)
            .order_by(DocumentHistory.changed_at.desc()).all())


def duplicate_permit(doc_id):
    """
    יוצר רשומת אישור חדשה (טיוטה) לצורך חידוש, עם אותה מטא-דאטה של האישור
    המקורי אך ללא קובץ מצורף. שימושי כשמתחילים תהליך חידוש לפני שהקובץ מוכן.
    """
    src = get_document_or_404(doc_id)
    draft = Document(
        req_id=src.req_id,
        zone_id=src.zone_id,
        file_name=f"טיוטה - {src.file_name}",
        file_path='',
        file_hash=f"draft-{uuid.uuid4().hex}",
        expiry_date=None,
        status='draft',
        permit_number=src.permit_number,
        issuing_body=src.issuing_body,
        issue_date=None,
        contact_name=src.contact_name,
        notes=src.notes,
        category=src.category,
        tags=src.tags,
    )
    db.session.add(draft)
    db.session.flush()
    alog.log('create', 'permit', draft.id, entity_label=draft.file_name, new_value={'duplicated_from': doc_id})
    db.session.commit()
    return draft


def safe_delete_document(doc_id, acting_user_id, upload_folder):
    """
    Commit 4 (Safe Delete) - מחליף את delete_permit הישן, שמחק רק את
    הרשומה מה-DB בלי לגעת בקובץ הפיזי (יצר קובץ יתום בכל מחיקה).

    Option B (הוחלט במפורש אחרי Audit נוסף שגילה IntegrityError):
    file_path/file_hash/file_size *נשארים* ברשומה כפי שהיו - לא מאופסים
    ל-NULL, כי העמודות האלה הן nullable=False (ולא רוצים migration נוסף
    מול Production). הסימון היחיד ל"נמחק" הוא status='deleted' +
    deleted_at + deleted_by. ההיסטוריה המלאה (כולל הערכים ה"ישנים",
    לצורך שקיפות) כבר נשמרת גם ב-AuditLog.old_value לפני השינוי.

    **קריטי**: מכיוון שה-file_path נשאר ברשומה גם אחרי המחיקה, כל שאילתה
    שמחזירה "מסמכים פעילים/רלוונטיים" במערכת חייבת להחריג במפורש
    status='deleted' (ר' תיעוד מלא ב-models.py ליד הגדרת עמודת status) -
    אחרת המסמך "הרוח" הזה יופיע כאילו יש לו קובץ תקין, כשלמעשה הוא נמחק.
    כל השאילתות הרלוונטיות בפרויקט עודכנו לכך כחלק מ-commit זה.

    סדר הפעולות מכוון: DB מתעדכן ו-commit-מאושר *לפני* שנוגעים בקובץ
    הפיזי, כדי שלעולם לא ייווצר מצב שבו ה-DB "חושב" שהמסמך עדיין פעיל
    בזמן שהקובץ כבר נמחק. המחיר: אם מחיקת הקובץ הפיזי נכשלת (אחרי שה-DB
    כבר commit בהצלחה), נשאר קובץ יתום זמנית - זה תרחיש מתועד ומקובל,
    שנתפס ע"י Storage Health Check (Commit 6).

    acting_user_id: חובה (לא None) - נבדק מול auth_service.require_role
    לפני כל שינוי. upload_folder: app.config['UPLOAD_FOLDER'], מועבר
    מפורשות מה-route (לא נקרא כאן מ-current_app), כדי שהפונקציה תישאר
    ניתנת לבדיקה גם מחוץ להקשר Flask מלא.
    """
    auth_service.require_role(acting_user_id, ['admin', 'super_admin'])

    doc = get_document_or_404(doc_id)
    _ensure_unlocked(doc)
    if doc.status == 'deleted':
        raise PermitServiceError("המסמך כבר נמחק")

    old_snapshot = {
        "file_path": doc.file_path, "file_hash": doc.file_hash,
        "file_name": doc.file_name, "file_size": doc.file_size,
    }
    alog.log('delete_pending', 'permit', doc.id, entity_label=doc.file_name, old_value=old_snapshot)

    file_path_to_remove = doc.file_path  # לא מאפסים ברשומה (Option B), אבל צריך את הערך כדי למחוק את הקובץ הפיזי בהמשך
    doc.deleted_at = datetime.utcnow()
    doc.deleted_by = acting_user_id
    doc.status = 'deleted'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        alog.log('delete_failed', 'permit', doc_id, entity_label=old_snapshot.get('file_name'),
                 new_value={"error": str(e)})
        db.session.commit()  # שומר את רשומת ה-alog של הכשל עצמו
        raise PermitServiceError(f"מחיקת המסמך נכשלה (DB) - לא בוצע שום שינוי: {e}")

    # מכאן והלאה ה-DB כבר עקבי ותקין (status='deleted'). מה שקורה עם הקובץ
    # הפיזי הוא best-effort - כשל כאן לא הופך את ה-DB ללא-תקין.
    storage_result = {"status": False, "error": "לא היה file_path פיזי למחיקה"}
    if file_path_to_remove:
        storage_result = storage.delete_file(file_path_to_remove, upload_folder)

    if not storage_result["status"]:
        logger.warning(f"Document #{doc_id} סומן כנמחק ב-DB אך ניקוי הקובץ הפיזי נכשל: {storage_result['error']}")
        alog.log('delete_orphan_warning', 'permit', doc_id, entity_label=old_snapshot.get('file_name'),
                 new_value={"old_file_path": file_path_to_remove, "error": storage_result["error"]})
    else:
        alog.log('delete', 'permit', doc_id, entity_label=old_snapshot.get('file_name'))
    db.session.commit()  # alog.log() רק מוסיף ל-session, לא מבצע commit בעצמו - חובה כאן

    return doc


def safe_replace_document(doc_id, acting_user_id, new_file_bytes, new_original_filename, upload_folder):
    """
    Commit 5 (Safe Replace). מחליף את הקובץ הפיזי של מסמך קיים, תוך שמירה
    על כך שהמסמך הישן נשאר פעיל ותקין לאורך כל הדרך עד שהחדש כבר מאומת
    ב-DB בהצלחה.

    סדר הפעולות (מאושר בתכנון): מעלים את הקובץ החדש *לפני* שנוגעים ב-DB
    בכלל -> אם ההעלאה נכשלת, לא השתנה שום דבר. רק אחרי הצלחה, ה-DB
    מתעדכן ל-file_path/file_hash/file_size החדשים ומאושר (commit). רק
    *אחרי* שההחלפה כבר "אמת" ב-DB, מוחקים את הקובץ הישן - לא לפני.

    doc.file_name (השם המקורי המוצג) *לא* משתנה - זו החלפת תוכן הקובץ,
    לא שינוי המטא-דאטה של המסמך. אם ירצו לשנות גם את השם, יש כבר
    update_permit() קיים לכך בנפרד.
    """
    auth_service.require_role(acting_user_id, ['admin', 'super_admin'])

    doc = get_document_or_404(doc_id)
    _ensure_unlocked(doc)
    if doc.status == 'deleted':
        raise PermitServiceError("לא ניתן להחליף קובץ במסמך שנמחק")

    validity = storage.verify_pdf_bytes(new_file_bytes)
    if not validity["status"]:
        raise PermitServiceError(f"הקובץ החדש לא תקין: {validity['error']}")

    new_filename = f"{uuid.uuid4().hex}.pdf"
    upload_result = storage.upload_temp(new_file_bytes, new_filename, upload_folder)
    if not upload_result["status"]:
        raise PermitServiceError(f"העלאת הקובץ החדש נכשלה - המסמך הישן נשאר ללא שינוי: {upload_result['error']}")

    old_snapshot = {
        "file_path": doc.file_path, "file_hash": doc.file_hash,
        "file_name": doc.file_name, "file_size": doc.file_size,
    }
    new_snapshot = {"file_path": upload_result["path"], "file_hash": upload_result["hash"], "file_size": upload_result["size"]}
    alog.log('replace_pending', 'permit', doc.id, entity_label=doc.file_name,
             old_value=old_snapshot, new_value=new_snapshot)

    old_file_path = doc.file_path  # לשימוש למחיקה אחרי commit מוצלח
    doc.file_path = upload_result["path"]
    doc.file_hash = upload_result["hash"]
    doc.file_size = upload_result["size"]

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # ה-DB עדיין מצביע לישן (rollback) - מנקים את הקובץ החדש שהעלינו
        # לחינם, כדי לא להשאיר אותו יתום מההתחלה.
        storage.delete_file(upload_result["path"], upload_folder)
        alog.log('replace_failed', 'permit', doc_id, entity_label=old_snapshot.get('file_name'),
                 new_value={"error": str(e)})
        db.session.commit()
        raise PermitServiceError(f"החלפת המסמך נכשלה (DB) - הקובץ הישן עדיין פעיל, הקובץ החדש נוקה: {e}")

    # מכאן והלאה ה-DB כבר מצביע לקובץ החדש בהצלחה. מוחקים את הישן,
    # best-effort - כשל כאן לא הופך את ה-DB ללא-תקין (הוא כבר מצביע נכון).
    storage_result = {"status": False, "error": "לא היה קובץ ישן למחיקה"}
    if old_file_path:
        storage_result = storage.delete_file(old_file_path, upload_folder)

    if not storage_result["status"]:
        logger.warning(f"Document #{doc_id} הוחלף אך ניקוי הקובץ הישן נכשל: {storage_result['error']}")
        alog.log('replace_orphan_warning', 'permit', doc_id, entity_label=doc.file_name,
                 new_value={"old_file_path": old_file_path, "error": storage_result["error"]})
    else:
        alog.log('replace', 'permit', doc_id, entity_label=doc.file_name, new_value=new_snapshot)
    db.session.commit()

    return doc


def search_permits(q=None, category=None, zone_id=None, status=None, sort=None, include_archived=False):
    query = Document.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            Document.file_name.ilike(like),
            Document.permit_number.ilike(like),
            Document.issuing_body.ilike(like),
            Document.tags.ilike(like),
            Document.notes.ilike(like),
            Document.contact_name.ilike(like),
            Document.category.ilike(like),
        ))
    if category:
        query = query.filter(Document.category == category)
    if zone_id:
        query = query.filter(Document.zone_id == zone_id)
    if status:
        query = query.filter(Document.status == status)
    else:
        excluded = ['deleted'] if include_archived else ['archived', 'deleted']
        query = query.filter(Document.status.notin_(excluded))

    sort_map = {
        'expiry_asc': Document.expiry_date.asc(),
        'expiry_desc': Document.expiry_date.desc(),
        'uploaded_desc': Document.uploaded_at.desc(),
        'uploaded_asc': Document.uploaded_at.asc(),
        'name_asc': Document.file_name.asc(),
    }
    query = query.order_by(sort_map.get(sort, Document.uploaded_at.desc()))
    return query.all()


def list_categories():
    rows = db.session.query(Document.category).filter(Document.category.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def serialize_permit(doc):
    zone = doc.zone
    req = doc.requirement
    deleted_by_user = db.session.get(User, doc.deleted_by) if doc.deleted_by else None
    return {
        "id": doc.id, "req_id": doc.req_id, "zone_id": doc.zone_id,
        "zone_name": zone.zone_name if zone else None,
        "system_name": req.system_name if req else None,
        "file_name": doc.file_name, "file_path": doc.file_path,
        "file_size": doc.file_size,
        "expiry_date": str(doc.expiry_date) if doc.expiry_date else None,
        "issue_date": str(doc.issue_date) if doc.issue_date else None,
        "status": doc.status, "permit_number": doc.permit_number,
        "issuing_body": doc.issuing_body, "contact_name": doc.contact_name,
        "notes": doc.notes, "category": doc.category,
        "tags": [t.strip() for t in doc.tags.split(',')] if doc.tags else [],
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "locked": doc.locked,
        "deleted_at": doc.deleted_at.isoformat() if doc.deleted_at else None,
        "deleted_by": doc.deleted_by,
        "deleted_by_username": deleted_by_user.username if deleted_by_user else None,
    }


def serialize_history(h):
    return {
        "id": h.id, "field_name": h.field_name, "old_value": h.old_value,
        "new_value": h.new_value, "changed_at": h.changed_at.isoformat() if h.changed_at else None,
    }
