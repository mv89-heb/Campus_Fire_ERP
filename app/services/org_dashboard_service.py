"""
Service Layer עבור הדשבורד הארגוני.
מדדי אישורים מחושבים לפי expiry_date אמיתי; מסמך ללא תאריך תוקף אמין
אינו נחשב תקין אלא מסומן לבדיקה.
"""
import time
from datetime import date, timedelta
from collections import Counter

from app.models import Document, Supplier, Task, Audit, Deficiency, Equipment, Zone
from app.services.document_analysis_service import validity_status

_CACHE = {"data": None, "expires_at": 0}
_CACHE_TTL_SECONDS = 30


def _permit_kpis():
    today = date.today()
    docs = Document.query.filter(Document.status.notin_(['archived', 'deleted'])).all()
    valid = expired = warning_30 = needs_review = 0
    by_month = Counter()
    by_status = Counter()
    upcoming = []
    for d in docs:
        status = validity_status(d.expiry_date, today)
        if status == 'expired':
            expired += 1
        elif status == 'critical':
            warning_30 += 1
        elif status == 'warning':
            warning_30 += 1
        elif status == 'needs_review':
            needs_review += 1
        else:
            valid += 1

        by_status[status] += 1
        if d.expiry_date:
            month_key = d.expiry_date.strftime('%Y-%m')
            by_month[month_key] += 1
            days_left = (d.expiry_date - today).days
            if 0 <= days_left <= 60:
                upcoming.append({
                    "id": d.id,
                    "file_name": d.file_name,
                    "permit_number": d.permit_number,
                    "expiry_date": str(d.expiry_date),
                    "days_left": days_left,
                    "status": status,
                })
    upcoming.sort(key=lambda x: x['days_left'])
    return {
        "active_count": valid,
        "expired_count": expired,
        "warning_30_count": warning_30,
        "needs_review_count": needs_review,
        "by_month": dict(sorted(by_month.items())[-6:]),
        "by_status": dict(by_status),
        "upcoming_expirations": upcoming[:10],
    }


def _task_kpis():
    tasks = Task.query.all()
    by_status = Counter(t.status for t in tasks)
    urgent = [t for t in tasks if t.status != 'done' and t.priority in ('urgent', 'high')]
    urgent.sort(key=lambda t: (t.due_date is None, t.due_date or date.max))
    return {
        "open_count": by_status.get('open', 0) + by_status.get('in_progress', 0),
        "by_status": dict(by_status),
        "urgent_tasks": [
            {"id": t.id, "title": t.title, "priority": t.priority, "due_date": str(t.due_date) if t.due_date else None}
            for t in urgent[:10]
        ],
    }


def _audit_kpis():
    today = date.today()
    week_end = today + timedelta(days=7)
    audits = Audit.query.all()
    upcoming = [a for a in audits if a.audit_date and today <= a.audit_date <= week_end]
    upcoming.sort(key=lambda a: a.audit_date)
    return {
        "total_count": len(audits),
        "scheduled_count": sum(1 for a in audits if a.status == 'scheduled'),
        "this_week": [
            {"id": a.id, "audit_number": a.audit_number, "site_id": a.site_id, "audit_date": str(a.audit_date)}
            for a in upcoming
        ],
    }


def _deficiency_kpis():
    deficiencies = Deficiency.query.all()
    open_defs = [d for d in deficiencies if d.status != 'resolved']
    by_severity = Counter(d.severity for d in open_defs)
    return {"open_count": len(open_defs), "by_severity": dict(by_severity)}


def _equipment_kpis():
    equipment = Equipment.query.all()
    faulty = [e for e in equipment if e.status == 'faulty']
    return {
        "total_count": len(equipment),
        "faulty_count": len(faulty),
        "faulty_items": [
            {"id": e.id, "equipment_type": e.equipment_type, "serial_number": e.serial_number}
            for e in faulty[:10]
        ],
    }


def _supplier_kpis():
    suppliers = Supplier.query.all()
    return {"total_count": len(suppliers), "active_count": sum(1 for s in suppliers if s.status == 'active')}


def get_org_dashboard(force_refresh=False):
    now = time.time()
    if not force_refresh and _CACHE["data"] is not None and _CACHE["expires_at"] > now:
        return _CACHE["data"]
    data = _compute_org_dashboard()
    _CACHE["data"] = data
    _CACHE["expires_at"] = now + _CACHE_TTL_SECONDS
    return data


def _compute_org_dashboard():
    permits = _permit_kpis()
    tasks = _task_kpis()
    audits = _audit_kpis()
    deficiencies = _deficiency_kpis()
    equipment = _equipment_kpis()
    suppliers = _supplier_kpis()

    readiness_inputs = []
    total_permits = (
        permits['active_count'] + permits['expired_count'] +
        permits['warning_30_count'] + permits['needs_review_count']
    )
    if total_permits:
        readiness_inputs.append(permits['active_count'] / total_permits * 100)
    if equipment['total_count']:
        readiness_inputs.append((equipment['total_count'] - equipment['faulty_count']) / equipment['total_count'] * 100)
    readiness_score = round(sum(readiness_inputs) / len(readiness_inputs), 1) if readiness_inputs else None

    return {
        "readiness_score": readiness_score,
        "zone_count": Zone.query.count(),
        "permits": permits,
        "tasks": tasks,
        "audits": audits,
        "deficiencies": deficiencies,
        "equipment": equipment,
        "suppliers": suppliers,
    }
