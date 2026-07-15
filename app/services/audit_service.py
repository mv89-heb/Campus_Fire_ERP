"""
Service Layer עבור מערכת ביקורות (שלב 5).
"""
from datetime import date, datetime

from app.extensions import db
from app.models import Audit, Deficiency, Site, Building, Floor
from app.services import audit_log_service as alog


class AuditServiceError(Exception):
    pass


_DATE_FIELDS = {'audit_date'}

_FIELDS = [
    'audit_number', 'site_id', 'building_id', 'floor_id', 'inspector_name',
    'audit_date', 'status', 'result', 'score', 'notes', 'signature_data',
]


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise AuditServiceError(f"פורמט תאריך לא תקין: {value} (נדרש YYYY-MM-DD)")


def list_audits(site_id=None, status=None, result=None):
    query = Audit.query
    if site_id:
        query = query.filter(Audit.site_id == site_id)
    if status:
        query = query.filter(Audit.status == status)
    if result:
        query = query.filter(Audit.result == result)
    return query.order_by(Audit.audit_date.desc().nullslast()).all()


def get_audit_or_404(audit_id):
    audit = db.session.get(Audit, audit_id)
    if not audit:
        raise AuditServiceError(f"ביקורת {audit_id} לא נמצאה")
    return audit


def create_audit(data):
    audit = Audit()
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(audit, field, value)
    db.session.add(audit)
    db.session.flush()
    alog.log('create', 'audit', audit.id, entity_label=audit.audit_number or f"#{audit.id}", new_value=data)
    db.session.commit()
    return audit


def update_audit(audit_id, data):
    audit = get_audit_or_404(audit_id)
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(audit, field, value)
    alog.log('update', 'audit', audit.id, entity_label=audit.audit_number or f"#{audit.id}",
             new_value={k: v for k, v in data.items() if k != 'signature_data'})
    db.session.commit()
    return audit


def delete_audit(audit_id):
    audit = get_audit_or_404(audit_id)
    alog.log('delete', 'audit', audit.id, entity_label=audit.audit_number or f"#{audit.id}")
    db.session.delete(audit)
    db.session.commit()


def compare_to_previous(audit_id):
    """
    מחזיר את הביקורות הקודמות באותו אתר (לפני תאריך הביקורת הנוכחית),
    לצורך השוואת מגמת הציון לאורך זמן.
    """
    audit = get_audit_or_404(audit_id)
    if not audit.site_id or not audit.audit_date:
        return []
    previous = (Audit.query
                .filter(Audit.site_id == audit.site_id, Audit.id != audit.id)
                .filter(Audit.audit_date.isnot(None), Audit.audit_date <= audit.audit_date)
                .order_by(Audit.audit_date.desc())
                .limit(5).all())
    return previous


def compute_suggested_score(audit_id):
    """
    ציון מוצע בהתבסס על חומרת הליקויים הפתוחים בביקורת (לא מחליף הזנה ידנית).
    100 פחות ניקוד לפי חומרה, לא פחות מ-0.
    """
    weights = {'low': 3, 'medium': 8, 'high': 15, 'critical': 25}
    deficiencies = Deficiency.query.filter_by(audit_id=audit_id).filter(Deficiency.status != 'resolved').all()
    penalty = sum(weights.get(d.severity, 5) for d in deficiencies)
    return max(0, 100 - penalty)


def serialize_audit(audit, include_deficiencies=True):
    site = db.session.get(Site, audit.site_id) if audit.site_id else None
    building = db.session.get(Building, audit.building_id) if audit.building_id else None
    floor = db.session.get(Floor, audit.floor_id) if audit.floor_id else None
    data = {
        "id": audit.id, "audit_number": audit.audit_number, "site_id": audit.site_id,
        "site_name": site.name if site else None,
        "building_id": audit.building_id, "building_name": building.name if building else None,
        "floor_id": audit.floor_id, "floor_name": floor.name if floor else None,
        "inspector_name": audit.inspector_name,
        "audit_date": str(audit.audit_date) if audit.audit_date else None,
        "status": audit.status, "result": audit.result, "score": audit.score,
        "notes": audit.notes, "has_signature": bool(audit.signature_data),
        "deficiency_count": Deficiency.query.filter_by(audit_id=audit.id).count(),
        "open_deficiency_count": Deficiency.query.filter_by(audit_id=audit.id).filter(Deficiency.status != 'resolved').count(),
    }
    if include_deficiencies:
        from app.services.deficiency_service import serialize_deficiency
        data["deficiencies"] = [serialize_deficiency(d) for d in audit.deficiencies]
    return data
