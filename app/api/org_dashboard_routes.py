"""
API עבור הדשבורד הארגוני (שלב 1). Blueprint נפרד; אינו נוגע ב-main_bp.
"""
from flask import Blueprint, jsonify, render_template
import time
from app.services import org_dashboard_service as svc
from app.services import data_integrity_service as integrity_svc

org_dashboard_bp = Blueprint('org_dashboard', __name__)
_INTEGRITY_CACHE = {'data': None, 'expires_at': 0}
_INTEGRITY_CACHE_TTL = 60


@org_dashboard_bp.route('/org-dashboard')
def org_dashboard_page():
    return render_template('org_dashboard.html', active_nav='dashboard')


@org_dashboard_bp.route('/api/org-dashboard', methods=['GET'])
def api_org_dashboard():
    from flask import request
    force = request.args.get('refresh', 'false').lower() == 'true'
    return jsonify(svc.get_org_dashboard(force_refresh=force))


@org_dashboard_bp.route('/api/data-integrity', methods=['GET'])
def api_data_integrity():
    now = time.time()
    if _INTEGRITY_CACHE['data'] is None or _INTEGRITY_CACHE['expires_at'] <= now:
        _INTEGRITY_CACHE['data'] = integrity_svc.scan()
        _INTEGRITY_CACHE['expires_at'] = now + _INTEGRITY_CACHE_TTL
    return jsonify(_INTEGRITY_CACHE['data'])


@org_dashboard_bp.route('/api/data-integrity/repair', methods=['POST'])
def api_data_integrity_repair():
    result = integrity_svc.repair()
    _INTEGRITY_CACHE['data'] = result.get('after')
    _INTEGRITY_CACHE['expires_at'] = time.time() + _INTEGRITY_CACHE_TTL
    return jsonify(result)
