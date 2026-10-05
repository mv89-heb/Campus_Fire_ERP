"""Data integrity and safe master-data deduplication for the ERP.

The PDF/Gemini layer is evidence; the relational ERP tables are the operational
source of truth. This service detects and safely merges only exact normalized
master-record duplicates. It never merges deficiencies automatically.
"""
from __future__ import annotations

import re
from collections import defaultdict

from app.extensions import db
from app.models import (
    Document, Site, Building, Floor, Area, Supplier, Equipment,
    Task, Audit, Deficiency,
)


def normalize(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", value)
    value = re.sub(r"[^\w\u0590-\u05ff]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _groups(rows, key_fn):
    groups = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        if key:
            groups[key].append(row)
    return {key: rows for key, rows in groups.items() if len(rows) > 1}


def _fill_empty(target, source, fields):
    changed = 0
    for field in fields:
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
            changed += 1
    return changed


def scan():
    site_dupes = _groups(Site.query.order_by(Site.id.asc()).all(), lambda x: (
        "nameaddr:" + normalize(x.name) + "|" + normalize(x.address)
        if normalize(x.name) and normalize(x.address)
        else "name:" + normalize(x.name) if normalize(x.name)
        else "addr:" + normalize(x.address)
    ))
    supplier_dupes = _groups(
        Supplier.query.order_by(Supplier.id.asc()).all(),
        lambda x: "num:" + normalize(x.supplier_number) if normalize(x.supplier_number)
        else "name:" + normalize(x.company_name),
    )
    building_dupes = _groups(
        Building.query.order_by(Building.id.asc()).all(),
        lambda x: f"{x.site_id}:{normalize(x.name)}",
    )
    floor_dupes = _groups(
        Floor.query.order_by(Floor.id.asc()).all(),
        lambda x: f"{x.building_id}:{normalize(x.name)}",
    )
    area_dupes = _groups(
        Area.query.order_by(Area.id.asc()).all(),
        lambda x: f"{x.floor_id}:{normalize(x.name)}",
    )
    equipment_dupes = _groups(
        Equipment.query.order_by(Equipment.id.asc()).all(),
        lambda x: (
            "serial:" + normalize(x.serial_number)
            + "|manufacturer:" + normalize(x.manufacturer)
            + "|model:" + normalize(x.model)
            if normalize(x.serial_number) else ""
        ),
    )
    audit_dupes = _groups(
        Audit.query.order_by(Audit.id.asc()).all(),
        lambda x: (
            "num:" + normalize(x.audit_number) + "|site:" + str(x.site_id or "")
            if normalize(x.audit_number) else ""
        ),
    )

    orphan = {
        "documents_missing_site": Document.query.filter(
            Document.ai_status == "completed",
            Document.site_id.is_(None),
            Document.status.notin_(["deleted", "archived"]),
        ).count(),
        "documents_missing_supplier": Document.query.filter(
            Document.ai_status == "completed",
            Document.supplier_id.is_(None),
            Document.status.notin_(["deleted", "archived"]),
        ).count(),
        "documents_missing_audit": Document.query.filter(
            Document.ai_status == "completed",
            Document.audit_id.is_(None),
            Document.status.notin_(["deleted", "archived"]),
        ).count(),
        "deficiencies_without_audit": Deficiency.query.filter(Deficiency.audit_id.is_(None)).count(),
        "deficiencies_without_task": Deficiency.query.filter(
            Deficiency.status != "resolved",
            Deficiency.task_id.is_(None),
        ).count(),
        "equipment_without_area": Equipment.query.filter(Equipment.area_id.is_(None)).count(),
    }

    return {
        "duplicates": {
            "sites": sum(len(v) - 1 for v in site_dupes.values()),
            "suppliers": sum(len(v) - 1 for v in supplier_dupes.values()),
            "buildings": sum(len(v) - 1 for v in building_dupes.values()),
            "floors": sum(len(v) - 1 for v in floor_dupes.values()),
            "areas": sum(len(v) - 1 for v in area_dupes.values()),
            "equipment_by_serial": sum(len(v) - 1 for v in equipment_dupes.values()),
            "audits_by_number": sum(len(v) - 1 for v in audit_dupes.values()),
        },
        "orphans": orphan,
    }


def _merge_sites():
    groups = _groups(Site.query.order_by(Site.id.asc()).all(), lambda x: (
        "nameaddr:" + normalize(x.name) + "|" + normalize(x.address)
        if normalize(x.name) and normalize(x.address)
        else "name:" + normalize(x.name) if normalize(x.name)
        else "addr:" + normalize(x.address)
    ))
    merged = 0
    fields = ["address", "contact_name", "contact_phone", "contact_email", "map_lat", "map_lng", "notes"]
    for rows in groups.values():
        target = rows[0]
        for duplicate in rows[1:]:
            _fill_empty(target, duplicate, fields)
            Document.query.filter_by(site_id=duplicate.id).update({"site_id": target.id}, synchronize_session=False)
            Audit.query.filter_by(site_id=duplicate.id).update({"site_id": target.id}, synchronize_session=False)
            Task.query.filter_by(site_id=duplicate.id).update({"site_id": target.id}, synchronize_session=False)
            Supplier.query.filter_by(site_id=duplicate.id).update({"site_id": target.id}, synchronize_session=False)
            Building.query.filter_by(site_id=duplicate.id).update({"site_id": target.id}, synchronize_session=False)
            db.session.delete(duplicate)
            merged += 1
    return merged


def _merge_suppliers():
    groups = _groups(
        Supplier.query.order_by(Supplier.id.asc()).all(),
        lambda x: "num:" + normalize(x.supplier_number) if normalize(x.supplier_number)
        else "name:" + normalize(x.company_name),
    )
    merged = 0
    fields = [
        "supplier_number", "contact_name", "phone", "phone_secondary", "email",
        "address", "website", "service_type", "service_area", "active_days",
        "active_hours", "contract_number", "contract_expiry", "insurance_expiry",
        "rating", "status", "notes", "site_id",
    ]
    for rows in groups.values():
        target = rows[0]
        for duplicate in rows[1:]:
            _fill_empty(target, duplicate, fields)
            Document.query.filter_by(supplier_id=duplicate.id).update({"supplier_id": target.id}, synchronize_session=False)
            Equipment.query.filter_by(supplier_id=duplicate.id).update({"supplier_id": target.id}, synchronize_session=False)
            Task.query.filter_by(supplier_id=duplicate.id).update({"supplier_id": target.id}, synchronize_session=False)
            db.session.delete(duplicate)
            merged += 1
    return merged


def _merge_buildings():
    groups = _groups(
        Building.query.order_by(Building.id.asc()).all(),
        lambda x: f"{x.site_id}:{normalize(x.name)}",
    )
    merged = 0
    for rows in groups.values():
        target = rows[0]
        for duplicate in rows[1:]:
            _fill_empty(target, duplicate, ["notes"])
            Floor.query.filter_by(building_id=duplicate.id).update({"building_id": target.id}, synchronize_session=False)
            Audit.query.filter_by(building_id=duplicate.id).update({"building_id": target.id}, synchronize_session=False)
            db.session.delete(duplicate)
            merged += 1
    return merged


def _merge_floors():
    groups = _groups(
        Floor.query.order_by(Floor.id.asc()).all(),
        lambda x: f"{x.building_id}:{normalize(x.name)}",
    )
    merged = 0
    for rows in groups.values():
        target = rows[0]
        for duplicate in rows[1:]:
            _fill_empty(target, duplicate, ["notes"])
            Area.query.filter_by(floor_id=duplicate.id).update({"floor_id": target.id}, synchronize_session=False)
            Audit.query.filter_by(floor_id=duplicate.id).update({"floor_id": target.id}, synchronize_session=False)
            db.session.delete(duplicate)
            merged += 1
    return merged


def _merge_areas():
    groups = _groups(
        Area.query.order_by(Area.id.asc()).all(),
        lambda x: f"{x.floor_id}:{normalize(x.name)}",
    )
    merged = 0
    for rows in groups.values():
        target = rows[0]
        for duplicate in rows[1:]:
            _fill_empty(target, duplicate, ["zone_id", "notes"])
            Equipment.query.filter_by(area_id=duplicate.id).update({"area_id": target.id}, synchronize_session=False)
            db.session.delete(duplicate)
            merged += 1
    return merged


def _merge_equipment():
    groups = _groups(
        Equipment.query.order_by(Equipment.id.asc()).all(),
        lambda x: "serial:" + normalize(x.serial_number) if normalize(x.serial_number) else "",
    )
    merged = 0
    fields = [
        "qr_code", "barcode", "equipment_type", "manufacturer", "model", "area_id",
        "install_date", "last_check_date", "next_check_date", "status",
        "warranty_expiry", "notes", "supplier_id",
    ]
    for rows in groups.values():
        target = rows[0]
        for duplicate in rows[1:]:
            _fill_empty(target, duplicate, fields)
            db.session.delete(duplicate)
            merged += 1
    return merged


def _merge_audits():
    groups = _groups(
        Audit.query.order_by(Audit.id.asc()).all(),
        lambda x: (
            "num:" + normalize(x.audit_number) + "|site:" + str(x.site_id or "")
            if normalize(x.audit_number) else ""
        ),
    )
    merged = 0
    fields = ["site_id", "building_id", "floor_id", "inspector_name", "audit_date", "status", "result", "score", "notes", "signature_data"]
    for rows in groups.values():
        target = rows[0]
        for duplicate in rows[1:]:
            _fill_empty(target, duplicate, fields)
            Document.query.filter_by(audit_id=duplicate.id).update({"audit_id": target.id}, synchronize_session=False)
            Deficiency.query.filter_by(audit_id=duplicate.id).update({"audit_id": target.id}, synchronize_session=False)
            db.session.delete(duplicate)
            merged += 1
    return merged



def _repair_safe_links():
    """Repair relationships only when the source document gives an unambiguous link."""
    repaired = {"deficiencies_to_audit": 0, "equipment_to_area": 0}

    for deficiency in Deficiency.query.filter(Deficiency.audit_id.is_(None)).all():
        match = re.search(r"(?:^|;)document:(\d+)(?:;|$)", deficiency.notes or "")
        if not match:
            continue
        document = db.session.get(Document, int(match.group(1)))
        if document and document.audit_id:
            deficiency.audit_id = document.audit_id
            repaired["deficiencies_to_audit"] += 1

    for equipment in Equipment.query.filter(Equipment.area_id.is_(None)).all():
        if not equipment.supplier_id:
            continue
        supplier = db.session.get(Supplier, equipment.supplier_id)
        if not supplier or not supplier.site_id:
            continue
        area_rows = (Area.query.join(Floor, Area.floor_id == Floor.id)
                     .join(Building, Floor.building_id == Building.id)
                     .filter(Building.site_id == supplier.site_id)
                     .order_by(Area.id.asc()).all())
        if len(area_rows) == 1:
            equipment.area_id = area_rows[0].id
            repaired["equipment_to_area"] += 1
    return repaired

def repair():
    """Safely merge exact normalized master duplicates and return the result."""
    before = scan()
    merged = {}
    try:
        # Parent entities first, then their children, so foreign keys remain valid.
        merged["sites"] = _merge_sites()
        merged["suppliers"] = _merge_suppliers()
        merged["buildings"] = _merge_buildings()
        merged["floors"] = _merge_floors()
        merged["areas"] = _merge_areas()
        merged["equipment"] = _merge_equipment()
        merged["audits"] = _merge_audits()
        safe_links = _repair_safe_links()
        db.session.flush()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    after = scan()
    return {"before": before, "merged": merged, "safe_links": safe_links, "after": after}
