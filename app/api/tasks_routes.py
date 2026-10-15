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
            grouped[source_row] = {
                "id": task.id,
                "source_row": source_row,
                "title": task.title,
                "asset": fields.get("נכס רלוונטי", ""),
                "case_number": fields.get("מספר תיק", ""),
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
            }
        else:
            # Keep one visible row per source spreadsheet row; do not delete underlying records.
            grouped[source_row]["duplicate_count"] += 1
            # If the primary row has no owner, retain the owner from a duplicate for visibility.
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
