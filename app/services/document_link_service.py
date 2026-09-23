"""Document intelligence relationship resolution.

Turns Gemini entity extraction into explicit, reviewable ERP links.
Automatic links are made only for unambiguous matches; ambiguous or
missing relationships remain visible as candidates for user confirmation.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from app.extensions import db
from app.models import Document, Audit, Site, Supplier


def _norm(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[‏‎\s\-_/.,:;()\[\]{}]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _score(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def _meta(document):
    try:
        value = json.loads(document.ai_actions_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _candidate(entity, score, label, extra=None):
    data = {"id": entity.id, "label": label, "score": round(score, 3)}
    if extra:
        data.update(extra)
    return data


def resolve_document(document, persist=True):
    meta = _meta(document)
    audit_number = str(meta.get("audit_number") or "").strip()
    site_name = str(meta.get("site_name") or "").strip()
    site_address = str(meta.get("site_address") or "").strip()
    supplier_name = str(meta.get("supplier_name") or "").strip()
    supplier_number = str(meta.get("supplier_number") or "").strip()

    audits = Audit.query.order_by(Audit.audit_date.desc().nullslast(), Audit.id.desc()).all()
    sites = Site.query.order_by(Site.name.asc()).all()
    suppliers = Supplier.query.order_by(Supplier.company_name.asc()).all()

    audit_candidates = []
    for audit in audits:
        score = 0.0
        if audit_number:
            score = max(score, _score(audit_number, audit.audit_number))
        if site_name and audit.site_id:
            site = db.session.get(Site, audit.site_id)
            score = max(score, _score(site_name, site.name if site else None) * 0.88)
        if score >= 0.55:
            audit_candidates.append(_candidate(
                audit, score, audit.audit_number or f"ביקורת #{audit.id}",
                {"site_id": audit.site_id, "audit_date": audit.audit_date.isoformat() if audit.audit_date else None}
            ))
    audit_candidates.sort(key=lambda x: (-x["score"], x["id"]))
    if not document.audit_id and audit_number:
        exact = [x for x in audit_candidates if x["score"] >= 0.999]
        if len(exact) == 1:
            document.audit_id = exact[0]["id"]
            document.site_id = exact[0].get("site_id")
    audit_candidates = audit_candidates[:8]

    site_candidates = []
    for site in sites:
        score = max(_score(site_name, site.name), _score(site_address, site.address) * 0.85)
        if score >= 0.55:
            site_candidates.append(_candidate(site, score, site.name, {"address": site.address}))
    site_candidates.sort(key=lambda x: (-x["score"], x["id"]))
    if not document.site_id and site_name:
        exact = [x for x in site_candidates if x["score"] >= 0.999]
        if len(exact) == 1:
            document.site_id = exact[0]["id"]
    site_candidates = site_candidates[:8]

    supplier_candidates = []
    for supplier in suppliers:
        score = max(_score(supplier_name, supplier.company_name), _score(supplier_number, supplier.supplier_number))
        if score >= 0.55:
            supplier_candidates.append(_candidate(supplier, score, supplier.company_name, {"supplier_number": supplier.supplier_number}))
    supplier_candidates.sort(key=lambda x: (-x["score"], x["id"]))
    if not document.supplier_id:
        exact = [x for x in supplier_candidates if x["score"] >= 0.999]
        if len(exact) == 1:
            document.supplier_id = exact[0]["id"]
    supplier_candidates = supplier_candidates[:8]

    links = {
        "audit": {"status": "linked" if document.audit_id else ("candidate" if audit_candidates else "missing"),
                  "id": document.audit_id, "candidates": audit_candidates},
        "site": {"status": "linked" if document.site_id else ("candidate" if site_candidates else "missing"),
                 "id": document.site_id, "candidates": site_candidates},
        "supplier": {"status": "linked" if document.supplier_id else ("candidate" if supplier_candidates else "missing"),
                     "id": document.supplier_id, "candidates": supplier_candidates},
    }

    if document.audit_id:
        audit = db.session.get(Audit, document.audit_id)
        if audit and audit.site_id and not document.site_id:
            document.site_id = audit.site_id
            links["site"]["id"] = audit.site_id
            links["site"]["status"] = "linked"

    if persist:
        meta["relationship_resolution"] = links
        document.ai_actions_json = json.dumps(meta, ensure_ascii=False)
        db.session.commit()
    return links


def apply_links(document_id, payload):
    document = db.session.get(Document, document_id)
    if not document:
        raise ValueError("המסמך לא נמצא")

    audit_id = payload.get("audit_id")
    site_id = payload.get("site_id")
    supplier_id = payload.get("supplier_id")

    if audit_id is not None:
        audit = db.session.get(Audit, int(audit_id))
        if not audit:
            raise ValueError("הביקורת שנבחרה לא נמצאה")
        document.audit_id = audit.id
        if site_id is None and audit.site_id:
            document.site_id = audit.site_id

    if site_id is not None:
        site = db.session.get(Site, int(site_id))
        if not site:
            raise ValueError("האתר שנבחר לא נמצא")
        document.site_id = site.id

    if supplier_id is not None:
        supplier = db.session.get(Supplier, int(supplier_id))
        if not supplier:
            raise ValueError("הספק שנבחר לא נמצא")
        document.supplier_id = supplier.id

    resolve_document(document, persist=False)
    db.session.commit()
    return document, resolve_document(document, persist=False)
