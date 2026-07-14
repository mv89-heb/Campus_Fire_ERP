"""
Service Layer עבור ניהול ספקים (שלב 4).
"""
from datetime import date, datetime

from app.extensions import db
from app.models import Supplier
from app.services import audit_log_service as alog


class SupplierServiceError(Exception):
    pass


_DATE_FIELDS = {'contract_expiry', 'insurance_expiry'}

_FIELDS = [
    'company_name', 'supplier_number', 'contact_name', 'phone', 'phone_secondary',
    'email', 'address', 'website', 'service_type', 'service_area', 'active_days',
    'active_hours', 'contract_number', 'contract_expiry', 'insurance_expiry',
    'rating', 'status', 'notes', 'site_id',
]


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise SupplierServiceError(f"פורמט תאריך לא תקין: {value} (נדרש YYYY-MM-DD)")


def _require(value, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SupplierServiceError(f"שדה חובה חסר: {field_name}")
    return value


def list_suppliers(q=None, service_type=None, status=None, site_id=None):
    query = Supplier.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            Supplier.company_name.ilike(like),
            Supplier.contact_name.ilike(like),
            Supplier.service_type.ilike(like),
            Supplier.phone.ilike(like),
        ))
    if service_type:
        query = query.filter(Supplier.service_type == service_type)
    if status:
        query = query.filter(Supplier.status == status)
    if site_id:
        query = query.filter(Supplier.site_id == site_id)
    return query.order_by(Supplier.company_name).all()


def get_supplier_or_404(supplier_id):
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        raise SupplierServiceError(f"ספק {supplier_id} לא נמצא")
    return supplier


def create_supplier(data):
    _require(data.get('company_name'), 'company_name')
    supplier = Supplier()
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(supplier, field, value)
        elif field == 'company_name':
            supplier.company_name = data['company_name']
    db.session.add(supplier)
    db.session.flush()
    alog.log('create', 'supplier', supplier.id, entity_label=supplier.company_name, new_value=data)
    db.session.commit()
    return supplier


def update_supplier(supplier_id, data):
    supplier = get_supplier_or_404(supplier_id)
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(supplier, field, value)
    alog.log('update', 'supplier', supplier.id, entity_label=supplier.company_name, new_value=data)
    db.session.commit()
    return supplier


def delete_supplier(supplier_id):
    supplier = get_supplier_or_404(supplier_id)
    alog.log('delete', 'supplier', supplier.id, entity_label=supplier.company_name)
    db.session.delete(supplier)
    db.session.commit()


def list_service_types():
    rows = db.session.query(Supplier.service_type).filter(Supplier.service_type.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def serialize_supplier(s):
    return {
        "id": s.id, "company_name": s.company_name, "supplier_number": s.supplier_number,
        "contact_name": s.contact_name, "phone": s.phone, "phone_secondary": s.phone_secondary,
        "email": s.email, "address": s.address, "website": s.website,
        "service_type": s.service_type, "service_area": s.service_area,
        "active_days": s.active_days, "active_hours": s.active_hours,
        "contract_number": s.contract_number,
        "contract_expiry": str(s.contract_expiry) if s.contract_expiry else None,
        "insurance_expiry": str(s.insurance_expiry) if s.insurance_expiry else None,
        "rating": s.rating, "status": s.status, "notes": s.notes, "site_id": s.site_id,
    }
