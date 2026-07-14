"""
Service Layer עבור מערכת ליקויים (שלב 6).
"""
from datetime import date, datetime

from app.extensions import db
from app.models import Deficiency, Task
from app.services import audit_log_service as alog


class DeficiencyServiceError(Exception):
    pass


_DATE_FIELDS = {'opened_at', 'due_date'}

_FIELDS = [
    'audit_id', 'title', 'description', 'severity', 'responsible',
    'opened_at', 'due_date', 'status', 'task_id', 'notes',
]


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise DeficiencyServiceError(f"פורמט תאריך לא תקין: {value} (נדרש YYYY-MM-DD)")


def _require(value, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise DeficiencyServiceError(f"שדה חובה חסר: {field_name}")
    return value


def list_deficiencies(audit_id=None, severity=None, status=None):
    query = Deficiency.query
    if audit_id:
        query = query.filter(Deficiency.audit_id == audit_id)
    if severity:
        query = query.filter(Deficiency.severity == severity)
    if status:
        query = query.filter(Deficiency.status == status)
    return query.order_by(Deficiency.due_date.asc().nullslast()).all()


def get_deficiency_or_404(deficiency_id):
    d = db.session.get(Deficiency, deficiency_id)
    if not d:
        raise DeficiencyServiceError(f"ליקוי {deficiency_id} לא נמצא")
    return d


def create_deficiency(data):
    _require(data.get('title'), 'title')
    if not data.get('opened_at'):
        data = dict(data)
        data['opened_at'] = date.today().isoformat()
    d = Deficiency(title=data['title'])
    for field in _FIELDS:
        if field in data and field != 'title':
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(d, field, value)
    db.session.add(d)
    db.session.flush()
    alog.log('create', 'deficiency', d.id, entity_label=d.title, new_value=data)
    db.session.commit()
    return d


def update_deficiency(deficiency_id, data):
    d = get_deficiency_or_404(deficiency_id)
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(d, field, value)
    alog.log('update', 'deficiency', d.id, entity_label=d.title, new_value=data)
    db.session.commit()
    return d


def delete_deficiency(deficiency_id):
    d = get_deficiency_or_404(deficiency_id)
    alog.log('delete', 'deficiency', d.id, entity_label=d.title)
    db.session.delete(d)
    db.session.commit()


def create_task_from_deficiency(deficiency_id):
    """יוצר משימת תיקון מקושרת לליקוי (שלב 6: 'קישור למשימה')."""
    d = get_deficiency_or_404(deficiency_id)
    if d.task_id:
        raise DeficiencyServiceError("לליקוי זה כבר קיימת משימה מקושרת")
    priority_map = {'critical': 'urgent', 'high': 'high', 'medium': 'normal', 'low': 'low'}
    task = Task(
        title=f"תיקון ליקוי: {d.title}",
        description=d.description,
        assignee=d.responsible,
        priority=priority_map.get(d.severity, 'normal'),
        status='open',
        due_date=d.due_date,
    )
    db.session.add(task)
    db.session.flush()  # לקבל task.id לפני ה-commit
    d.task_id = task.id
    alog.log('create', 'task', task.id, entity_label=task.title, new_value={'from_deficiency': d.id})
    db.session.commit()
    return d, task


def serialize_deficiency(d):
    return {
        "id": d.id, "audit_id": d.audit_id, "title": d.title, "description": d.description,
        "severity": d.severity, "responsible": d.responsible,
        "opened_at": str(d.opened_at) if d.opened_at else None,
        "due_date": str(d.due_date) if d.due_date else None,
        "status": d.status, "task_id": d.task_id, "notes": d.notes,
    }
