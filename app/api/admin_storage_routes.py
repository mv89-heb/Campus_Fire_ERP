"""
API עבור Storage Health Check (Commit 6, Document Storage Management).
כל ה-endpoints מוגנים ב-admin_required. הזרימה: Scan/Report -> Preview
Cleanup -> Approve -> Delete. אין מחיקה אוטומטית - cleanup-confirm הוא
ה-endpoint היחיד שבאמת מוחק, ורק לרשימת נתיבים מפורשת שהתקבלה מהלקוח
(כלומר: אושרה ע"י אדם אחרי שראה את ה-Preview).
"""
from flask import Blueprint, jsonify, request, current_app, session
from app.services import storage_health_service as svc
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
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/scan', methods=['GET'])
@admin_required
def api_scan():
    result = svc.scan(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/report', methods=['GET'])
@admin_required
def api_report():
    # בשלב זה זהה ל-scan (סריקה טרייה) - אין עדיין שכבת cache נפרדת.
    # שם ה-endpoint נשמר תואם לתכנון המקורי, למקרה שתתווסף בעתיד.
    result = svc.scan(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


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
