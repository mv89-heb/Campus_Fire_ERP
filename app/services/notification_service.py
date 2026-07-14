"""
Service Layer עבור מערכת תזכורות (שלב 3).
סורק אישורים/משימות/ביקורות/ציוד בעלי תאריך יעד, ומייצר/מעדכן התראה אחת
פר-ישות כשהיא נכנסת לאחד מחלונות הזמן: 90/60/30/14/7/1 ימים (או פג תוקף).
"""
from datetime import date

from app.extensions import db
from app.models import Notification, Document, Task, Audit, Equipment

WINDOWS = [90, 60, 30, 14, 7, 1]


class NotificationServiceError(Exception):
    pass


def _bucket_for(days_left):
    """מחזיר את חלון הזמן המתאים (הקטן ביותר שעדיין >= ימים שנותרו), או None אם רחוק מדי."""
    if days_left is None:
        return None
    if days_left < 0:
        return 0  # פג תוקף / עבר המועד
    applicable = [w for w in WINDOWS if days_left <= w]
    return min(applicable) if applicable else None


def _upsert(ref_type, ref_id, bucket, title, message):
    existing = Notification.query.filter_by(ref_type=ref_type, ref_id=ref_id, dismissed=False).first()
    if existing:
        if existing.window_days != bucket:
            existing.window_days = bucket
            existing.title = title
            existing.message = message
            existing.read_at = None  # התראה נעשתה דחופה יותר - להציג שוב כלא-נקראה
    else:
        db.session.add(Notification(
            ref_type=ref_type, ref_id=ref_id, window_days=bucket, title=title, message=message,
        ))


def scan_and_generate():
    """
    סורק את כל הישויות הרלוונטיות ומייצר/מעדכן התראות בהתאם. אידמפוטנטי -
    ניתן להריץ בכל טעינת עמוד בלי ליצור כפילויות.
    """
    today = date.today()
    count_before = Notification.query.count()

    # אישורים
    for doc in Document.query.filter(Document.expiry_date.isnot(None), Document.status != 'archived').all():
        days_left = (doc.expiry_date - today).days
        bucket = _bucket_for(days_left)
        if bucket is not None:
            label = "פג תוקף" if bucket == 0 else f"פג בעוד {days_left} ימים"
            _upsert('permit', doc.id, bucket, f"אישור עומד לפוג: {doc.file_name}", label)

    # משימות
    for task in Task.query.filter(Task.due_date.isnot(None), Task.status.notin_(['done', 'cancelled'])).all():
        days_left = (task.due_date - today).days
        bucket = _bucket_for(days_left)
        if bucket is not None:
            label = "עבר המועד" if bucket == 0 and days_left < 0 else f"יעד בעוד {days_left} ימים"
            _upsert('task', task.id, bucket, f"משימה מתקרבת ליעד: {task.title}", label)

    # ביקורות מתוכננות
    for audit in Audit.query.filter(Audit.audit_date.isnot(None), Audit.status == 'scheduled').all():
        days_left = (audit.audit_date - today).days
        bucket = _bucket_for(days_left)
        if bucket is not None:
            label = f"מתוכננת בעוד {days_left} ימים" if days_left >= 0 else "המועד עבר"
            _upsert('audit', audit.id, bucket, f"ביקורת מתקרבת: {audit.audit_number or ('#' + str(audit.id))}", label)

    # ציוד - בדיקה הבאה
    for eq in Equipment.query.filter(Equipment.next_check_date.isnot(None)).all():
        days_left = (eq.next_check_date - today).days
        bucket = _bucket_for(days_left)
        if bucket is not None:
            label = "עבר מועד הבדיקה" if days_left < 0 else f"בדיקה בעוד {days_left} ימים"
            _upsert('equipment', eq.id, bucket, f"ציוד דורש בדיקה: {eq.equipment_type}", label)

    db.session.commit()
    return Notification.query.count() - count_before


def list_notifications(unread_only=False, include_dismissed=False):
    query = Notification.query
    if not include_dismissed:
        query = query.filter(Notification.dismissed.is_(False))
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return query.order_by(Notification.window_days.asc(), Notification.updated_at.desc()).all()


def unread_count():
    return Notification.query.filter(Notification.dismissed.is_(False), Notification.read_at.is_(None)).count()


def mark_read(notification_id):
    n = db.session.get(Notification, notification_id)
    if not n:
        raise NotificationServiceError(f"התראה {notification_id} לא נמצאה")
    from datetime import datetime
    n.read_at = datetime.utcnow()
    db.session.commit()
    return n


def mark_all_read():
    from datetime import datetime
    Notification.query.filter(Notification.read_at.is_(None)).update({"read_at": datetime.utcnow()})
    db.session.commit()


def dismiss(notification_id):
    n = db.session.get(Notification, notification_id)
    if not n:
        raise NotificationServiceError(f"התראה {notification_id} לא נמצאה")
    n.dismissed = True
    db.session.commit()
    return n


def serialize_notification(n):
    return {
        "id": n.id, "ref_type": n.ref_type, "ref_id": n.ref_id, "window_days": n.window_days,
        "title": n.title, "message": n.message,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "dismissed": n.dismissed,
    }
