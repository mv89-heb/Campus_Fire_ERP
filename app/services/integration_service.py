"""Central business synchronization for Campus Fire ERP.

This module keeps related ERP entities consistent when a user changes one
part of a workflow. It deliberately contains business rules rather than
presentation logic so every screen/API path shares the same behavior.
"""
from __future__ import annotations

from app.extensions import db
from app.models import Audit, Deficiency, Task, Site, Equipment, Supplier, Document, Building, Floor, Area


def sync_deficiency_task(deficiency: Deficiency) -> Task | None:
    """Synchronize the task linked to a deficiency, if one exists."""
    if not deficiency.task_id:
        return None

    task = db.session.get(Task, deficiency.task_id)
    if not task:
        deficiency.task_id = None
        return None

    task.description = deficiency.description
    task.assignee = deficiency.responsible
    task.due_date = deficiency.due_date

    priority_map = {
        "critical": "urgent",
        "high": "high",
        "medium": "normal",
        "low": "low",
    }
    if deficiency.severity in priority_map:
        task.priority = priority_map[deficiency.severity]

    if deficiency.status == "resolved":
        task.status = "done"
    elif task.status == "done":
        task.status = "open"

    return task


def sync_audit_derived_state(audit_id: int | None) -> None:
    """Refresh derived audit values from its current deficiencies.

    We do not overwrite a user's explicit audit result. The suggested score
    remains a derived value and is exposed by the audit API.
    """
    if not audit_id:
        return
    audit = db.session.get(Audit, audit_id)
    if not audit:
        return

    deficiencies = Deficiency.query.filter_by(audit_id=audit.id).all()
    open_items = [d for d in deficiencies if d.status != "resolved"]

    if audit.status == "completed" and open_items:
        # A completed audit with unresolved findings should remain visible as
        # requiring follow-up. Do not change the stored result.
        if audit.result in (None, "", "passed", "ok"):
            audit.result = "needs_attention"


def sync_after_deficiency_change(deficiency: Deficiency) -> None:
    """Synchronize everything downstream of a deficiency mutation."""
    sync_deficiency_task(deficiency)
    sync_audit_derived_state(deficiency.audit_id)


def sync_audit_change(audit: Audit) -> list[Deficiency]:
    """Propagate audit context changes to its deficiencies and linked tasks."""
    deficiencies = Deficiency.query.filter_by(audit_id=audit.id).all()
    for deficiency in deficiencies:
        if deficiency.task_id:
            task = db.session.get(Task, deficiency.task_id)
            if task:
                task.site_id = audit.site_id
        sync_audit_derived_state(audit.id)
    return deficiencies


def create_task_for_deficiency(deficiency: Deficiency) -> Task:
    """Create the canonical repair task for a deficiency."""
    if deficiency.task_id:
        existing = db.session.get(Task, deficiency.task_id)
        if existing:
            sync_deficiency_task(deficiency)
            return existing

    priority_map = {
        "critical": "urgent",
        "high": "high",
        "medium": "normal",
        "low": "low",
    }

    site_id = None
    if deficiency.audit_id:
        audit = db.session.get(Audit, deficiency.audit_id)
        site_id = audit.site_id if audit else None

    task = Task(
        title=f"\u05ea\u05d9\u05e7\u05d5\u05df \u05dc\u05d9\u05e7\u05d5\u05d9: {deficiency.title}",
        description=deficiency.description,
        assignee=deficiency.responsible,
        priority=priority_map.get(deficiency.severity, "normal"),
        status="open",
        due_date=deficiency.due_date,
        site_id=site_id,
    )
    db.session.add(task)
    db.session.flush()
    deficiency.task_id = task.id
    return task


def _severity_from_priority(priority: str | None) -> str | None:
    return {
        "urgent": "critical",
        "high": "high",
        "normal": "medium",
        "low": "low",
    }.get(priority)


def sync_task_change(task: Task) -> list[Deficiency]:
    """Propagate editable task fields back to deficiencies linked to the task."""
    deficiencies = Deficiency.query.filter_by(task_id=task.id).all()
    severity = _severity_from_priority(task.priority)
    for deficiency in deficiencies:
        if task.description is not None:
            deficiency.description = task.description
        deficiency.responsible = task.assignee
        deficiency.due_date = task.due_date
        if severity:
            deficiency.severity = severity
        if task.status == "done":
            deficiency.status = "resolved"
        elif deficiency.status == "resolved":
            deficiency.status = "open"
        sync_audit_derived_state(deficiency.audit_id)
    return deficiencies


def sync_task_completion(task: Task) -> list[Deficiency]:
    """Backward-compatible wrapper for task completion synchronization."""
    return sync_task_change(task)


def _document_summary(document: Document) -> dict:
    return {
        "id": document.id,
        "file_name": document.file_name,
        "category": document.category,
        "status": document.status,
        "expiry_date": document.expiry_date.isoformat() if document.expiry_date else None,
        "ai_status": document.ai_status,
        "ai_summary": document.ai_summary,
        "site_id": document.site_id,
        "audit_id": document.audit_id,
        "supplier_id": document.supplier_id,
    }


def site_context(site_id: int) -> dict:
    """Return the complete operational context for one site."""
    site = db.session.get(Site, site_id)
    if not site:
        raise ValueError("האתר לא נמצא")

    buildings = Building.query.filter_by(site_id=site_id).all()
    building_ids = [b.id for b in buildings]
    floors = Floor.query.filter(Floor.building_id.in_(building_ids)).all() if building_ids else []
    floor_ids = [f.id for f in floors]
    areas = Area.query.filter(Area.floor_id.in_(floor_ids)).all() if floor_ids else []

    audits = Audit.query.filter_by(site_id=site_id).order_by(Audit.audit_date.desc().nullslast(), Audit.id.desc()).all()
    audit_ids = [a.id for a in audits]
    deficiencies = (
        Deficiency.query.filter(Deficiency.audit_id.in_(audit_ids))
        .order_by(Deficiency.due_date.asc().nullslast(), Deficiency.id.desc()).all()
        if audit_ids else []
    )
    tasks = Task.query.filter_by(site_id=site_id).order_by(Task.due_date.asc().nullslast(), Task.id.desc()).all()
    area_ids = [a.id for a in areas]
    equipment = (
        Equipment.query.filter(Equipment.area_id.in_(area_ids)).order_by(Equipment.next_check_date.asc().nullslast()).all()
        if area_ids else []
    )
    suppliers = Supplier.query.filter_by(site_id=site_id).order_by(Supplier.company_name.asc()).all()

    supplier_ids = [s.id for s in suppliers]
    document_filters = [Document.site_id == site_id]
    if audit_ids:
        document_filters.append(Document.audit_id.in_(audit_ids))
    if supplier_ids:
        document_filters.append(Document.supplier_id.in_(supplier_ids))
    documents = Document.query.filter(
        db.or_(*document_filters),
        Document.status.notin_(["deleted", "archived"]),
    ).order_by(Document.uploaded_at.desc()).all()

    return {
        "site": {
            "id": site.id, "name": site.name, "address": site.address,
            "contact_name": site.contact_name, "contact_phone": site.contact_phone,
            "contact_email": site.contact_email, "notes": site.notes,
        },
        "buildings": [{"id": b.id, "name": b.name} for b in buildings],
        "floors": [{"id": f.id, "name": f.name, "building_id": f.building_id} for f in floors],
        "areas": [{"id": a.id, "name": a.name, "floor_id": a.floor_id} for a in areas],
        "audits": [{
            "id": a.id, "audit_number": a.audit_number,
            "audit_date": a.audit_date.isoformat() if a.audit_date else None,
            "status": a.status, "result": a.result, "score": a.score,
            "open_deficiency_count": sum(1 for d in a.deficiencies if d.status != "resolved"),
        } for a in audits],
        "deficiencies": [{
            "id": d.id, "audit_id": d.audit_id, "title": d.title, "severity": d.severity,
            "status": d.status, "responsible": d.responsible,
            "due_date": d.due_date.isoformat() if d.due_date else None, "task_id": d.task_id,
        } for d in deficiencies],
        "tasks": [{
            "id": t.id, "title": t.title, "status": t.status, "priority": t.priority,
            "assignee": t.assignee, "due_date": t.due_date.isoformat() if t.due_date else None,
            "supplier_id": t.supplier_id,
        } for t in tasks],
        "equipment": [{
            "id": e.id, "equipment_type": e.equipment_type, "serial_number": e.serial_number,
            "status": e.status, "next_check_date": e.next_check_date.isoformat() if e.next_check_date else None,
            "supplier_id": e.supplier_id, "area_id": e.area_id,
        } for e in equipment],
        "suppliers": [{
            "id": s.id, "company_name": s.company_name, "service_type": s.service_type,
            "phone": s.phone, "email": s.email, "status": s.status,
        } for s in suppliers],
        "documents": [_document_summary(d) for d in documents],
        "counts": {
            "buildings": len(buildings), "floors": len(floors), "areas": len(areas),
            "audits": len(audits), "deficiencies": len(deficiencies),
            "open_deficiencies": sum(1 for d in deficiencies if d.status != "resolved"),
            "tasks": len(tasks), "open_tasks": sum(1 for t in tasks if t.status not in {"done", "cancelled"}),
            "equipment": len(equipment), "suppliers": len(suppliers), "documents": len(documents),
        },
    }


def audit_context(audit_id: int) -> dict:
    """Return the complete operational context for one audit."""
    audit = db.session.get(Audit, audit_id)
    if not audit:
        raise ValueError("הביקורת לא נמצאה")
    site = db.session.get(Site, audit.site_id) if audit.site_id else None
    deficiencies = Deficiency.query.filter_by(audit_id=audit.id).order_by(Deficiency.due_date.asc().nullslast()).all()
    task_ids = [d.task_id for d in deficiencies if d.task_id]
    tasks = Task.query.filter(Task.id.in_(task_ids)).all() if task_ids else []
    document_filters = [Document.audit_id == audit.id]
    if audit.site_id:
        document_filters.append(Document.site_id == audit.site_id)
    documents = Document.query.filter(
        db.or_(*document_filters),
        Document.status.notin_(["deleted", "archived"]),
    ).order_by(Document.uploaded_at.desc()).all()
    return {
        "audit": {
            "id": audit.id, "audit_number": audit.audit_number, "site_id": audit.site_id,
            "site_name": site.name if site else None, "building_id": audit.building_id,
            "floor_id": audit.floor_id, "inspector_name": audit.inspector_name,
            "audit_date": audit.audit_date.isoformat() if audit.audit_date else None,
            "status": audit.status, "result": audit.result, "score": audit.score,
        },
        "deficiencies": [{
            "id": d.id, "title": d.title, "description": d.description, "severity": d.severity,
            "status": d.status, "responsible": d.responsible,
            "due_date": d.due_date.isoformat() if d.due_date else None, "task_id": d.task_id,
        } for d in deficiencies],
        "tasks": [{
            "id": t.id, "title": t.title, "status": t.status, "priority": t.priority,
            "assignee": t.assignee, "due_date": t.due_date.isoformat() if t.due_date else None,
        } for t in tasks],
        "documents": [_document_summary(d) for d in documents],
    }
