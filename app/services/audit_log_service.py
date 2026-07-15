"""
Service Layer עבור Audit Log מערכתי (שלב 12).
מספק פונקציית log() גנרית שכל מודול אחר קורא לה אחרי פעולת כתיבה, וכן
חיפוש/סינון/ייצוא של היומן.
"""
import json

from flask import session, request

from app.extensions import db
from app.models import AuditLog


def log(action, entity_type, entity_id=None, entity_label=None, old_value=None, new_value=None):
    """
    רושם פעולה ביומן. בטוח לקריאה מכל הקשר (גם מחוץ לבקשת HTTP, למשל סקריפט
    רקע) - אם אין הקשר בקשה/session פעיל, פשוט לא ממלא IP/משתמש.
    """
    entry = AuditLog(
        action=action, entity_type=entity_type, entity_id=entity_id, entity_label=entity_label,
        old_value=_to_text(old_value), new_value=_to_text(new_value),
    )
    try:
        entry.user_id = session.get('user_id')
        entry.username_snapshot = session.get('username')
    except RuntimeError:
        pass  # אין הקשר session פעיל (למשל קריאה מסקריפט)
    try:
        entry.ip_address = request.remote_addr
        entry.user_agent = (request.user_agent.string or '')[:255]
    except RuntimeError:
        pass  # אין הקשר בקשה פעיל
    db.session.add(entry)
    # לא מבצעים commit כאן במכוון - נשענים על ה-commit של הפעולה העסקית עצמה
    # שקוראת ל-log(), כדי לשמור אטומיות (אם הפעולה נכשלת, גם הרישום מתבטל)


def _to_text(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def list_logs(entity_type=None, action=None, q=None, entity_id=None, limit=200):
    query = AuditLog.query
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            AuditLog.entity_label.ilike(like),
            AuditLog.username_snapshot.ilike(like),
        ))
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()


def list_entity_types():
    rows = db.session.query(AuditLog.entity_type).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def serialize(entry):
    return {
        "id": entry.id, "user_id": entry.user_id,
        "username": entry.username_snapshot or "אנונימי",
        "action": entry.action, "entity_type": entry.entity_type,
        "entity_id": entry.entity_id, "entity_label": entry.entity_label,
        "old_value": entry.old_value, "new_value": entry.new_value,
        "ip_address": entry.ip_address,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
