"""
API עבור Storage Health Check ו-Recovery של מסמכים ישנים.
כל ה-endpoints מוגנים ב-admin_required.
"""
from flask import Blueprint, jsonify, request, current_app, session
from app.services import storage_health_service as svc
from app.services import storage_migration_service as migration_svc
from app.services.auth_service import AuthServiceError
from app.api.auth_routes import admin_required

admin_storage_bp = Blueprint('admin_storage', __name__)


@admin_storage_bp.errorhandler(AuthServiceError)
def _handle_auth_error(err):
    return jsonify({"error": str(err)}), 403


@admin_storage_bp.route('/api/admin/storage/dashboard', methods=['GET'])
@admin_required
def api_dashboard():
    result = svc.dashboard_summary(current_app.config['UPLOAD_FOLDER'])
    result['migration'] = migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/scan', methods=['GET'])
@admin_required
def api_scan():
    result = svc.scan(current_app.config['UPLOAD_FOLDER'])
    result['migration'] = migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/report', methods=['GET'])
@admin_required
def api_report():
    result = svc.scan(current_app.config['UPLOAD_FOLDER'])
    result['migration'] = migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/migration-scan', methods=['GET'])
@admin_required
def api_migration_scan():
    return jsonify(migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER']))


@admin_storage_bp.route('/api/admin/storage/migration-run', methods=['POST'])
@admin_required
def api_migration_run():
    result = migration_svc.migrate(current_app.config['UPLOAD_FOLDER'], session.get('user_id'))
    return jsonify(result), (200 if result.get('success') else 409)


@admin_storage_bp.route('/api/admin/storage/cleanup-preview', methods=['POST'])
@admin_required
def api_cleanup_preview():
    orphans = svc.cleanup_preview(current_app.config['UPLOAD_FOLDER'])
    return jsonify({"orphaned_items": orphans, "count": len(orphans)})


@admin_storage_bp.route('/api/admin/storage/cleanup-confirm', methods=['POST'])
@admin_required
def api_cleanup_confirm():
    body = request.get_json(silent=True) or {}
    paths = body.get('paths')
    if not paths or not isinstance(paths, list):
        return jsonify({"error": "יש לספק רשימת paths לא ריקה (מה שהוצג ב-Preview)"}), 400

    result = svc.cleanup_confirm(paths, session.get('user_id'), current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)
