"""
עמוד תיעוד חי (Living Style Guide) עבור ה-Design System (שלב 1 ב-Redesign).
לא נוגע בשום עמוד קיים - זהו מסך תצוגה/אישור בלבד לפני שממשיכים לשלב 2
(Shell מאוחד) ושלב 3 (חיבור בפועל של העמודים הקיימים לקובץ הזה).
"""
from flask import Blueprint, render_template

design_system_bp = Blueprint('design_system', __name__)


@design_system_bp.route('/design-system')
def design_system_page():
    return render_template('design_system.html')


@design_system_bp.route('/settings')
def settings_page():
    return render_template('settings.html', active_nav='settings')


@design_system_bp.route('/admin/storage')
def admin_storage_page():
    return render_template('admin_storage.html', active_nav='settings')
