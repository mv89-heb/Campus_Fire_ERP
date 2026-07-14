"""
API עבור צפייה ב-Audit Log מערכתי (שלב 12).
"""
from flask import Blueprint, jsonify, request, render_template
from app.services import audit_log_service as svc

audit_log_bp = Blueprint('audit_log', __name__)


@audit_log_bp.route('/audit-log')
def audit_log_page():
    return render_template('audit_log.html', active_nav='settings')


@audit_log_bp.route('/api/audit-log', methods=['GET'])
def api_list_audit_log():
    entries = svc.list_logs(
        entity_type=request.args.get('entity_type'),
        action=request.args.get('action'),
        q=request.args.get('q'),
        entity_id=request.args.get('entity_id', type=int),
        limit=request.args.get('limit', 200, type=int),
    )
    return jsonify([svc.serialize(e) for e in entries])


@audit_log_bp.route('/api/audit-log/entity_types', methods=['GET'])
def api_entity_types():
    return jsonify(svc.list_entity_types())
