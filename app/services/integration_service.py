"""Central business synchronization for Campus Fire ERP.

This module keeps related ERP entities consistent when a user changes one
part of a workflow. It deliberately contains business rules rather than
presentation logic so every screen/API path shares the same behavior.
"""
from __future__ import annotations

from app.extensions import db
from app.models import Audit, Deficiency, Task


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
