"""
API עבור Storage Health Check ו-Recovery של מסמכים ישנים.
כל ה-endpoints מוגנים ב-admin_required.
"""
from flask import Blueprint, jsonify, request, current_app, session
from app.services import storage_health_service as svc
from app.services import storage_migration_service as migration_svc
from app.services import storage
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


@admin_storage_bp.route('/api/admin/storage/inventory', methods=['GET'])
@admin_required
def api_storage_inventory():
    """Read-only diagnostic of the configured Supabase bucket.

    Never returns credentials or file contents. It exposes object names,
    sizes and a small optional filename search so an administrator can verify
    whether legacy documents actually exist in the bucket.
    """
    if not storage.is_configured():
        return jsonify({
            'configured': False,
            'bucket': storage.get_bucket_name(),
            'error': 'Supabase אינו מוגדר: חסרים SUPABASE_URL / SUPABASE_SERVICE_KEY',
            'objects': [],
        }), 503

    try:
        objects = storage.list_supabase_files()
        query = (request.args.get('q') or '').strip().lower()
        if query:
            objects = [
                item for item in objects
                if query in str(item.get('filename', '')).lower()
                or query in str(item.get('basename', '')).lower()
            ]

        return jsonify({
            'configured': True,
            'bucket': storage.get_bucket_name(),
            'object_count': len(objects),
            'query': query or None,
            'objects': objects,
        })
    except Exception as exc:
        current_app.logger.exception('Supabase inventory check failed')
        return jsonify({
            'configured': True,
            'bucket': storage.get_bucket_name(),
            'object_count': 0,
            'objects': [],
            'error': f'לא ניתן לקרוא את Supabase Storage: {exc}',
        }), 502
