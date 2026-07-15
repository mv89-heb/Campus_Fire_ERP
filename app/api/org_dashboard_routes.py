"""
API עבור הדשבורד הארגוני (שלב 1). Blueprint נפרד; אינו נוגע ב-main_bp.
"""
from flask import Blueprint, jsonify, render_template
from app.services import org_dashboard_service as svc

org_dashboard_bp = Blueprint('org_dashboard', __name__)


@org_dashboard_bp.route('/org-dashboard')
def org_dashboard_page():
    return render_template('org_dashboard.html', active_nav='dashboard')


@org_dashboard_bp.route('/api/org-dashboard', methods=['GET'])
def api_org_dashboard():
    from flask import request
    force = request.args.get('refresh', 'false').lower() == 'true'
    return jsonify(svc.get_org_dashboard(force_refresh=force))
