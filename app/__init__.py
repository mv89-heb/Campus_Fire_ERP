import hmac
import os
from urllib.parse import urlparse

from flask import Flask, jsonify, request, session

from .extensions import db, migrate, limiter
from .config import Config
from .services.permissions import can_write


PUBLIC_EXACT_PATHS = {
    '/login',
    '/api/auth/login',
    '/api/auth/me',
    '/api/auth/bootstrap_status',
    '/api/system/health',
}
PUBLIC_PREFIXES = ('/static/',)
WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


def _same_origin_allowed(app) -> bool:
    """Reject cross-origin browser writes while allowing non-browser API clients."""
    if request.method not in WRITE_METHODS:
        return True

    fetch_site = request.headers.get('Sec-Fetch-Site')
    if fetch_site == 'cross-site':
        return False

    origin = request.headers.get('Origin')
    if not origin:
        return True

    parsed = urlparse(origin)
    origin_value = f'{parsed.scheme}://{parsed.netloc}'.rstrip('/')
    trusted = set(app.config.get('TRUSTED_ORIGINS', ()))
    trusted.add(request.host_url.rstrip('/'))
    return origin_value in trusted


def _csrf_valid() -> bool:
    expected = session.get('csrf_token')
    supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    return bool(expected and supplied and hmac.compare_digest(str(expected), str(supplied)))


def _is_bootstrap_user_creation() -> bool:
    if request.path != '/api/users' or request.method != 'POST':
        return False
    from app.models import User
    return db.session.query(User.id).first() is None


def _install_security_guards(app):
    @app.before_request
    def security_guard():
        path = request.path

        if path in PUBLIC_EXACT_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            if request.method in WRITE_METHODS and not _same_origin_allowed(app):
                return jsonify({'error': 'Cross-origin request blocked'}), 403
            return None

        if path == '/api/auth/logout':
            if not _same_origin_allowed(app):
                return jsonify({'error': 'Cross-origin request blocked'}), 403
            if session.get('user_id') and not _csrf_valid():
                return jsonify({'error': 'CSRF token חסר או לא תקין'}), 403
            return None

        if _is_bootstrap_user_creation():
            if not _same_origin_allowed(app):
                return jsonify({'error': 'Cross-origin request blocked'}), 403
            return None

        if not session.get('user_id'):
            return jsonify({'error': 'נדרשת התחברות'}), 401

        from app.models import User
        user = db.session.get(User, session.get('user_id'))
        if not user or not user.active:
            session.clear()
            return jsonify({'error': 'החשבון אינו פעיל או אינו קיים'}), 401

        session['username'] = user.username
        session['role'] = user.role

        if request.method in WRITE_METHODS:
            if not _csrf_valid():
                return jsonify({'error': 'CSRF token חסר או לא תקין'}), 403
            if not can_write(user.role, path):
                return jsonify({'error': 'אין הרשאה לבצע פעולה זו עבור התפקיד הנוכחי'}), 403

        if not _same_origin_allowed(app):
            return jsonify({'error': 'Cross-origin request blocked'}), 403

        return None


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.validate()

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except Exception as e:
        app.logger.warning(f'Could not create upload folder: {e}')

    from app.models import (
        Zone, SystemRequirement, Document,
        Site, Building, Floor, Area,
        Supplier, Equipment, Task, Audit, Deficiency,
        DocumentHistory, User, Notification, AuditLog,
    )

    with app.app_context():
        auto_create_db = app.config.get('AUTO_CREATE_DB', not app.config.get('IS_PRODUCTION', False))
        if auto_create_db:
            try:
                db.create_all()
                seed_data()
            except Exception as e:
                app.logger.error(
                    f'Database initialization failed; DB operations may fail: {e}'
                )

    from .api.routes import main_bp
    app.register_blueprint(main_bp)
    from .api.sites_routes import sites_bp
    app.register_blueprint(sites_bp)
    from .api.permits_routes import permits_bp
    app.register_blueprint(permits_bp)
    from .api.suppliers_routes import suppliers_bp
    app.register_blueprint(suppliers_bp)
    from .api.equipment_routes import equipment_bp
    app.register_blueprint(equipment_bp)
    from .api.tasks_routes import tasks_bp
    app.register_blueprint(tasks_bp)
    from .api.audits_routes import audits_bp
    app.register_blueprint(audits_bp)
    from .api.org_dashboard_routes import org_dashboard_bp
    app.register_blueprint(org_dashboard_bp)
    from .api.auth_routes import auth_bp
    app.register_blueprint(auth_bp)
    from .api.notifications_routes import notifications_bp
    app.register_blueprint(notifications_bp)
    from .api.audit_log_routes import audit_log_bp
    app.register_blueprint(audit_log_bp)
    from .api.reports_routes import reports_bp
    app.register_blueprint(reports_bp)
    from .api.search_routes import search_bp
    app.register_blueprint(search_bp)
    from .api.design_system_routes import design_system_bp
    app.register_blueprint(design_system_bp)
    from .api.admin_storage_routes import admin_storage_bp
    app.register_blueprint(admin_storage_bp)

    return app


def seed_data():
    from .models import Zone, SystemRequirement
    try:
        if not Zone.query.first():
            zones_data = [
                ('תשתיות כלליות', 'ראשי'), ('מגורים (פנימייה)', '8855-7'),
                ('מטבח וחדר אוכל', '8859-7'), ('אולם ספורט', '8853-7'),
                ('בית מדרש', '8860-7')
            ]
            zones = []
            for name, fn in zones_data:
                z = Zone(zone_name=name, file_number=fn)
                db.session.add(z)
                zones.append(z)
            db.session.commit()

            reqs = [
                (zones[1].id, 'ציוד כיבוי', 'טופס 1'),
                (zones[1].id, 'תחזוקת מטפים', 'טופס 2'),
                (zones[1].id, 'חשמל', 'טופס 3'),
                (zones[1].id, 'גילוי אש', 'טופס 4'),
                (zones[1].id, 'לוחות חשמל', 'טופס 5'),
                (zones[1].id, 'כריזה', 'טופס 6'),
                (zones[1].id, 'ספרינקלרים', 'טופס 7'),
                (zones[1].id, 'תיק שטח', 'טופס 13'),
                (zones[1].id, 'הדרכת עובדים', 'טופס 14'),
                (zones[2].id, 'מערכת גז', 'טופס 18'),
                (zones[3].id, 'שחרור עשן', 'טופס 10'),
                (zones[4].id, 'גילוי אש', 'טופס 4')
            ]
            for zid, sname, form in reqs:
                db.session.add(SystemRequirement(zone_id=zid, system_name=sname, required_form=form))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Seeding skipped or failed: {e}')
