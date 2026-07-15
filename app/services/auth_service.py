"""
Service Layer עבור תשתית משתמשים ואימות.
Session-based auth פשוט (ללא JWT/OAuth) בהתאם לאופי האפליקציה הקיימת.
"""
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db
from app.models import User
from app.services import audit_log_service as alog
from datetime import datetime

VALID_ROLES = ['super_admin', 'admin', 'manager', 'inspector', 'technician', 'viewer']


class AuthServiceError(Exception):
    pass


def _require(value, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AuthServiceError(f"שדה חובה חסר: {field_name}")
    return value


def require_role(user_id, allowed_roles):
    """
    Helper הרשאות ברמת ה-Service (Commit 1 - Permissions Foundation).
    לא בשימוש עדיין באף שירות קיים - מוכן לשימוש בשירותים מסוכנים חדשים
    (מחיקה/ניקוי אחסון) בהמשך.

    מקבל user_id מפורש (לא קורא ל-session בעצמו) כדי שהפונקציה תישאר
    טהורה וניתנת לבדיקה גם מחוץ להקשר Flask request - קריאת session
    נשארת אחריות שכבת ה-route, בדיוק כמו login_required/admin_required.

    מעלה AuthServiceError (עם קוד 400 אצל הקורא, כמו שאר השירות) אם
    המשתמש לא קיים, לא פעיל, או שהתפקיד שלו אינו ברשימת allowed_roles.
    מחזיר את אובייקט ה-User בהצלחה, לשימוש נוסף (למשל deleted_by=user.id).
    """
    if not user_id:
        raise AuthServiceError("נדרשת התחברות לביצוע פעולה זו")
    user = db.session.get(User, user_id)
    if not user:
        raise AuthServiceError("המשתמש לא נמצא")
    if not user.active:
        raise AuthServiceError("חשבון המשתמש אינו פעיל")
    if user.role not in allowed_roles:
        raise AuthServiceError(f"הפעולה דורשת אחד מהתפקידים: {', '.join(allowed_roles)}")
    return user


def list_users():
    return User.query.order_by(User.username).all()


def get_user_or_404(user_id):
    user = db.session.get(User, user_id)
    if not user:
        raise AuthServiceError(f"משתמש {user_id} לא נמצא")
    return user


def create_user(data):
    username = _require(data.get('username'), 'username')
    password = _require(data.get('password'), 'password')
    if User.query.filter_by(username=username).first():
        raise AuthServiceError("שם המשתמש כבר קיים במערכת")
    role = data.get('role', 'viewer')
    if role not in VALID_ROLES:
        raise AuthServiceError(f"תפקיד לא תקין: {role}")
    user = User(
        username=username,
        email=data.get('email'),
        full_name=data.get('full_name'),
        role=role,
        password_hash=generate_password_hash(password),
        active=data.get('active', True),
    )
    db.session.add(user)
    db.session.flush()
    alog.log('create', 'user', user.id, entity_label=user.username, new_value={'role': role})
    db.session.commit()
    return user


def update_user(user_id, data):
    user = get_user_or_404(user_id)
    if 'email' in data:
        user.email = data['email']
    if 'full_name' in data:
        user.full_name = data['full_name']
    if 'role' in data:
        if data['role'] not in VALID_ROLES:
            raise AuthServiceError(f"תפקיד לא תקין: {data['role']}")
        user.role = data['role']
    if 'active' in data:
        user.active = bool(data['active'])
    if data.get('password'):
        user.password_hash = generate_password_hash(data['password'])
    changed = {k: v for k, v in data.items() if k != 'password'}
    alog.log('update', 'user', user.id, entity_label=user.username, new_value=changed)
    db.session.commit()
    return user


def delete_user(user_id):
    user = get_user_or_404(user_id)
    alog.log('delete', 'user', user.id, entity_label=user.username)
    db.session.delete(user)
    db.session.commit()


def authenticate(username, password):
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password or ''):
        raise AuthServiceError("שם משתמש או סיסמה שגויים")
    if not user.active:
        raise AuthServiceError("חשבון המשתמש אינו פעיל")
    user.last_login = datetime.utcnow()
    db.session.commit()
    return user


def has_any_users():
    return db.session.query(User.id).first() is not None


def serialize_user(user, include_sensitive=False):
    data = {
        "id": user.id, "username": user.username, "email": user.email,
        "full_name": user.full_name, "role": user.role, "active": user.active,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }
    return data
