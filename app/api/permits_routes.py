"""
API עבור הרחבת מודול האישורים (שלב 2).
Blueprint נפרד מ-main_bp הקיים; לא נוגע ב-/api/dashboard או בהעלאת קבצים.
"""
import secrets
from itsdangerous import URLSafeTimedSerializer
from flask import Blueprint, jsonify, request, session, current_app
from app.services import permit_service as svc
from app.services.permit_service import PermitServiceError
from app.services.auth_service import AuthServiceError
from app.api.auth_routes import admin_required

permits_bp = Blueprint('permits', __name__)
DOCUMENT_TOKEN_SALT = 'campus-fire-document-access-v1'
DOCUMENT_TOKEN_MAX_AGE = 300


def _json_body():
    return request.get_json(silent=True) or {}


def _document_access_token(doc_id):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=DOCUMENT_TOKEN_SALT)
    return serializer.dumps({'doc_id': int(doc_id), 'nonce': secrets.token_urlsafe(12)})


@permits_bp.errorhandler(PermitServiceError)
def _handle_service_error(err):
    return jsonify({"error": str(err)}), 400


@permits_bp.errorhandler(AuthServiceError)
def _handle_auth_error(err):
    return jsonify({"error": str(err)}), 403


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
    payload = svc.serialize_permit(doc)
    if doc.file_path and doc.status != 'deleted':
        token = _document_access_token(doc.id)
        response = jsonify({**payload, 'file_access_url': f"/api/documents/{doc.id}/file?access_token={token}"})
        # Keep the short-lived document token available to the exact document
        # endpoint and its nested navigation paths. This also makes direct
        # window.open() preview/download resilient when the session cookie is
        # unavailable in a newly opened browser tab.
        response.set_cookie(
            f'doc_access_{doc.id}', token,
            max_age=DOCUMENT_TOKEN_MAX_AGE,
            httponly=True,
            secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
            samesite=current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
            path='/api/documents/',
        )
        return response
    return jsonify({**payload, 'file_access_url': None})


@permits_bp.route('/api/permits/<int:doc_id>', methods=['PUT'])
def api_update_permit(doc_id):
    doc = svc.update_permit(doc_id, _json_body())
    return jsonify(svc.serialize_permit(doc))


@permits_bp.route('/api/permits/<int:doc_id>', methods=['DELETE'])
@admin_required
def api_delete_permit(doc_id):
    svc.safe_delete_document(doc_id, session.get('user_id'), current_app.config['UPLOAD_FOLDER'])
    return jsonify({"success": True})


@permits_bp.route('/api/permits/<int:doc_id>/replace', methods=['POST'])
@admin_required
def api_replace_permit(doc_id):
    file_obj = request.files.get('file')
    if not file_obj or not file_obj.filename:
        return jsonify({"error": "לא צורף קובץ"}), 400
    if not file_obj.filename.lower().endswith('.pdf'):
        return jsonify({"error": "ניתן להעלות רק קבצי PDF"}), 400

    file_bytes = file_obj.read()
    doc = svc.safe_replace_document(
        doc_id, session.get('user_id'), file_bytes, file_obj.filename,
        current_app.config['UPLOAD_FOLDER'],
    )
    return jsonify(svc.serialize_permit(doc))


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
