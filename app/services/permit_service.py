"""
Service Layer עבור הרחבת מודול האישורים (שלב 2) ומודול מסמכים (שלב 9).
מטפל בעריכת מטא-דאטה של אישור קיים (Document), שכפול אישור לצורך חידוש,
חיפוש/סינון/מיון, נעילה מפני עריכה, וארכוב, עם תיעוד היסטוריית שינויים.
"""
import uuid
from datetime import date, datetime

from app.extensions import db
from app.models import Document, Zone, SystemRequirement, DocumentHistory
from app.services import audit_log_service as alog


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


def delete_permit(doc_id):
    doc = get_document_or_404(doc_id)
    _ensure_unlocked(doc)
    alog.log('delete', 'permit', doc.id, entity_label=doc.file_name)
    db.session.delete(doc)
    db.session.commit()


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
    elif not include_archived:
        query = query.filter(Document.status != 'archived')

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
    return {
        "id": doc.id, "req_id": doc.req_id, "zone_id": doc.zone_id,
        "zone_name": zone.zone_name if zone else None,
        "system_name": req.system_name if req else None,
        "file_name": doc.file_name, "file_path": doc.file_path,
        "expiry_date": str(doc.expiry_date) if doc.expiry_date else None,
        "issue_date": str(doc.issue_date) if doc.issue_date else None,
        "status": doc.status, "permit_number": doc.permit_number,
        "issuing_body": doc.issuing_body, "contact_name": doc.contact_name,
        "notes": doc.notes, "category": doc.category,
        "tags": [t.strip() for t in doc.tags.split(',')] if doc.tags else [],
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "locked": doc.locked,
    }


def serialize_history(h):
    return {
        "id": h.id, "field_name": h.field_name, "old_value": h.old_value,
        "new_value": h.new_value, "changed_at": h.changed_at.isoformat() if h.changed_at else None,
    }
