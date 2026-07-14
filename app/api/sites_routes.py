"""
API עבור ניהול אתרים (שלב 10): Site -> Building -> Floor -> Area.
Blueprint נפרד מ-main_bp הקיים, כדי לא לגעת בקוד שכבר עובד.
"""
from flask import Blueprint, jsonify, request, render_template
from app.services import site_service as svc
from app.services.site_service import SiteServiceError

sites_bp = Blueprint('sites', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@sites_bp.errorhandler(SiteServiceError)
def _handle_service_error(err):
    return jsonify({"error": str(err)}), 400


# ---------- Page ----------

@sites_bp.route('/sites')
def sites_page():
    return render_template('sites.html', active_nav='sites')


# ---------- Sites ----------

@sites_bp.route('/api/sites', methods=['GET'])
def api_list_sites():
    sites = svc.list_sites()
    return jsonify([svc.serialize_site(s) for s in sites])


@sites_bp.route('/api/sites', methods=['POST'])
def api_create_site():
    site = svc.create_site(_json_body())
    return jsonify(svc.serialize_site(site)), 201


@sites_bp.route('/api/sites/<int:site_id>', methods=['GET'])
def api_get_site(site_id):
    site = svc.get_site_or_404(site_id)
    return jsonify(svc.serialize_site(site))


@sites_bp.route('/api/sites/<int:site_id>', methods=['PUT'])
def api_update_site(site_id):
    site = svc.update_site(site_id, _json_body())
    return jsonify(svc.serialize_site(site))


@sites_bp.route('/api/sites/<int:site_id>', methods=['DELETE'])
def api_delete_site(site_id):
    svc.delete_site(site_id)
    return jsonify({"success": True})


# ---------- Buildings ----------

@sites_bp.route('/api/sites/<int:site_id>/buildings', methods=['POST'])
def api_create_building(site_id):
    building = svc.create_building(site_id, _json_body())
    return jsonify(svc.serialize_building(building)), 201


@sites_bp.route('/api/buildings/<int:building_id>', methods=['PUT'])
def api_update_building(building_id):
    building = svc.update_building(building_id, _json_body())
    return jsonify(svc.serialize_building(building))


@sites_bp.route('/api/buildings/<int:building_id>', methods=['DELETE'])
def api_delete_building(building_id):
    svc.delete_building(building_id)
    return jsonify({"success": True})


# ---------- Floors ----------

@sites_bp.route('/api/buildings/<int:building_id>/floors', methods=['POST'])
def api_create_floor(building_id):
    floor = svc.create_floor(building_id, _json_body())
    return jsonify(svc.serialize_floor(floor)), 201


@sites_bp.route('/api/floors/<int:floor_id>', methods=['PUT'])
def api_update_floor(floor_id):
    floor = svc.update_floor(floor_id, _json_body())
    return jsonify(svc.serialize_floor(floor))


@sites_bp.route('/api/floors/<int:floor_id>', methods=['DELETE'])
def api_delete_floor(floor_id):
    svc.delete_floor(floor_id)
    return jsonify({"success": True})


# ---------- Areas ----------

@sites_bp.route('/api/floors/<int:floor_id>/areas', methods=['POST'])
def api_create_area(floor_id):
    area = svc.create_area(floor_id, _json_body())
    return jsonify(svc.serialize_area(area)), 201


@sites_bp.route('/api/areas/<int:area_id>', methods=['PUT'])
def api_update_area(area_id):
    area = svc.update_area(area_id, _json_body())
    return jsonify(svc.serialize_area(area))


@sites_bp.route('/api/areas/<int:area_id>', methods=['DELETE'])
def api_delete_area(area_id):
    svc.delete_area(area_id)
    return jsonify({"success": True})
