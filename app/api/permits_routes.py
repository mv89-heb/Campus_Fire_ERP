"""
API עבור הרחבת מודול האישורים (שלב 2).
Blueprint נפרד מ-main_bp הקיים; לא נוגע ב-/api/dashboard או בהעלאת קבצים.
"""
import os
import secrets
from itsdangerous import URLSafeTimedSerializer
from flask import Blueprint, jsonify, request, session, current_app, redirect
from app.services import permit_service as svc
from app.services.permit_service import PermitServiceError
from app.services.auth_service import AuthServiceError
from app.api.auth_routes import admin_required
from app.services import storage

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


@permits_bp.route('/api/permits/<int:doc_id>/preview', methods=['GET'])
def api_preview_permit(doc_id):
    """Open a document through an authenticated same-origin redirect."""
    if not session.get('user_id'):
        return jsonify({"error": "נדרשת התחברות"}), 401

    doc = svc.get_document_or_404(doc_id)
    if not doc.file_path or doc.status in ('deleted', 'draft'):
        return jsonify({"error": "למסמך אין קובץ זמין לצפייה"}), 404

    token = _document_access_token(doc.id)
    return redirect(f"/api/documents/{doc.id}/file?access_token={token}", code=302)


@permits_bp.route('/api/admin/storage/health/documents', methods=['GET'])
@admin_required
def api_storage_health_documents():
    """Admin-only runtime check: resolve and actually download stored PDFs.

    This intentionally verifies bytes, not just signed-URL creation, so it can
    distinguish a DB path mismatch from a missing/corrupt object in Storage.
    """
    raw_ids = request.args.get('ids', '').strip()
    ids = []
    if raw_ids:
        for value in raw_ids.split(','):
            value = value.strip()
            if value.isdigit():
                ids.append(int(value))
    if not ids:
        ids = [doc.id for doc in svc.Document.query.order_by(svc.Document.id.asc()).limit(50).all()]

    inventory = storage.list_supabase_files()
    results = []
    bucket = storage.get_bucket_name()
    client = None

    for doc_id in ids:
        try:
            doc = svc.get_document_or_404(doc_id)
            result = {
                'id': doc.id,
                'file_name': doc.file_name,
                'db_file_path': doc.file_path,
                'status': doc.status,
                'storage_exists': False,
                'storage_location': None,
                'resolved_path': None,
                'download_ok': False,
                'bytes': None,
                'sha256': None,
                'pdf_valid': False,
                'error': None,
            }

            if not doc.file_path:
                result['error'] = 'file_path ריק'
                results.append(result)
                continue

            resolved = doc.file_path if storage.is_supabase_path(doc.file_path) else storage.find_supabase_legacy_path(doc.file_path, inventory)
            if resolved:
                remote_path = resolved[len(bucket) + 1:] if resolved.startswith(f'{bucket}/') else resolved
                result['storage_location'] = 'supabase' if storage.is_supabase_path(doc.file_path) else 'supabase_legacy'
                result['resolved_path'] = resolved
                if client is None:
                    client = storage._get_client()
                data = client.storage.from_(bucket).download(remote_path)
                if data:
                    result['storage_exists'] = True
                    result['download_ok'] = True
                    result['bytes'] = len(data)
                    result['sha256'] = storage.calculate_hash(data)
                    validation = storage.verify_pdf_bytes(data)
                    result['pdf_valid'] = validation['status']
                    if not validation['status']:
                        result['error'] = validation['error']
                else:
                    result['error'] = 'Supabase download returned empty data'
            else:
                local_path = os.path.abspath(os.path.join(current_app.config['UPLOAD_FOLDER'], os.path.basename(doc.file_path)))
                root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
                if os.path.isfile(local_path) and os.path.commonpath([local_path, root]) == root:
                    result['storage_location'] = 'local'
                    result['resolved_path'] = local_path
                    with open(local_path, 'rb') as fh:
                        data = fh.read()
                    result['storage_exists'] = True
                    result['download_ok'] = True
                    result['bytes'] = len(data)
                    result['sha256'] = storage.calculate_hash(data)
                    validation = storage.verify_pdf_bytes(data)
                    result['pdf_valid'] = validation['status']
                    if not validation['status']:
                        result['error'] = validation['error']
                else:
                    result['error'] = 'לא נמצא לא ב-Supabase ולא מקומית'
        except Exception as exc:
            result['error'] = str(exc)
        results.append(result)

    return jsonify({
        'bucket': bucket,
        'checked': len(results),
        'results': results,
    })


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
