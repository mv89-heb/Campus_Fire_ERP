"""
Service Layer עבור מערכת דוחות (שלב 11).
כל פונקציית report_* מחזירה (headers, rows) - רשימת כותרות עמודות ורשימת
שורות (כל שורה = רשימת ערכים, בסדר תואם לכותרות) - פורמט אחיד שמייצוא
CSV/Excel/הדפסה יכולים לצרוך בלי לדעת על המודל שמאחורי הדוח.
"""
from datetime import date

from app.models import Document, Supplier, Equipment, Deficiency, Audit, Task
from app.services import audit_log_service


class ReportServiceError(Exception):
    pass


def report_expired_permits():
    today = date.today()
    docs = (Document.query
            .filter(Document.expiry_date.isnot(None), Document.expiry_date < today, Document.status != 'archived')
            .order_by(Document.expiry_date.asc()).all())
    headers = ["שם קובץ", "מספר אישור", "גוף מנפיק", "תאריך תפוגה", "ימים מאז הפקיעה"]
    rows = [[d.file_name, d.permit_number or '', d.issuing_body or '', str(d.expiry_date),
             (today - d.expiry_date).days] for d in docs]
    return headers, rows


def report_expiring_permits(days=30):
    today = date.today()
    docs = (Document.query
            .filter(Document.expiry_date.isnot(None), Document.status != 'archived').all())
    filtered = [d for d in docs if 0 <= (d.expiry_date - today).days <= days]
    filtered.sort(key=lambda d: d.expiry_date)
    headers = ["שם קובץ", "מספר אישור", "גוף מנפיק", "תאריך תפוגה", "ימים שנותרו"]
    rows = [[d.file_name, d.permit_number or '', d.issuing_body or '', str(d.expiry_date),
             (d.expiry_date - today).days] for d in filtered]
    return headers, rows


def report_suppliers():
    suppliers = Supplier.query.order_by(Supplier.company_name).all()
    headers = ["שם חברה", "סוג שירות", "איש קשר", "טלפון", "סטטוס", "תוקף חוזה", "תוקף ביטוח", "דירוג"]
    rows = [[s.company_name, s.service_type or '', s.contact_name or '', s.phone or '', s.status,
             str(s.contract_expiry) if s.contract_expiry else '', str(s.insurance_expiry) if s.insurance_expiry else '',
             s.rating or ''] for s in suppliers]
    return headers, rows


def report_equipment():
    items = Equipment.query.order_by(Equipment.equipment_type).all()
    headers = ["סוג ציוד", "מספר סידורי", "יצרן", "דגם", "סטטוס", "בדיקה הבאה"]
    rows = [[e.equipment_type, e.serial_number or '', e.manufacturer or '', e.model or '', e.status,
             str(e.next_check_date) if e.next_check_date else ''] for e in items]
    return headers, rows


def report_deficiencies():
    items = Deficiency.query.order_by(Deficiency.severity.desc()).all()
    headers = ["כותרת", "חומרה", "אחראי", "יעד לתיקון", "סטטוס"]
    rows = [[d.title, d.severity, d.responsible or '', str(d.due_date) if d.due_date else '', d.status]
            for d in items]
    return headers, rows


def report_audits():
    items = Audit.query.order_by(Audit.audit_date.desc().nullslast()).all()
    headers = ["מספר ביקורת", "תאריך", "בודק", "סטטוס", "תוצאה", "ציון"]
    rows = [[a.audit_number or f"#{a.id}", str(a.audit_date) if a.audit_date else '', a.inspector_name or '',
             a.status, a.result or '', a.score if a.score is not None else ''] for a in items]
    return headers, rows


def report_tasks():
    items = Task.query.order_by(Task.due_date.asc().nullslast()).all()
    headers = ["כותרת", "שיוך", "עדיפות", "סטטוס", "יעד"]
    rows = [[t.title, t.assignee or '', t.priority, t.status, str(t.due_date) if t.due_date else '']
            for t in items]
    return headers, rows


def report_user_activity():
    entries = audit_log_service.list_logs(limit=500)
    headers = ["זמן", "משתמש", "פעולה", "סוג ישות", "ישות"]
    rows = [[e.created_at.strftime('%Y-%m-%d %H:%M') if e.created_at else '', e.username_snapshot or 'אנונימי',
             e.action, e.entity_type, e.entity_label or ''] for e in entries]
    return headers, rows


REPORTS = {
    'expired_permits': {"label": "אישורים שפגו", "func": report_expired_permits},
    'expiring_permits': {"label": "אישורים קרובים לפקיעה", "func": report_expiring_permits},
    'suppliers': {"label": "ספקים", "func": report_suppliers},
    'equipment': {"label": "ציוד", "func": report_equipment},
    'deficiencies': {"label": "ליקויים", "func": report_deficiencies},
    'audits': {"label": "ביקורות", "func": report_audits},
    'tasks': {"label": "משימות", "func": report_tasks},
    'user_activity': {"label": "פעילות משתמשים", "func": report_user_activity},
}


def get_report(report_key):
    if report_key not in REPORTS:
        raise ReportServiceError(f"סוג דוח לא מוכר: {report_key}")
    headers, rows = REPORTS[report_key]["func"]()
    return {"key": report_key, "label": REPORTS[report_key]["label"], "headers": headers, "rows": rows}


def list_report_types():
    return [{"key": k, "label": v["label"]} for k, v in REPORTS.items()]
