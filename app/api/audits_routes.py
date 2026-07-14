"""
API עבור מערכת ביקורות (שלב 5) ומערכת ליקויים (שלב 6).
שני המודולים קשורים הדוקות (ליקוי שייך לביקורת) ולכן מרוכזים ב-blueprint אחד.
"""
from flask import Blueprint, jsonify, request, render_template
from app.services import audit_service as audit_svc
from app.services import deficiency_service as def_svc
from app.services.audit_service import AuditServiceError
from app.services.deficiency_service import DeficiencyServiceError

audits_bp = Blueprint('audits', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@audits_bp.errorhandler(AuditServiceError)
def _handle_audit_error(err):
    return jsonify({"error": str(err)}), 400


@audits_bp.errorhandler(DeficiencyServiceError)
def _handle_deficiency_error(err):
    return jsonify({"error": str(err)}), 400


# ---------- Pages ----------

@audits_bp.route('/audits')
def audits_page():
    return render_template('audits.html', active_nav='audits')


@audits_bp.route('/audits/<int:audit_id>/report')
def audit_report_page(audit_id):
    audit = audit_svc.get_audit_or_404(audit_id)
    audit_data = audit_svc.serialize_audit(audit)
    return render_template('audit_report.html', audit=audit_data, signature_data=audit.signature_data)


# ---------- Audits API ----------

@audits_bp.route('/api/audits', methods=['GET'])
def api_list_audits():
    audits = audit_svc.list_audits(
        site_id=request.args.get('site_id', type=int),
        status=request.args.get('status'),
        result=request.args.get('result'),
    )
    return jsonify([audit_svc.serialize_audit(a, include_deficiencies=False) for a in audits])


@audits_bp.route('/api/audits', methods=['POST'])
def api_create_audit():
    audit = audit_svc.create_audit(_json_body())
    return jsonify(audit_svc.serialize_audit(audit)), 201


@audits_bp.route('/api/audits/<int:audit_id>', methods=['GET'])
def api_get_audit(audit_id):
    audit = audit_svc.get_audit_or_404(audit_id)
    return jsonify(audit_svc.serialize_audit(audit))


@audits_bp.route('/api/audits/<int:audit_id>', methods=['PUT'])
def api_update_audit(audit_id):
    audit = audit_svc.update_audit(audit_id, _json_body())
    return jsonify(audit_svc.serialize_audit(audit))


@audits_bp.route('/api/audits/<int:audit_id>', methods=['DELETE'])
def api_delete_audit(audit_id):
    audit_svc.delete_audit(audit_id)
    return jsonify({"success": True})


@audits_bp.route('/api/audits/<int:audit_id>/compare', methods=['GET'])
def api_compare_audit(audit_id):
    previous = audit_svc.compare_to_previous(audit_id)
    return jsonify([audit_svc.serialize_audit(a, include_deficiencies=False) for a in previous])


@audits_bp.route('/api/audits/<int:audit_id>/suggested_score', methods=['GET'])
def api_suggested_score(audit_id):
    return jsonify({"suggested_score": audit_svc.compute_suggested_score(audit_id)})


# ---------- Deficiencies API ----------

@audits_bp.route('/api/deficiencies', methods=['GET'])
def api_list_deficiencies():
    items = def_svc.list_deficiencies(
        audit_id=request.args.get('audit_id', type=int),
        severity=request.args.get('severity'),
        status=request.args.get('status'),
    )
    return jsonify([def_svc.serialize_deficiency(d) for d in items])


@audits_bp.route('/api/deficiencies', methods=['POST'])
def api_create_deficiency():
    d = def_svc.create_deficiency(_json_body())
    return jsonify(def_svc.serialize_deficiency(d)), 201


@audits_bp.route('/api/deficiencies/<int:deficiency_id>', methods=['GET'])
def api_get_deficiency(deficiency_id):
    d = def_svc.get_deficiency_or_404(deficiency_id)
    return jsonify(def_svc.serialize_deficiency(d))


@audits_bp.route('/api/deficiencies/<int:deficiency_id>', methods=['PUT'])
def api_update_deficiency(deficiency_id):
    d = def_svc.update_deficiency(deficiency_id, _json_body())
    return jsonify(def_svc.serialize_deficiency(d))


@audits_bp.route('/api/deficiencies/<int:deficiency_id>', methods=['DELETE'])
def api_delete_deficiency(deficiency_id):
    def_svc.delete_deficiency(deficiency_id)
    return jsonify({"success": True})


@audits_bp.route('/api/deficiencies/<int:deficiency_id>/create_task', methods=['POST'])
def api_create_task_from_deficiency(deficiency_id):
    d, task = def_svc.create_task_from_deficiency(deficiency_id)
    return jsonify({"deficiency": def_svc.serialize_deficiency(d), "task_id": task.id}), 201
