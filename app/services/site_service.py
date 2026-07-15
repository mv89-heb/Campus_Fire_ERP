"""
Service Layer עבור ניהול היררכיית אתרים (Site -> Building -> Floor -> Area).
מפריד לוגיקה עסקית/ולידציה מה-routes, בהתאם לדרישת הארכיטקטורה הנקייה.
"""
from app.extensions import db
from app.models import Site, Building, Floor, Area
from app.services import audit_log_service as alog


class SiteServiceError(Exception):
    """שגיאה עסקית צפויה (ולידציה) שצריכה לחזור ללקוח כ-400."""
    pass


def _require(value, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SiteServiceError(f"שדה חובה חסר: {field_name}")
    return value


# ---------- Sites ----------

def list_sites():
    return Site.query.order_by(Site.name).all()


def get_site_or_404(site_id):
    site = db.session.get(Site, site_id)
    if not site:
        raise SiteServiceError(f"אתר {site_id} לא נמצא")
    return site


def create_site(data):
    name = _require(data.get('name'), 'name')
    site = Site(
        name=name,
        address=data.get('address'),
        contact_name=data.get('contact_name'),
        contact_phone=data.get('contact_phone'),
        contact_email=data.get('contact_email'),
        map_lat=data.get('map_lat'),
        map_lng=data.get('map_lng'),
        notes=data.get('notes'),
    )
    db.session.add(site)
    db.session.flush()
    alog.log('create', 'site', site.id, entity_label=site.name, new_value=data)
    db.session.commit()
    return site


def update_site(site_id, data):
    site = get_site_or_404(site_id)
    for field in ['name', 'address', 'contact_name', 'contact_phone', 'contact_email',
                  'map_lat', 'map_lng', 'notes']:
        if field in data:
            setattr(site, field, data[field])
    alog.log('update', 'site', site.id, entity_label=site.name, new_value=data)
    db.session.commit()
    return site


def delete_site(site_id):
    site = get_site_or_404(site_id)
    alog.log('delete', 'site', site.id, entity_label=site.name)
    db.session.delete(site)
    db.session.commit()


# ---------- Buildings ----------

def create_building(site_id, data):
    get_site_or_404(site_id)
    name = _require(data.get('name'), 'name')
    building = Building(site_id=site_id, name=name, notes=data.get('notes'))
    db.session.add(building)
    db.session.flush()
    alog.log('create', 'building', building.id, entity_label=name, new_value=data)
    db.session.commit()
    return building


def update_building(building_id, data):
    building = db.session.get(Building, building_id)
    if not building:
        raise SiteServiceError(f"מבנה {building_id} לא נמצא")
    for field in ['name', 'notes']:
        if field in data:
            setattr(building, field, data[field])
    alog.log('update', 'building', building.id, entity_label=building.name, new_value=data)
    db.session.commit()
    return building


def delete_building(building_id):
    building = db.session.get(Building, building_id)
    if not building:
        raise SiteServiceError(f"מבנה {building_id} לא נמצא")
    alog.log('delete', 'building', building.id, entity_label=building.name)
    db.session.delete(building)
    db.session.commit()


# ---------- Floors ----------

def create_floor(building_id, data):
    if not db.session.get(Building, building_id):
        raise SiteServiceError(f"מבנה {building_id} לא נמצא")
    name = _require(data.get('name'), 'name')
    floor = Floor(building_id=building_id, name=name, notes=data.get('notes'))
    db.session.add(floor)
    db.session.flush()
    alog.log('create', 'floor', floor.id, entity_label=name, new_value=data)
    db.session.commit()
    return floor


def update_floor(floor_id, data):
    floor = db.session.get(Floor, floor_id)
    if not floor:
        raise SiteServiceError(f"קומה {floor_id} לא נמצאה")
    for field in ['name', 'notes']:
        if field in data:
            setattr(floor, field, data[field])
    alog.log('update', 'floor', floor.id, entity_label=floor.name, new_value=data)
    db.session.commit()
    return floor


def delete_floor(floor_id):
    floor = db.session.get(Floor, floor_id)
    if not floor:
        raise SiteServiceError(f"קומה {floor_id} לא נמצאה")
    alog.log('delete', 'floor', floor.id, entity_label=floor.name)
    db.session.delete(floor)
    db.session.commit()


# ---------- Areas ----------

def create_area(floor_id, data):
    if not db.session.get(Floor, floor_id):
        raise SiteServiceError(f"קומה {floor_id} לא נמצאה")
    name = _require(data.get('name'), 'name')
    area = Area(floor_id=floor_id, name=name, notes=data.get('notes'), zone_id=data.get('zone_id'))
    db.session.add(area)
    db.session.flush()
    alog.log('create', 'area', area.id, entity_label=name, new_value=data)
    db.session.commit()
    return area


def update_area(area_id, data):
    area = db.session.get(Area, area_id)
    if not area:
        raise SiteServiceError(f"אזור {area_id} לא נמצא")
    for field in ['name', 'notes', 'zone_id']:
        if field in data:
            setattr(area, field, data[field])
    alog.log('update', 'area', area.id, entity_label=area.name, new_value=data)
    db.session.commit()
    return area


def delete_area(area_id):
    area = db.session.get(Area, area_id)
    if not area:
        raise SiteServiceError(f"אזור {area_id} לא נמצא")
    alog.log('delete', 'area', area.id, entity_label=area.name)
    db.session.delete(area)
    db.session.commit()


# ---------- Serialization ----------

def serialize_area(area):
    return {
        "id": area.id, "floor_id": area.floor_id, "name": area.name,
        "notes": area.notes, "zone_id": area.zone_id,
    }


def serialize_floor(floor, include_areas=True):
    data = {"id": floor.id, "building_id": floor.building_id, "name": floor.name, "notes": floor.notes}
    if include_areas:
        data["areas"] = [serialize_area(a) for a in floor.areas]
    return data


def serialize_building(building, include_floors=True):
    data = {"id": building.id, "site_id": building.site_id, "name": building.name, "notes": building.notes}
    if include_floors:
        data["floors"] = [serialize_floor(f) for f in building.floors]
    return data


def serialize_site(site, include_children=True):
    data = {
        "id": site.id, "name": site.name, "address": site.address,
        "contact_name": site.contact_name, "contact_phone": site.contact_phone,
        "contact_email": site.contact_email, "map_lat": site.map_lat, "map_lng": site.map_lng,
        "notes": site.notes,
        "building_count": len(site.buildings),
    }
    if include_children:
        data["buildings"] = [serialize_building(b) for b in site.buildings]
    return data
