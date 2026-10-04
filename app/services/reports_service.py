"""
Service Layer עבור מערכת דוחות (שלב 11).
כל פונקציית report_* מחזירה (headers, rows) - רשימת כותרות עמודות ורשימת
שורות (כל שורה = רשימת ערכים, בסדר תואם לכותרות) - פורמט אחיד שמייצוא
CSV/Excel/הדפסה יכולים לצרוך בלי לדעת על המודל שמאחורי הדוח.
"""
from datetime import date

from app.models import Document, Supplier, Equipment, Deficiency, Audit, Task, Site
from app.extensions import db
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
    headers = ["סוג ציוד", "מספר סידורי", "יצרן", "דגם", "אתר", "סטטוס", "בדיקה הבאה"]
    rows = []
    for e in items:
        site_name = ''
        if e.area_id:
            from app.models import Area, Floor, Building
            area = db.session.get(Area, e.area_id)
            floor = db.session.get(Floor, area.floor_id) if area else None
            building = db.session.get(Building, floor.building_id) if floor else None
            site = db.session.get(Site, building.site_id) if building else None
            site_name = site.name if site else ''
        rows.append([e.equipment_type, e.serial_number or '', e.manufacturer or '', e.model or '',
                     site_name, e.status, str(e.next_check_date) if e.next_check_date else ''])
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
    headers = ["כותרת", "שיוך", "עדיפות", "סטטוס", "יעד", "אתר"]
    rows = []
    for t in items:
        site = db.session.get(Site, t.site_id) if t.site_id else None
        rows.append([t.title, t.assignee or '', t.priority, t.status,
                     str(t.due_date) if t.due_date else '', site.name if site else ''])
    return headers, rows


def report_documents():
    items = Document.query.filter(Document.status.notin_(['archived', 'deleted'])).order_by(Document.uploaded_at.desc()).all()
    headers = ["מסמך", "קטגוריה", "אתר", "ביקורת", "ספק", "AI", "בדיקה נדרשת", "תפוגה"]
    rows = []
    for d in items:
        site = db.session.get(Site, d.site_id) if d.site_id else None
        audit = db.session.get(Audit, d.audit_id) if d.audit_id else None
        supplier = db.session.get(Supplier, d.supplier_id) if d.supplier_id else None
        rows.append([d.file_name, d.category or '', site.name if site else '',
                     audit.audit_number if audit else '', supplier.company_name if supplier else '',
                     d.ai_status, 'כן' if d.analysis_review_required else 'לא',
                     str(d.expiry_date) if d.expiry_date else ''])
    return headers, rows


def report_ai_findings():
    items = Document.query.filter(Document.ai_findings_json.isnot(None)).order_by(Document.ai_analyzed_at.desc()).all()
    headers = ["מסמך", "אתר", "AI", "ביטחון", "בדיקה", "סיכום"]
    rows = []
    for d in items:
        site = db.session.get(Site, d.site_id) if d.site_id else None
        rows.append([d.file_name, site.name if site else '', d.ai_status,
                     round(d.ai_confidence * 100) if d.ai_confidence is not None else '',
                     'כן' if d.analysis_review_required else 'לא', d.ai_summary or ''])
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
    'documents': {"label": "מסמכים וקשרי AI", "func": report_documents},
    'ai_findings': {"label": "ממצאי Gemini", "func": report_ai_findings},
}


def get_report(report_key):
    if report_key not in REPORTS:
        raise ReportServiceError(f"סוג דוח לא מוכר: {report_key}")
    headers, rows = REPORTS[report_key]["func"]()
    return {"key": report_key, "label": REPORTS[report_key]["label"], "headers": headers, "rows": rows}


def list_report_types():
    return [{"key": k, "label": v["label"]} for k, v in REPORTS.items()]


def _json_object(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


def get_ai_full_reports():
    """Return complete, human-readable Gemini reports for every completed document."""
    documents = (
        Document.query
        .filter(Document.ai_status == 'completed')
        .filter(Document.status.notin_(['archived', 'deleted']))
        .order_by(Document.ai_analyzed_at.desc().nullslast(), Document.uploaded_at.desc())
        .all()
    )
    reports = []
    for d in documents:
        site = db.session.get(Site, d.site_id) if d.site_id else None
        audit = db.session.get(Audit, d.audit_id) if d.audit_id else None
        supplier = db.session.get(Supplier, d.supplier_id) if d.supplier_id else None
        findings = _json_object(d.ai_findings_json, [])
        actions = _json_object(d.ai_actions_json, {})
        deficiencies = (
            Deficiency.query
            .filter(Deficiency.notes.ilike(f"%document:{d.id}%"))
            .order_by(Deficiency.severity.desc(), Deficiency.id.asc())
            .all()
        )
        operational = []
        for deficiency in deficiencies:
            task = db.session.get(Task, deficiency.task_id) if deficiency.task_id else None
            operational.append({
                "deficiency_id": deficiency.id,
                "title": deficiency.title,
                "severity": deficiency.severity,
                "description": deficiency.description or "",
                "responsible": deficiency.responsible or "",
                "due_date": str(deficiency.due_date) if deficiency.due_date else None,
                "status": deficiency.status,
                "task_id": task.id if task else None,
                "task_title": task.title if task else None,
                "task_status": task.status if task else None,
                "task_due_date": str(task.due_date) if task and task.due_date else None,
            })
        reports.append({
            "document_id": d.id,
            "file_name": d.file_name,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "analyzed_at": d.ai_analyzed_at.isoformat() if d.ai_analyzed_at else None,
            "ai_model": d.ai_model,
            "document_type": d.ai_document_type,
            "category": d.category,
            "site": site.name if site else actions.get("site_name"),
            "site_address": site.address if site else actions.get("site_address"),
            "audit_number": audit.audit_number if audit else actions.get("audit_number"),
            "audit_date": str(audit.audit_date) if audit and audit.audit_date else actions.get("audit_date"),
            "inspector_name": audit.inspector_name if audit else actions.get("inspector_name"),
            "supplier": supplier.company_name if supplier else actions.get("supplier_name"),
            "supplier_number": supplier.supplier_number if supplier else actions.get("supplier_number"),
            "issue_date": str(d.issue_date) if d.issue_date else None,
            "expiry_date": str(d.expiry_date) if d.expiry_date else None,
            "analysis_expiry_date": str(d.analysis_expiry_date) if d.analysis_expiry_date else None,
            "validity_status": d.analysis_validity_status,
            "validity_source": d.analysis_validity_source,
            "validity_rule": d.analysis_validity_rule_label or d.analysis_validity_rule,
            "validity_evidence": d.analysis_validity_rule_evidence,
            "analysis_confidence": d.analysis_confidence,
            "ai_confidence": d.ai_confidence,
            "review_required": bool(d.analysis_review_required),
            "summary": d.ai_summary or "",
            "findings": findings,
            "missing_items": actions.get("missing_items", []),
            "contradictions": actions.get("contradictions", []),
            "follow_up_questions": actions.get("follow_up_questions", []),
            "operational_actions": operational,
        })
    return reports
