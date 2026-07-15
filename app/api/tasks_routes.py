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
