"""
API עבור חיפוש גלובלי (שלב 14).
"""
from flask import Blueprint, jsonify, request
from app.services import search_service as svc

search_bp = Blueprint('global_search', __name__)


@search_bp.route('/api/search', methods=['GET'])
def api_global_search():
    q = request.args.get('q', '')
    return jsonify(svc.global_search(q))
