"""
API עבור מערכת משימות (שלב 7).
"""
from flask import Blueprint, jsonify, request, render_template
from app.services import task_service as svc
from app.services.task_service import TaskServiceError

tasks_bp = Blueprint('tasks', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@tasks_bp.errorhandler(TaskServiceError)
def _handle_service_error(err):
    return jsonify({"error": str(err)}), 400


@tasks_bp.route('/tasks')
def tasks_page():
    return render_template('tasks.html', active_nav='tasks')


@tasks_bp.route('/api/tasks/import-fire-safety-tracking', methods=['POST'])
def api_import_fire_safety_tracking():
    # Uses the same existing Task model/table; importer is idempotent and never deletes data.
    from scripts.import_fire_safety_tracking_table import import_rows
    result = import_rows(dry_run=False)
    return jsonify({"success": True, "result": result})


@tasks_bp.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    tasks = svc.list_tasks(
        q=request.args.get('q'),
        status=request.args.get('status'),
        priority=request.args.get('priority'),
        assignee=request.args.get('assignee'),
        site_id=request.args.get('site_id', type=int),
    )
    return jsonify([svc.serialize_task(t) for t in tasks])


@tasks_bp.route('/api/tasks/fire-safety-tracking', methods=['GET'])
def api_fire_safety_tracking():
    """Spreadsheet-style view of imported workbook rows, deduplicated by source row."""
    import re
    from app.models import Task

    source_marker = "ייבוא טבלת מעקב כבאות והצלה"
    tasks = Task.query.filter(Task.description.ilike(f"%{source_marker}%")).order_by(Task.id.asc()).all()
    # Reuse the persisted Gemini analyses; do not generate new AI output here.
    try:
        from app.services.reports_service import get_ai_full_reports
        ai_reports = get_ai_full_reports()
    except Exception:
        ai_reports = []

    def norm(value):
        return " ".join(str(value or "").casefold().split()).strip(" .,'\"׳״")

    grouped = {}
    for task in tasks:
        desc = task.description or ""
        row_match = re.search(r"שורה מקורית:\s*(\d+)", desc)
        if not row_match:
            continue
        source_row = int(row_match.group(1))
        fields = {}
        for line in desc.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        if source_row not in grouped:
            asset = fields.get("נכס רלוונטי", "")
            case_number = fields.get("מספר תיק", "")
            asset_key, case_key = norm(asset), norm(case_number)
            matched_reports = []
            for report in ai_reports:
                site_key = norm(report.get("site"))
                audit_key = norm(report.get("audit_number"))
                # Prefer exact case/audit matches. Site matches must be exact or a meaningful full-name containment.
                case_match = bool(case_key and audit_key and case_key == audit_key)
                site_match = bool(asset_key and site_key and (
                    asset_key == site_key or
                    (len(asset_key) >= 8 and asset_key in site_key) or
                    (len(site_key) >= 8 and site_key in asset_key)
                ))
                if case_match or site_match:
                    matched_reports.append(report)
            grouped[source_row] = {
                "id": task.id,
                "source_row": source_row,
                "title": task.title,
                "asset": asset,
                "case_number": case_number,
                "forms": fields.get("מספר טופס להגשה", ""),
                "phase": fields.get("שלב / שבוע", ""),
                "notes": fields.get("הערות ודגשים", ""),
                "source": fields.get("ייבוא טבלת מעקב כבאות והצלה", ""),
                "assignee": task.assignee or "",
                "status": task.status,
                "priority": task.priority,
                "due_date": str(task.due_date) if task.due_date else None,
                "description": desc,
                "duplicate_count": 0,
                "ai_reports": [{
                    "document_id": r.get("document_id"),
                    "file_name": r.get("file_name"),
                    "document_type": r.get("document_type"),
                    "document_purpose": r.get("document_purpose"),
                    "analyzed_at": r.get("analyzed_at"),
                    "ai_model": r.get("ai_model"),
                    "overall_status": r.get("overall_status"),
                    "ai_confidence_percent": r.get("ai_confidence_percent"),
                    "review_required": r.get("review_required"),
                    "summary": r.get("summary"),
                    "findings": r.get("findings") or [],
                    "missing_items": r.get("missing_items") or [],
                    "contradictions": r.get("contradictions") or [],
                    "follow_up_questions": r.get("follow_up_questions") or [],
                    "operational_actions": r.get("operational_actions") or [],
                    "validity_status": r.get("validity_status"),
                    "validity_evidence": r.get("validity_evidence"),
                    "site": r.get("site"),
                    "audit_number": r.get("audit_number"),
                } for r in matched_reports],
            }
        else:
            grouped[source_row]["duplicate_count"] += 1
            if not grouped[source_row]["assignee"] and task.assignee:
                grouped[source_row]["assignee"] = task.assignee
    return jsonify(sorted(grouped.values(), key=lambda item: (item["asset"], item["source_row"])))


@tasks_bp.route('/api/tasks/assignees', methods=['GET'])
def api_list_assignees():
    return jsonify(svc.list_assignees())


@tasks_bp.route('/api/tasks', methods=['POST'])
def api_create_task():
    task = svc.create_task(_json_body())
    return jsonify(svc.serialize_task(task)), 201


@tasks_bp.route('/api/tasks/<int:task_id>', methods=['GET'])
def api_get_task(task_id):
    task = svc.get_task_or_404(task_id)
    return jsonify(svc.serialize_task(task))


@tasks_bp.route('/api/tasks/<int:task_id>', methods=['PUT'])
def api_update_task(task_id):
    task = svc.update_task(task_id, _json_body())
    return jsonify(svc.serialize_task(task))


@tasks_bp.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    svc.delete_task(task_id)
    return jsonify({"success": True})


@tasks_bp.route('/api/tasks/<int:task_id>/complete', methods=['POST'])
def api_complete_task(task_id):
    task, next_task = svc.complete_task(task_id)
    return jsonify({
        "task": svc.serialize_task(task),
        "next_task": svc.serialize_task(next_task) if next_task else None,
    })
