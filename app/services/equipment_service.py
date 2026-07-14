"""
Service Layer עבור ניהול ציוד כיבוי אש (שלב 8).
"""
from datetime import date, datetime

from app.extensions import db
from app.models import Equipment, Area, Floor, Building, Site
from app.services import audit_log_service as alog


class EquipmentServiceError(Exception):
    pass


_DATE_FIELDS = {'install_date', 'last_check_date', 'next_check_date', 'warranty_expiry'}

_FIELDS = [
    'serial_number', 'qr_code', 'barcode', 'equipment_type', 'manufacturer', 'model',
    'area_id', 'install_date', 'last_check_date', 'next_check_date', 'status',
    'warranty_expiry', 'notes', 'supplier_id',
]


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise EquipmentServiceError(f"פורמט תאריך לא תקין: {value} (נדרש YYYY-MM-DD)")


def _require(value, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise EquipmentServiceError(f"שדה חובה חסר: {field_name}")
    return value


def list_equipment(q=None, equipment_type=None, status=None, site_id=None):
    query = Equipment.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            Equipment.serial_number.ilike(like),
            Equipment.equipment_type.ilike(like),
            Equipment.manufacturer.ilike(like),
            Equipment.model.ilike(like),
            Equipment.qr_code.ilike(like),
            Equipment.barcode.ilike(like),
        ))
    if equipment_type:
        query = query.filter(Equipment.equipment_type == equipment_type)
    if status:
        query = query.filter(Equipment.status == status)
    if site_id:
        # שרשור area -> floor -> building -> site כדי לסנן ציוד לפי אתר
        query = (query.join(Area, Equipment.area_id == Area.id)
                       .join(Floor, Area.floor_id == Floor.id)
                       .join(Building, Floor.building_id == Building.id)
                       .filter(Building.site_id == site_id))
    return query.order_by(Equipment.next_check_date.asc().nullslast()).all()


def get_equipment_or_404(equipment_id):
    eq = db.session.get(Equipment, equipment_id)
    if not eq:
        raise EquipmentServiceError(f"ציוד {equipment_id} לא נמצא")
    return eq


def create_equipment(data):
    _require(data.get('equipment_type'), 'equipment_type')
    eq = Equipment(equipment_type=data['equipment_type'])
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(eq, field, value)
    db.session.add(eq)
    db.session.flush()
    alog.log('create', 'equipment', eq.id, entity_label=eq.equipment_type, new_value=data)
    db.session.commit()
    return eq


def update_equipment(equipment_id, data):
    eq = get_equipment_or_404(equipment_id)
    for field in _FIELDS:
        if field in data:
            value = data[field]
            if field in _DATE_FIELDS:
                value = _parse_date(value)
            setattr(eq, field, value)
    alog.log('update', 'equipment', eq.id, entity_label=eq.equipment_type, new_value=data)
    db.session.commit()
    return eq


def delete_equipment(equipment_id):
    eq = get_equipment_or_404(equipment_id)
    alog.log('delete', 'equipment', eq.id, entity_label=eq.equipment_type)
    db.session.delete(eq)
    db.session.commit()


def list_equipment_types():
    rows = db.session.query(Equipment.equipment_type).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def serialize_equipment(eq):
    area = db.session.get(Area, eq.area_id) if eq.area_id else None
    return {
        "id": eq.id, "serial_number": eq.serial_number, "qr_code": eq.qr_code, "barcode": eq.barcode,
        "equipment_type": eq.equipment_type, "manufacturer": eq.manufacturer, "model": eq.model,
        "area_id": eq.area_id, "area_name": area.name if area else None,
        "install_date": str(eq.install_date) if eq.install_date else None,
        "last_check_date": str(eq.last_check_date) if eq.last_check_date else None,
        "next_check_date": str(eq.next_check_date) if eq.next_check_date else None,
        "status": eq.status,
        "warranty_expiry": str(eq.warranty_expiry) if eq.warranty_expiry else None,
        "notes": eq.notes, "supplier_id": eq.supplier_id,
    }
