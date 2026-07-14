"""
Service Layer עבור מערכת משימות (שלב 7).
"""
import json
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import Task
from app.services import audit_log_service as alog


class TaskServiceError(Exception):
    pass


_DATE_FIELDS = {'due_date'}

_FIELDS = [
    'title', 'description', 'assignee', 'priority', 'status', 'due_date',
    'is_recurring', 'recurrence_rule', 'site_id', 'supplier_id',
]

_RECURRENCE_DAYS = {'daily': 1, 'weekly': 7, 'monthly': 30, 'quarterly': 91, 'yearly': 365}


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise TaskServiceError(f"פורמט תאריך לא תקין: {value} (נדרש YYYY-MM-DD)")


def _require(value, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise TaskServiceError(f"שדה חובה חסר: {field_name}")
    return value


def list_tasks(q=None, status=None, priority=None, assignee=None, site_id=None):
    query = Task.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            Task.title.ilike(like), Task.description.ilike(like), Task.assignee.ilike(like),
        ))
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)
    if assignee:
        query = query.filter(Task.assignee == assignee)
    if site_id:
        query = query.filter(Task.site_id == site_id)
    return query.order_by(Task.status.asc(), Task.due_date.asc().nullslast()).all()


def get_task_or_404(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        raise TaskServiceError(f"משימה {task_id} לא נמצאה")
    return task


def _validate_checklist(checklist):
    if checklist is None:
        return None
    if not isinstance(checklist, list):
        raise TaskServiceError("צ'קליסט חייב להיות רשימה")
    cleaned = []
    for item in checklist:
        if isinstance(item, str):
            cleaned.append({"text": item, "done": False})
        elif isinstance(item, dict) and 'text' in item:
            cleaned.append({"text": item['text'], "done": bool(item.get('done', False))})
        else:
            raise TaskServiceError("פריט צ'קליסט לא תקין")
    return cleaned


def create_task(data):
    _require(data.get('title'), 'title')
    task = Task(title=data['title'])
    for field in _FIELDS:
        if field in data and field != 'title':
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(task, field, value)
    if 'checklist' in data:
        task.checklist_json = json.dumps(_validate_checklist(data['checklist']), ensure_ascii=False)
    db.session.add(task)
    db.session.flush()
    alog.log('create', 'task', task.id, entity_label=task.title, new_value=data)
    db.session.commit()
    return task


def update_task(task_id, data):
    task = get_task_or_404(task_id)
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(task, field, value)
    if 'checklist' in data:
        task.checklist_json = json.dumps(_validate_checklist(data['checklist']), ensure_ascii=False)
    alog.log('update', 'task', task.id, entity_label=task.title, new_value=data)
    db.session.commit()
    return task


def delete_task(task_id):
    task = get_task_or_404(task_id)
    alog.log('delete', 'task', task.id, entity_label=task.title)
    db.session.delete(task)
    db.session.commit()


def complete_task(task_id):
    """
    מסמן משימה כהושלמה. אם היא משימה חוזרת, יוצרת אוטומטית את המופע הבא
    בהתאם לכלל החזרה (יומי/שבועי/חודשי/רבעוני/שנתי).
    """
    task = get_task_or_404(task_id)
    task.status = 'done'
    task.completed_at = datetime.utcnow()
    alog.log('update', 'task', task.id, entity_label=task.title, new_value={'status': 'done'})

    next_task = None
    if task.is_recurring and task.recurrence_rule in _RECURRENCE_DAYS:
        base_date = task.due_date or date.today()
        next_due = base_date + timedelta(days=_RECURRENCE_DAYS[task.recurrence_rule])
        next_task = Task(
            title=task.title, description=task.description, assignee=task.assignee,
            priority=task.priority, status='open', due_date=next_due,
            is_recurring=True, recurrence_rule=task.recurrence_rule,
            checklist_json=task.checklist_json, site_id=task.site_id, supplier_id=task.supplier_id,
        )
        db.session.add(next_task)

    db.session.commit()
    return task, next_task


def list_assignees():
    rows = db.session.query(Task.assignee).filter(Task.assignee.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def serialize_task(task):
    checklist = json.loads(task.checklist_json) if task.checklist_json else []
    return {
        "id": task.id, "title": task.title, "description": task.description, "assignee": task.assignee,
        "priority": task.priority, "status": task.status,
        "due_date": str(task.due_date) if task.due_date else None,
        "is_recurring": task.is_recurring, "recurrence_rule": task.recurrence_rule,
        "checklist": checklist, "site_id": task.site_id, "supplier_id": task.supplier_id,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }
