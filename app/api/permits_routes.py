"""
API עבור הרחבת מודול האישורים (שלב 2).
Blueprint נפרד מ-main_bp הקיים; לא נוגע ב-/api/dashboard או בהעלאת קבצים.
"""
from flask import Blueprint, jsonify, request
from app.services import permit_service as svc
from app.services.permit_service import PermitServiceError

permits_bp = Blueprint('permits', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@permits_bp.errorhandler(PermitServiceError)
def _handle_service_error(err):
    return jsonify({"error": str(err)}), 400


@permits_bp.route('/api/permits', methods=['GET'])
def api_search_permits():
    docs = svc.search_permits(
        q=request.args.get('q'),
        category=request.args.get('category'),
        zone_id=request.args.get('zone_id', type=int),
        status=request.args.get('status'),
        sort=request.args.get('sort'),
        include_archived=request.args.get('include_archived', 'false').lower() == 'true',
    )
    return jsonify([svc.serialize_permit(d) for d in docs])


@permits_bp.route('/api/permits/categories', methods=['GET'])
def api_list_categories():
    return jsonify(svc.list_categories())


@permits_bp.route('/api/permits/<int:doc_id>', methods=['GET'])
def api_get_permit(doc_id):
    doc = svc.get_document_or_404(doc_id)
    return jsonify(svc.serialize_permit(doc))


@permits_bp.route('/api/permits/<int:doc_id>', methods=['PUT'])
def api_update_permit(doc_id):
    doc = svc.update_permit(doc_id, _json_body())
    return jsonify(svc.serialize_permit(doc))


@permits_bp.route('/api/permits/<int:doc_id>', methods=['DELETE'])
def api_delete_permit(doc_id):
    svc.delete_permit(doc_id)
    return jsonify({"success": True})


@permits_bp.route('/api/permits/<int:doc_id>/duplicate', methods=['POST'])
def api_duplicate_permit(doc_id):
    draft = svc.duplicate_permit(doc_id)
    return jsonify(svc.serialize_permit(draft)), 201


@permits_bp.route('/api/permits/<int:doc_id>/lock', methods=['POST'])
def api_lock_permit(doc_id):
    doc = svc.set_locked(doc_id, True)
    return jsonify(svc.serialize_permit(doc))


@permits_bp.route('/api/permits/<int:doc_id>/unlock', methods=['POST'])
def api_unlock_permit(doc_id):
    doc = svc.set_locked(doc_id, False)
    return jsonify(svc.serialize_permit(doc))


@permits_bp.route('/api/permits/<int:doc_id>/history', methods=['GET'])
def api_permit_history(doc_id):
    history = svc.get_history(doc_id)
    return jsonify([svc.serialize_history(h) for h in history])
