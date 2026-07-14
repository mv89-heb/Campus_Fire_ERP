"""
API עבור מערכת תזכורות (שלב 3).
"""
from flask import Blueprint, jsonify, request
from app.services import notification_service as svc
from app.services.notification_service import NotificationServiceError

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.errorhandler(NotificationServiceError)
def _handle_error(err):
    return jsonify({"error": str(err)}), 400


@notifications_bp.route('/api/notifications', methods=['GET'])
def api_list_notifications():
    svc.scan_and_generate()  # אידמפוטנטי - מרענן לפני החזרת הרשימה
    items = svc.list_notifications(
        unread_only=request.args.get('unread_only', 'false').lower() == 'true',
    )
    return jsonify({
        "unread_count": svc.unread_count(),
        "items": [svc.serialize_notification(n) for n in items],
    })


@notifications_bp.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
def api_mark_read(notification_id):
    n = svc.mark_read(notification_id)
    return jsonify(svc.serialize_notification(n))


@notifications_bp.route('/api/notifications/mark_all_read', methods=['POST'])
def api_mark_all_read():
    svc.mark_all_read()
    return jsonify({"success": True})


@notifications_bp.route('/api/notifications/<int:notification_id>/dismiss', methods=['POST'])
def api_dismiss(notification_id):
    n = svc.dismiss(notification_id)
    return jsonify(svc.serialize_notification(n))
