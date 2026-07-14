"""
API עבור ניהול ספקים (שלב 4).
"""
from flask import Blueprint, jsonify, request, render_template
from app.services import supplier_service as svc
from app.services.supplier_service import SupplierServiceError

suppliers_bp = Blueprint('suppliers', __name__)


def _json_body():
    return request.get_json(silent=True) or {}


@suppliers_bp.errorhandler(SupplierServiceError)
def _handle_service_error(err):
    return jsonify({"error": str(err)}), 400


@suppliers_bp.route('/suppliers')
def suppliers_page():
    return render_template('suppliers.html', active_nav='suppliers')


@suppliers_bp.route('/api/suppliers', methods=['GET'])
def api_list_suppliers():
    suppliers = svc.list_suppliers(
        q=request.args.get('q'),
        service_type=request.args.get('service_type'),
        status=request.args.get('status'),
        site_id=request.args.get('site_id', type=int),
    )
    return jsonify([svc.serialize_supplier(s) for s in suppliers])


@suppliers_bp.route('/api/suppliers/service_types', methods=['GET'])
def api_list_service_types():
    return jsonify(svc.list_service_types())


@suppliers_bp.route('/api/suppliers', methods=['POST'])
def api_create_supplier():
    supplier = svc.create_supplier(_json_body())
    return jsonify(svc.serialize_supplier(supplier)), 201


@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['GET'])
def api_get_supplier(supplier_id):
    supplier = svc.get_supplier_or_404(supplier_id)
    return jsonify(svc.serialize_supplier(supplier))


@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['PUT'])
def api_update_supplier(supplier_id):
    supplier = svc.update_supplier(supplier_id, _json_body())
    return jsonify(svc.serialize_supplier(supplier))


@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['DELETE'])
def api_delete_supplier(supplier_id):
    svc.delete_supplier(supplier_id)
    return jsonify({"success": True})
