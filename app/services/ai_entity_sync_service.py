"""Synchronize structured Gemini document entities into the ERP domain.

Gemini is the evidence extractor; ERP tables are the operational source of truth.
This module is deliberately idempotent: rerunning it never creates duplicate
sites, suppliers, audits, deficiencies or tasks for the same document.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from app.extensions import db
from app.models import Document, Site, Supplier, Audit
from app.services import integration_service


def _meta(document):
    try:
        value = json.loads(document.ai_actions_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _clean(value):
    value = str(value or "").strip()
    return value or None


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _find_site(name, address):
    name = _clean(name)
    address = _clean(address)
    if name:
        exact = Site.query.filter(db.func.lower(Site.name) == name.lower()).first()
        if exact:
            return exact
    if address:
        exact = Site.query.filter(db.func.lower(Site.address) == address.lower()).first()
        if exact:
            return exact
    return None


def _find_supplier(name, number):
    name = _clean(name)
    number = _clean(number)
    if number:
        exact = Supplier.query.filter(db.func.lower(Supplier.supplier_number) == number.lower()).first()
        if exact:
            return exact
    if name:
        exact = Supplier.query.filter(db.func.lower(Supplier.company_name) == name.lower()).first()
        if exact:
            return exact
    return None


def _find_audit(number):
    number = _clean(number)
    if not number:
        return None
    return (Audit.query
            .filter(db.func.lower(Audit.audit_number) == number.lower())
            .order_by(Audit.id.desc())
            .first())


def sync_document_entities(document: Document, create_missing: bool = True) -> dict:
    """Materialize Gemini's extracted site/supplier/audit entities.

    Existing manually maintained fields are preserved. Missing fields are
    enriched from the document's AI extraction only.
    """
    meta = _meta(document)
    changes = []
    result = {"site_id": document.site_id, "supplier_id": document.supplier_id,
              "audit_id": document.audit_id, "created": [], "updated": []}

    site_name = _clean(meta.get("site_name"))
    site_address = _clean(meta.get("site_address"))
    supplier_name = _clean(meta.get("supplier_name"))
    supplier_number = _clean(meta.get("supplier_number"))
    audit_number = _clean(meta.get("audit_number"))
    audit_date = _parse_date(meta.get("audit_date"))
    inspector_name = _clean(meta.get("inspector_name"))
    overall_status = _clean(meta.get("overall_status"))

    site = db.session.get(Site, document.site_id) if document.site_id else None
    if not site and (site_name or site_address):
        site = _find_site(site_name, site_address)
    if not site and create_missing and site_name:
        site = Site(name=site_name, address=site_address)
        db.session.add(site)
        db.session.flush()
        result["created"].append({"type": "site", "id": site.id, "name": site.name})
    if site:
        if site_name and not site.name:
            site.name = site_name
        if site_address and not site.address:
            site.address = site_address
        document.site_id = site.id
        result["site_id"] = site.id
        changes.append("site")

    supplier = db.session.get(Supplier, document.supplier_id) if document.supplier_id else None
    if not supplier and (supplier_name or supplier_number):
        supplier = _find_supplier(supplier_name, supplier_number)
    if not supplier and create_missing and supplier_name:
        supplier = Supplier(company_name=supplier_name, supplier_number=supplier_number)
        db.session.add(supplier)
        db.session.flush()
        result["created"].append({"type": "supplier", "id": supplier.id, "name": supplier.company_name})
    if supplier:
        if supplier_name and not supplier.company_name:
            supplier.company_name = supplier_name
        if supplier_number and not supplier.supplier_number:
            supplier.supplier_number = supplier_number
        if site and not supplier.site_id:
            supplier.site_id = site.id
        if document.contact_name and not supplier.contact_name:
            supplier.contact_name = document.contact_name
        if document.issuing_body and not supplier.notes:
            supplier.notes = f"נמצא במסמך: {document.issuing_body}"
        document.supplier_id = supplier.id
        result["supplier_id"] = supplier.id
        changes.append("supplier")

    audit = db.session.get(Audit, document.audit_id) if document.audit_id else None
    if not audit and audit_number:
        audit = _find_audit(audit_number)
    if not audit and create_missing and audit_number:
        result_value = {
            "critical": "needs_attention",
            "needs_attention": "needs_attention",
            "ok": "passed",
            "unclear": "needs_attention",
        }.get(overall_status)
        audit = Audit(
            audit_number=audit_number,
            site_id=site.id if site else document.site_id,
            inspector_name=inspector_name,
            audit_date=audit_date,
            status="completed",
            result=result_value,
            notes="נוצר/הושלם מנתוני ניתוח Gemini במסמך.",
        )
        db.session.add(audit)
        db.session.flush()
        result["created"].append({"type": "audit", "id": audit.id, "number": audit.audit_number})
    if audit:
        if site and not audit.site_id:
            audit.site_id = site.id
        if audit_date and not audit.audit_date:
            audit.audit_date = audit_date
        if inspector_name and not audit.inspector_name:
            audit.inspector_name = inspector_name
        if overall_status in {"critical", "needs_attention"} and audit.result in {None, "", "passed", "ok"}:
            audit.result = "needs_attention"
        document.audit_id = audit.id
        if audit.site_id:
            document.site_id = audit.site_id
        result["audit_id"] = audit.id
        changes.append("audit")

    meta["erp_sync"] = {
        "site_id": document.site_id,
        "supplier_id": document.supplier_id,
        "audit_id": document.audit_id,
        "synced_at": datetime.utcnow().isoformat(),
        "changes": sorted(set(changes)),
    }
    document.ai_actions_json = json.dumps(meta, ensure_ascii=False)
    db.session.flush()
    return result


def reconcile_all_ai_documents(create_actions: bool = True) -> dict:
    """Backfill ERP entities from every completed Gemini document."""
    from app.services import gemini_document_service as ai_svc
    from app.services import document_link_service as link_svc

    docs = (Document.query
            .filter(Document.ai_status == "completed")
            .filter(Document.status.notin_(["deleted", "archived"]))
            .order_by(Document.id.asc())
            .all())
    summary = {"documents": len(docs), "created": 0, "linked": 0, "actions_created": 0, "errors": []}

    for document in docs:
        try:
            before = (document.site_id, document.supplier_id, document.audit_id)
            sync_document_entities(document, create_missing=True)
            link_svc.resolve_document(document, persist=False)
            if create_actions:
                action_result = ai_svc.create_operational_actions(document)
                summary["actions_created"] += int(action_result.get("count", 0))
            after = (document.site_id, document.supplier_id, document.audit_id)
            summary["linked"] += sum(1 for a, b in zip(before, after) if not a and b)
            summary["created"] += len(_meta(document).get("erp_sync", {}).get("changes", []))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            summary["errors"].append({"document_id": document.id, "error": str(exc)[:500]})
    return summary
