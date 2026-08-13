"""Authentication, sessions and user administration."""
import secrets
from functools import wraps

from flask import Blueprint, jsonify, request, session, render_template

from app.extensions import db
from app.models import User
from app.services import auth_service as svc
from app.services.auth_service import AuthServiceError

auth_bp = Blueprint('auth', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@auth_bp.errorhandler(AuthServiceError)
def _handle_error(err):
    return jsonify({'error': str(err)}), 400


def _current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if not user or not user.active:
        session.clear()
        return None
    return user


def _ensure_csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if not user:
            return jsonify({'error': 'נדרשת התחברות'}), 401
        return view_func(*args, **kwargs)
    return wrapped


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if not user:
            return jsonify({'error': 'נדרשת התחברות'}), 401
        if user.role not in ('admin', 'super_admin'):
            return jsonify({'error': 'הפעולה דורשת הרשאת מנהל (Admin)'}), 403
        return view_func(*args, **kwargs)
    return wrapped


# ---------- Pages ----------

@auth_bp.route('/login')
def login_page():
    return render_template('login.html')


@auth_bp.route('/users')
@admin_required
def users_page():
    return render_template('users.html', active_nav='settings')


# ---------- Auth API ----------

@auth_bp.route('/api/auth/login', methods=['POST'])
def api_login():
    data = _json_body()
    user = svc.authenticate(data.get('username'), data.get('password'))

    # Rotate the Flask session on successful authentication to reduce session-fixation risk.
    session.clear()
    session.permanent = True
    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role
    session['csrf_token'] = secrets.token_urlsafe(32)

    response = svc.serialize_user(user)
    response['csrf_token'] = session['csrf_token']
    return jsonify(response)


@auth_bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})


@auth_bp.route('/api/auth/me', methods=['GET'])
def api_me():
    user = _current_user()
    if not user:
        return jsonify(None)
    response = svc.serialize_user(user)
    response['csrf_token'] = _ensure_csrf_token()
    return jsonify(response)


@auth_bp.route('/api/auth/bootstrap_status', methods=['GET'])
def api_bootstrap_status():
    return jsonify({'has_users': svc.has_any_users()})


# ---------- Users management API ----------

@auth_bp.route('/api/users', methods=['GET'])
@admin_required
def api_list_users():
    return jsonify([svc.serialize_user(u) for u in svc.list_users()])


@auth_bp.route('/api/users', methods=['POST'])
def api_create_user():
    # The global security guard permits this endpoint only for first-time bootstrap.
    # Once an account exists, user creation requires an admin/super-admin session.
    current = _current_user()
    if svc.has_any_users() and (not current or current.role not in ('admin', 'super_admin')):
        return jsonify({'error': 'יצירת משתמש דורשת הרשאת מנהל'}), 403

    data = _json_body()
    if not svc.has_any_users():
        data['role'] = 'super_admin'
        data['active'] = True

    user = svc.create_user(data)
    return jsonify(svc.serialize_user(user)), 201


@auth_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@admin_required
def api_update_user(user_id):
    current = _current_user()
    if current.id == user_id and _json_body().get('active') is False:
        return jsonify({'error': 'לא ניתן להשבית את המשתמש המחובר'}), 400
    user = svc.update_user(user_id, _json_body())
    return jsonify(svc.serialize_user(user))


@auth_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_delete_user(user_id):
    current = _current_user()
    if current.id == user_id:
        return jsonify({'error': 'לא ניתן למחוק את המשתמש המחובר'}), 400
    svc.delete_user(user_id)
    return jsonify({'success': True})
