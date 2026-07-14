"""
Service Layer עבור חיפוש גלובלי (שלב 14).
מחפש בו-זמנית בכל הישויות המרכזיות במערכת ומחזיר תוצאות מאוחדות עם קישור
ישיר למסך הרלוונטי.
"""
from app.extensions import db
from app.models import Site, Supplier, Equipment, Task, Audit, Deficiency, Document, User


def global_search(q, limit_per_type=5):
    if not q or len(q.strip()) < 2:
        return []
    like = f"%{q.strip()}%"
    results = []

    for s in Site.query.filter(Site.name.ilike(like)).limit(limit_per_type).all():
        results.append({"type": "site", "type_label": "אתר", "id": s.id, "label": s.name, "url": "/sites"})

    for s in Supplier.query.filter(db.or_(
            Supplier.company_name.ilike(like), Supplier.contact_name.ilike(like))).limit(limit_per_type).all():
        results.append({"type": "supplier", "type_label": "ספק", "id": s.id, "label": s.company_name, "url": "/suppliers"})

    for e in Equipment.query.filter(db.or_(
            Equipment.equipment_type.ilike(like), Equipment.serial_number.ilike(like))).limit(limit_per_type).all():
        results.append({"type": "equipment", "type_label": "ציוד", "id": e.id, "label": f"{e.equipment_type} ({e.serial_number or '—'})", "url": "/equipment"})

    for t in Task.query.filter(Task.title.ilike(like)).limit(limit_per_type).all():
        results.append({"type": "task", "type_label": "משימה", "id": t.id, "label": t.title, "url": "/tasks"})

    for a in Audit.query.filter(db.or_(
            Audit.audit_number.ilike(like), Audit.inspector_name.ilike(like))).limit(limit_per_type).all():
        results.append({"type": "audit", "type_label": "ביקורת", "id": a.id, "label": a.audit_number or f"ביקורת #{a.id}", "url": "/audits"})

    for d in Deficiency.query.filter(Deficiency.title.ilike(like)).limit(limit_per_type).all():
        results.append({"type": "deficiency", "type_label": "ליקוי", "id": d.id, "label": d.title, "url": "/audits"})

    for doc in Document.query.filter(db.or_(
            Document.file_name.ilike(like), Document.permit_number.ilike(like))).limit(limit_per_type).all():
        results.append({"type": "permit", "type_label": "אישור", "id": doc.id, "label": doc.file_name, "url": "/"})

    for u in User.query.filter(db.or_(
            User.username.ilike(like), User.full_name.ilike(like))).limit(limit_per_type).all():
        results.append({"type": "user", "type_label": "משתמש", "id": u.id, "label": u.full_name or u.username, "url": "/users"})

    return results
