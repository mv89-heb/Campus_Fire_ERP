"""
API עבור תשתית אימות (login/logout/session) וניהול משתמשים.
חשוב: אף route קיים אינו מוגן ב-login_required/admin_required בשלב זה.
זו תשתית מוכנה (Commit 1 - Permissions Foundation) שתופעל במפורש בהמשך
על endpoints מסוכנים ספציפיים (למשל מחיקת/ניקוי אחסון) - לא באופן גורף.
"""
from functools import wraps

from flask import Blueprint, jsonify, request, session, render_template
from app.services import auth_service as svc
from app.services.auth_service import AuthServiceError

auth_bp = Blueprint('auth', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@auth_bp.errorhandler(AuthServiceError)
def _handle_error(err):
    return jsonify({"error": str(err)}), 400


def login_required(view_func):
    """
    Decorator מוכן לשימוש עתידי. לא מיושם על אף route קיים כרגע בכוונה
    (ראו הערה למעלה) - זמין למי שירצה להגן ידנית על route חדש.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({"error": "נדרשת התחברות"}), 401
        return view_func(*args, **kwargs)
    return wrapped


def admin_required(view_func):
    """
    Decorator להגנת route ברמת Admin. Commit 1 (Permissions Foundation) -
    מוגדר כאן אך *לא* מיושם על אף route קיים. ייושם במפורש בהמשך (Commit 4
    ואילך) על endpoints מסוכנים חדשים (מחיקה/ניקוי אחסון) בלבד.

    401 אם אין session פעיל בכלל, 403 אם יש session אך התפקיד אינו
    admin/super_admin. משתמש ב-session['role'] הקיים (נקבע ב-api_login),
    לא בודק שוב מול ה-DB בכל בקשה - עקבי עם login_required.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({"error": "נדרשת התחברות"}), 401
        if session.get('role') not in ('admin', 'super_admin'):
            return jsonify({"error": "הפעולה דורשת הרשאת מנהל (Admin)"}), 403
        return view_func(*args, **kwargs)
    return wrapped


# ---------- Pages ----------

@auth_bp.route('/login')
def login_page():
    return render_template('login.html')


@auth_bp.route('/users')
def users_page():
    return render_template('users.html', active_nav='settings')


# ---------- Auth API ----------

@auth_bp.route('/api/auth/login', methods=['POST'])
def api_login():
    data = _json_body()
    user = svc.authenticate(data.get('username'), data.get('password'))
    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role
    return jsonify(svc.serialize_user(user))


@auth_bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({"success": True})


@auth_bp.route('/api/auth/me', methods=['GET'])
def api_me():
    if not session.get('user_id'):
        return jsonify(None)
    user = svc.get_user_or_404(session['user_id'])
    return jsonify(svc.serialize_user(user))


@auth_bp.route('/api/auth/bootstrap_status', methods=['GET'])
def api_bootstrap_status():
    """מאפשר לממשק לדעת אם זו הפעלה ראשונה (אין עדיין אף משתמש במערכת)."""
    return jsonify({"has_users": svc.has_any_users()})


# ---------- Users management API ----------

@auth_bp.route('/api/users', methods=['GET'])
def api_list_users():
    return jsonify([svc.serialize_user(u) for u in svc.list_users()])


@auth_bp.route('/api/users', methods=['POST'])
def api_create_user():
    user = svc.create_user(_json_body())
    return jsonify(svc.serialize_user(user)), 201


@auth_bp.route('/api/users/<int:user_id>', methods=['PUT'])
def api_update_user(user_id):
    user = svc.update_user(user_id, _json_body())
    return jsonify(svc.serialize_user(user))


@auth_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
def api_delete_user(user_id):
    svc.delete_user(user_id)
    return jsonify({"success": True})
