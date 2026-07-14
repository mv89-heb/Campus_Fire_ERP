"""
API עבור ניהול ציוד כיבוי אש (שלב 8).
"""
from flask import Blueprint, jsonify, request, render_template
from app.services import equipment_service as svc
from app.services.equipment_service import EquipmentServiceError

equipment_bp = Blueprint('equipment', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@equipment_bp.errorhandler(EquipmentServiceError)
def _handle_service_error(err):
    return jsonify({"error": str(err)}), 400


@equipment_bp.route('/equipment')
def equipment_page():
    return render_template('equipment.html', active_nav='equipment')


@equipment_bp.route('/api/equipment', methods=['GET'])
def api_list_equipment():
    items = svc.list_equipment(
        q=request.args.get('q'),
        equipment_type=request.args.get('equipment_type'),
        status=request.args.get('status'),
        site_id=request.args.get('site_id', type=int),
    )
    return jsonify([svc.serialize_equipment(e) for e in items])


@equipment_bp.route('/api/equipment/types', methods=['GET'])
def api_list_types():
    return jsonify(svc.list_equipment_types())


@equipment_bp.route('/api/equipment', methods=['POST'])
def api_create_equipment():
    eq = svc.create_equipment(_json_body())
    return jsonify(svc.serialize_equipment(eq)), 201


@equipment_bp.route('/api/equipment/<int:equipment_id>', methods=['GET'])
def api_get_equipment(equipment_id):
    eq = svc.get_equipment_or_404(equipment_id)
    return jsonify(svc.serialize_equipment(eq))


@equipment_bp.route('/api/equipment/<int:equipment_id>', methods=['PUT'])
def api_update_equipment(equipment_id):
    eq = svc.update_equipment(equipment_id, _json_body())
    return jsonify(svc.serialize_equipment(eq))


@equipment_bp.route('/api/equipment/<int:equipment_id>', methods=['DELETE'])
def api_delete_equipment(equipment_id):
    svc.delete_equipment(equipment_id)
    return jsonify({"success": True})
