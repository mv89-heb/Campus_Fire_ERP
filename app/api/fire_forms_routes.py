"""Reusable official fire-form library and transient print-package generation."""
import hashlib
import html
import io
import json
import os
import re
import uuid
from datetime import datetime

import fitz
from flask import Blueprint, abort, current_app, jsonify, make_response, render_template, request, send_file, session

from app.extensions import db
from app.models import FireFormTemplate, User
from app.services import storage

fire_forms_bp = Blueprint("fire_forms", __name__)
ALLOWED_TEMPLATE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_TEMPLATE_FILES = 25
MAX_CERTIFICATE_BYTES = 12 * 1024 * 1024


def _user():
    user_id = session.get("user_id")
    user = db.session.get(User, user_id) if user_id else None
    if not user or not user.active:
        abort(401)
    return user

def _admin():
    user = _user()
    if user.role not in {"admin", "super_admin"}:
        abort(403)
    return user


def _as_pdf(data: bytes, filename: str) -> tuple[bytes, int]:
    """Validate and normalize an uploaded PDF or image entirely as bytes."""
    ext = os.path.splitext((filename or "").replace(chr(92), "/").rsplit("/", 1)[-1])[1].lower()
    if ext not in ALLOWED_TEMPLATE_EXTENSIONS:
        raise ValueError("אפשר להעלות PDF או תמונת PNG/JPG בלבד")
    if not data:
        raise ValueError("הקובץ ריק")
    if len(data) > current_app.config.get("MAX_PDF_BYTES", 100 * 1024 * 1024):
        raise ValueError("הקובץ חורג ממגבלת הגודל")
    try:
        if ext == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise ValueError("הקובץ אינו PDF תקין")
            doc = fitz.open(stream=data, filetype="pdf")
        else:
            doc = fitz.open(stream=data, filetype=ext[1:])
            normalized = doc.convert_to_pdf()
            doc.close()
            doc = fitz.open(stream=normalized, filetype="pdf")
        if doc.page_count < 1:
            doc.close()
            raise ValueError("המסמך אינו מכיל עמודים")
        page_count = doc.page_count
        normalized = doc.tobytes(garbage=4, deflate=True) if ext != ".pdf" else data
        doc.close()
        return normalized, page_count
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("לא ניתן לקרוא את הקובץ. ודא שהוא PDF או תמונה תקינים") from exc


def _store_template(template_id: str, data: bytes) -> str:
    key = f"fire-form-templates/{template_id}.pdf"
    if storage.is_configured():
        return storage.upload_bytes(key, data, "application/pdf")
    if current_app.config.get("IS_PRODUCTION"):
        raise RuntimeError("אחסון מסמכים מאובטח אינו מוגדר בסביבת הייצור")
    root = os.path.abspath(os.path.join(current_app.config["UPLOAD_FOLDER"], "fire-form-templates"))
    os.makedirs(root, mode=0o700, exist_ok=True)
    path = os.path.abspath(os.path.join(root, f"{template_id}.pdf"))
    if os.path.commonpath([path, root]) != root:
        raise RuntimeError("נתיב אחסון לא תקין")
    with open(path, "xb") as output:
        output.write(data)
    return "local:" + path


def _read_template(path: str) -> bytes:
    if path.startswith("local:"):
        local_path = os.path.abspath(path[6:])
        root = os.path.abspath(os.path.join(current_app.config["UPLOAD_FOLDER"], "fire-form-templates"))
        if os.path.commonpath([local_path, root]) != root:
            raise RuntimeError("נתיב אחסון לא תקין")
        with open(local_path, "rb") as source:
            return source.read()
    return storage.download_bytes(path)


def _delete_template_file(path: str) -> None:
    if path.startswith("local:"):
        local_path = os.path.abspath(path[6:])
        root = os.path.abspath(os.path.join(current_app.config["UPLOAD_FOLDER"], "fire-form-templates"))
        if os.path.commonpath([local_path, root]) == root and os.path.isfile(local_path):
            os.remove(local_path)
    elif storage.is_configured():
        storage.delete_object(path)


def _serialize(item):
    return {
        "id": item.id,
        "title": item.title,
        "original_filename": item.original_filename,
        "page_count": item.page_count,
        "file_size": item.file_size,
        "fields_schema": json.loads(item.fields_schema or "[]"),
        "uploaded_at": item.uploaded_at.isoformat() if item.uploaded_at else None,
    }


@fire_forms_bp.route("/fire-forms")
def fire_forms_page():
    _admin()
    return render_template("fire_forms.html", active_nav="fire_forms")


@fire_forms_bp.route("/api/fire-form-templates", methods=["GET"])
def list_fire_form_templates():
    _user()
    rows = FireFormTemplate.query.filter_by(active=True).order_by(FireFormTemplate.uploaded_at.desc()).all()
    return jsonify([_serialize(row) for row in rows])


@fire_forms_bp.route("/api/fire-form-templates", methods=["POST"])
def upload_fire_form_templates():
    user = _admin()
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "לא נבחרו קבצים"}), 400
    if len(files) > MAX_TEMPLATE_FILES:
        return jsonify({"error": f"ניתן להעלות עד {MAX_TEMPLATE_FILES} טפסים בפעימה"}), 400

    created, errors = [], []
    for file_index, uploaded in enumerate(files):
        stored_path = None
        original_name = os.path.basename((uploaded.filename or "").replace(chr(92), "/"))[:255]
        try:
            raw = uploaded.read(current_app.config.get("MAX_PDF_BYTES", 100 * 1024 * 1024) + 1)
            pdf_data, pages = _as_pdf(raw, original_name)
            digest = hashlib.sha256(pdf_data).hexdigest()
            if FireFormTemplate.query.filter_by(file_hash=digest).first():
                errors.append({"file": original_name, "error": "הטופס כבר קיים במאגר"})
                continue
            template_id = uuid.uuid4().hex
            stored_path = _store_template(template_id, pdf_data)
            title = (request.form.get("title_" + str(file_index)) or os.path.splitext(original_name)[0]).strip()[:180]
            item = FireFormTemplate(
                title=title or "טופס כיבוי",
                original_filename=original_name[:255],
                storage_path=stored_path,
                file_hash=digest,
                page_count=pages,
                file_size=len(pdf_data),
                uploaded_by=user.id,
            )
            db.session.add(item)
            db.session.commit()
            created.append(_serialize(item))
        except Exception as exc:
            db.session.rollback()
            if stored_path:
                try:
                    _delete_template_file(stored_path)
                except Exception:
                    current_app.logger.exception("Could not clean up failed fire form upload")
            errors.append({"file": original_name or "קובץ ללא שם", "error": str(exc)[:240]})
    return jsonify({"created": created, "errors": errors, "created_count": len(created)}), (207 if errors else 201)


@fire_forms_bp.route("/api/fire-form-templates/<int:template_id>", methods=["DELETE"])
def delete_fire_form_template(template_id):
    _admin()
    item = db.session.get(FireFormTemplate, template_id)
    if not item:
        return jsonify({"error": "הטופס לא נמצא"}), 404
    path = item.storage_path
    db.session.delete(item)
    db.session.commit()
    try:
        _delete_template_file(path)
    except Exception:
        current_app.logger.exception("Could not delete fire form template file id=%s", template_id)
        return jsonify({"error": "הרשומה הוסרה אך מחיקת הקובץ נכשלה; נדרש טיפול מנהל"}), 500
    return jsonify({"success": True})


@fire_forms_bp.route("/api/fire-form-templates/<int:template_id>/file", methods=["GET"])
def preview_fire_form_template(template_id):
    _user()
    item = db.session.get(FireFormTemplate, template_id)
    if not item or not item.active:
        return jsonify({"error": "הטופס לא נמצא"}), 404
    data = _read_template(item.storage_path)
    response = make_response(send_file(io.BytesIO(data), mimetype="application/pdf", download_name=item.original_filename.rsplit(".", 1)[0] + ".pdf"))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@fire_forms_bp.route("/api/fire-form-templates/<int:template_id>/pages/<int:page_number>.png", methods=["GET"])
def fire_form_template_page_image(template_id, page_number):
    _admin()
    item = db.session.get(FireFormTemplate, template_id)
    if not item or not item.active or page_number < 0 or page_number >= item.page_count:
        return jsonify({"error": "העמוד לא נמצא"}), 404
    document = fitz.open(stream=_read_template(item.storage_path), filetype="pdf")
    try:
        page = document[page_number]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image_data = pixmap.tobytes("png")
    finally:
        document.close()
    response = make_response(image_data)
    response.headers["Content-Type"] = "image/png"
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@fire_forms_bp.route("/api/fire-form-templates/<int:template_id>/mapping", methods=["GET", "PUT"])
def fire_form_mapping(template_id):
    _admin()
    item = db.session.get(FireFormTemplate, template_id)
    if not item or not item.active:
        return jsonify({"error": "הטופס לא נמצא"}), 404
    if request.method == "GET":
        return jsonify({"fields": json.loads(item.fields_schema or "[]"), "page_count": item.page_count})
    payload = request.get_json(silent=True) or {}
    fields = payload.get("fields")
    if not isinstance(fields, list) or len(fields) > 100:
        return jsonify({"error": "יש להגדיר רשימת שדות תקינה (עד 100 שדות)"}), 400
    cleaned, keys = [], set()
    for field in fields:
        if not isinstance(field, dict):
            return jsonify({"error": "הגדרת שדה אינה תקינה"}), 400
        key = str(field.get("key") or "").strip()[:60]
        label = str(field.get("label") or "").strip()[:100]
        try:
            page = int(field.get("page", 0))
            x, y = float(field.get("x")), float(field.get("y"))
            font_size = float(field.get("font_size", 10))
        except (TypeError, ValueError):
            return jsonify({"error": "מיקום או גודל גופן אינם תקינים"}), 400
        if (not key or not label or key in keys or page < 0 or page >= item.page_count
                or not 0 <= x <= 1 or not 0 <= y <= 1 or not 5 <= font_size <= 24):
            return jsonify({"error": "יש לבדוק שם, עמוד, מיקום וגודל גופן של כל שדה"}), 400
        keys.add(key)
        cleaned.append({"key": key, "label": label, "page": page, "x": x, "y": y, "font_size": font_size})
    item.fields_schema = json.dumps(cleaned, ensure_ascii=False)
    db.session.commit()
    return jsonify({"success": True, "fields": cleaned})

# Shared field vocabulary derived from the previously uploaded, completed
# fire approvals (forms 2, 3, 4, 5, 6, 7, 10, 13, 16 and 18).
# These are blank-field coordinates only: no historical person, certificate,
# inspection date, expiry date or site-specific value is copied into a new form.
# Dates are mappable input fields; signatures remain handwritten.
_AUTO_FIELD_LABELS = [
    ("institution_name", "שם המוסד / העסק", ("שם המוסד", "שם העסק", "שם הנכס", "שם האתר", "שם המפעל")),
    ("business_type", "מהות העסק", ("מהות העסק", "סוג העסק", "ייעוד הנכס")),
    ("business_id", "ח.פ / ע.מ / ע.ר / ת.ז", ("ח פ ע מ ע ר ת ז", "ח פ", "מספר חברה", "מספר עוסק")),
    ("fire_case_number", "מספר תיק ברשות הכבאות", ("מס תיק ברשות הכבאות", "מספר תיק ברשות הכבאות", "מס תיק כבאות", "מספר תיק כבאות")),
    ("address", "כתובת הנכס", ("כתובת הנכס", "כתובת העסק", "כתובת", "מען")),
    ("city", "יישוב", ("יישוב", "ישוב", "עיר")),
    ("street", "רחוב", ("רחוב",)),
    ("house_number", "מספר בית", ("מספר בית", "מס בית")),
    ("postal_code", "מיקוד", ("מיקוד",)),
    ("po_box", "תיבת דואר", ("ת ד", "תיבת דואר")),
    ("owner_name", "שם בעל העסק / מורשה חתימה", ("שם בעל העסק", "שם בעל הנכס", "בעל העסק", "מורשה חתימה")),
    ("contact_name", "שם איש הקשר", ("שם איש קשר", "שם איש קשר ראשי")),
    ("contact_phone", "טלפון איש קשר", ("טלפון ליצירת קשר", "מספר טלפון נייד", "טלפון נייד", "טלפון", "נייד")),
    ("contact_email", "דואר אלקטרוני", ("כתובת דואר אלקטרוני", "דואר אלקטרוני", "כתובת אימייל", "אימייל")),
    ("contact_role", "תפקיד איש קשר", ("תפקיד",)),
    ("company_name", "שם החברה המבצעת", ("שם החברה", "שם חברת התחזוקה", "חברה מבצעת")),
    ("company_certificate_number", "מספר אישור בחברה", ("מספר אישור בחברה", "מס אישור בחברה")),
    ("inspector_name", "שם הבודק / המבצע", ("שם הבודק", "שם הטכנאי", "שם המתקין", "שם המבצע", "שם המבצע ת", "אני הח מ")),
    ("inspector_id", "תעודת זהות של הבודק", ("ת ז של הבודק", "תעודת זהות של הבודק", "מספר זהות של הבודק")),
    ("professional_license_number", "מספר רישיון מקצועי", ("מספר רישיון", "מס רישיון", "מספר רשיון", "מס רשיון", "מספר רישיון חשמלאי")),
    ("document_date", "תאריך המסמך", ("תאריך המסמך",)),
    ("inspection_date", "תאריך בדיקה / ביצוע", ("תאריך בדיקה", "מועד בדיקה", "בתאריך")),
    ("expiry_date", "תאריך תוקף מפורש", ("בתוקף עד", "תאריך תפוגה", "תוקף עד")),
    ("next_inspection_date", "מועד בדיקה הבאה", ("מועד בדיקה הבאה", "בדיקה הבאה", "מועד הבדיקה הבא")),
    ("inspection_type", "סוג הבדיקה", ("סוג הבדיקה", "סוג בדיקה", "בדיקה שבוצעה")),
    ("inspection_result", "תוצאת הבדיקה", ("תוצאת הבדיקה", "נמצאה תקינה", "נמצאו תקינים", "תקין לא תקין")),
    ("system_description", "תיאור / סוג המערכת", ("תיאור המערכת", "סוג המערכת", "תיאור מערכת", "מערכת שנבדקה")),
    ("system_location", "מיקום המערכת", ("מיקום המערכת", "מיקום המתקן", "מיקום המערכת שנבדקה")),
    ("quantity", "כמות / מספר יחידות", ("מספר יחידות", "כמות יחידות", "כמות")),
    ("manufacturer", "יצרן", ("שם יצרן", "יצרן")),
    ("model", "דגם", ("דגם המערכת", "דגם")),
    ("serial_number", "מספר סידורי", ("מספר סידורי", "מס סידורי", "מספר מוטבע")),
    ("system_standard", "תקן / הוראת נציב", ("תקן ישראלי", "לפי ת י", "הוראת נציב")),
    ("maintenance_description", "תיאור הטיפול / התחזוקה", ("תיאור הטיפול", "פרטי הטיפול", "הטיפול שבוצע", "פעולות תחזוקה")),
]


def _normalized_hebrew_text(value):
    value = str(value or "").replace('"', " ").replace("׳", " ").replace("״", " ")
    value = re.sub(r"[^0-9a-zA-Zא-ת]+", " ", value.lower())
    return " ".join(value.split())


def _horizontal_segments(page):
    segments = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            first, second = item[1], item[2]
            if abs(first.y - second.y) > 2.5:
                continue
            left, right = sorted((first.x, second.x))
            if right - left >= 28:
                segments.append((left, right, (first.y + second.y) / 2))
    return segments


def _suggest_fields_for_pdf(pdf_bytes):
    """Suggest fields only where a writable horizontal rule is adjacent to a known label."""
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    suggestions, seen = [], set()
    try:
        for page_number, page in enumerate(document):
            segments = _horizontal_segments(page)
            page_dict = page.get_text("dict")
            page_text = _normalized_hebrew_text(page.get_text("text"))
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
                    if not spans:
                        continue
                    line_text = _normalized_hebrew_text(" ".join(span["text"] for span in spans))
                    if not line_text:
                        continue
                    bbox = fitz.Rect(
                        min(span["bbox"][0] for span in spans),
                        min(span["bbox"][1] for span in spans),
                        max(span["bbox"][2] for span in spans),
                        max(span["bbox"][3] for span in spans),
                    )
                    for key, label, aliases in _AUTO_FIELD_LABELS:
                        matched = any(_normalized_hebrew_text(alias) in line_text for alias in aliases)
                        # "ת ד" is an OCR split of תיבת דואר; require standalone tokens
                        # so it cannot match the end of "כתובת דואר אלקטרוני".
                        if key == "po_box":
                            tokens = line_text.split()
                            matched = "תיבת דואר" in line_text or any(
                                tokens[index:index + 2] == ["ת", "ד"]
                                for index in range(len(tokens) - 1)
                            )
                        # Older filled approvals label the contact person's value only
                        # as "שם מלא" beneath the contact-details section heading.
                        if (key == "contact_name" and "שם מלא" in line_text
                                and "פרטי התקשרות איש קשר ראשי" in page_text):
                            matched = True
                        # A property address must never be mapped to an e-mail field.
                        if key == "address" and ("דואר אלקטרוני" in line_text or "אימייל" in line_text):
                            matched = False
                        if key in seen or not matched:
                            continue
                        # A line immediately to the left of the Hebrew label is the
                        # safest writable target. Never guess a position without one.
                        nearby = [
                            segment for segment in segments
                            if segment[1] <= bbox.x0 + 8
                            and segment[1] >= bbox.x0 - min(page.rect.width * 0.45, 220)
                            and abs(segment[2] - (bbox.y0 + bbox.y1) / 2) <= 15
                        ]
                        if not nearby:
                            continue
                        left, right, line_y = min(
                            nearby,
                            key=lambda segment: abs(segment[1] - bbox.x0) + abs(segment[2] - (bbox.y0 + bbox.y1) / 2),
                        )
                        font_size = 10.0
                        suggestions.append({
                            "key": key,
                            "label": label,
                            "page": page_number,
                            "x": round(right / page.rect.width, 5),
                            "y": round(max(0, line_y - font_size * 1.35) / page.rect.height, 5),
                            "font_size": font_size,
                            "source": "auto_rule_label",
                        })
                        seen.add(key)
    finally:
        document.close()
    return suggestions


def _auto_map_all_templates():
    results = []
    rows = FireFormTemplate.query.filter_by(active=True).order_by(FireFormTemplate.id.asc()).all()
    for item in rows:
        existing = json.loads(item.fields_schema or "[]")
        if existing:
            results.append({
                "id": item.id, "title": item.title, "status": "kept_existing",
                "field_count": len(existing), "message": "מיפוי קיים נשמר ללא שינוי",
            })
            continue
        try:
            suggestions = _suggest_fields_for_pdf(_read_template(item.storage_path))
            if suggestions:
                item.fields_schema = json.dumps(suggestions, ensure_ascii=False)
                db.session.commit()
                results.append({
                    "id": item.id, "title": item.title, "status": "mapped",
                    "field_count": len(suggestions), "message": "זוהו תוויות וקווי מילוי תואמים",
                })
            else:
                results.append({
                    "id": item.id, "title": item.title, "status": "manual_review",
                    "field_count": 0, "message": "לא זוהה קו מילוי חד-משמעי; נדרשת בדיקה ידנית",
                })
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Automatic fire form mapping failed for template id=%s", item.id)
            results.append({
                "id": item.id, "title": item.title, "status": "error",
                "field_count": 0, "message": "לא ניתן היה לנתח את הקובץ",
            })
    return results


@fire_forms_bp.route("/api/fire-form-templates/auto-map-all", methods=["POST"])
def auto_map_all_fire_form_templates():
    _admin()
    results = _auto_map_all_templates()
    return jsonify({
        "success": True,
        "total": len(results),
        "mapped": sum(row["status"] == "mapped" for row in results),
        "kept_existing": sum(row["status"] == "kept_existing" for row in results),
        "manual_review": sum(row["status"] == "manual_review" for row in results),
        "errors": sum(row["status"] == "error" for row in results),
        "results": results,
    })


def _has_valid_fire_form_mapping(item):
    """Require at least one structurally valid mapped field before generating a print PDF."""
    try:
        fields = json.loads(item.fields_schema or "[]")
    except (TypeError, ValueError):
        return False
    if not isinstance(fields, list):
        return False
    for field in fields:
        if not isinstance(field, dict):
            continue
        try:
            page = int(field.get("page", -1))
            x, y = float(field.get("x")), float(field.get("y"))
            font_size = float(field.get("font_size", 10))
        except (TypeError, ValueError):
            continue
        if (str(field.get("key") or "").strip()
                and str(field.get("label") or "").strip()
                and 0 <= page < item.page_count
                and 0 <= x <= 1 and 0 <= y <= 1
                and 5 <= font_size <= 24):
            return True
    return False


def _overlay_mapped_values(document, item, values):
    """Overlay transient values onto one PDF using its saved field coordinates."""
    schema = json.loads(item.fields_schema or "[]")
    for field in schema:
        value = str(values.get(field["key"], "") or "").strip()
        if not value:
            continue
        value = "".join(ch for ch in value if ch >= " " and ch != chr(127))[:500]
        page = document[int(field["page"])]
        page_rect = page.rect
        anchor_x = float(field["x"]) * page_rect.width
        anchor_y = float(field["y"]) * page_rect.height
        font_size = float(field.get("font_size", 10))
        text_top = min(anchor_y, max(0, page_rect.height - 30))
        text_rect = fitz.Rect(max(0, anchor_x - page_rect.width * 0.45), text_top,
                              anchor_x, min(page_rect.height, text_top + max(28, font_size * 3)))
        safe_value = html.escape(value)
        html_text = '<div dir="rtl" style="font-family:sans-serif;font-size:' + str(font_size) + 'pt;line-height:1.2;text-align:right;color:#000;font-weight:700">' + safe_value + '</div>'
        page.insert_htmlbox(text_rect, html_text, overlay=True)


@fire_forms_bp.route("/api/fire-form-templates/print-package", methods=["POST"])
def create_fire_forms_batch_print_package():
    """Create one combined print PDF for selected forms; all submitted values stay transient."""
    _user()
    certificate = request.files.get("certificate")
    if certificate is None or not certificate.filename:
        return jsonify({"error": "יש לצרף תעודת הסמכה או רישיון לצורך ההדפסה"}), 400
    try:
        template_ids = json.loads(request.form.get("template_ids", "[]"))
        values = json.loads(request.form.get("values", "{}"))
        if (not isinstance(template_ids, list) or not template_ids or len(template_ids) > 24
                or not isinstance(values, dict)):
            raise ValueError
        ids = [int(value) for value in template_ids]
        if len(set(ids)) != len(ids):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "רשימת הטפסים או נתוני המילוי אינם תקינים"}), 400

    templates_by_id = {
        item.id: item for item in FireFormTemplate.query.filter(
            FireFormTemplate.id.in_(ids), FireFormTemplate.active.is_(True)
        ).all()
    }
    if len(templates_by_id) != len(ids):
        return jsonify({"error": "אחד מהטפסים שנבחרו אינו זמין"}), 404

    unmapped = [
        {"id": item.id, "title": item.title}
        for item in templates_by_id.values()
        if not _has_valid_fire_form_mapping(item)
    ]
    if unmapped:
        return jsonify({
            "error": "לא ניתן להפיק PDF: יש טפסים ללא מיפוי שדות תקין",
            "unmapped_templates": unmapped,
        }), 409

    cert_bytes = certificate.read(MAX_CERTIFICATE_BYTES + 1)
    if not cert_bytes or len(cert_bytes) > MAX_CERTIFICATE_BYTES:
        return jsonify({"error": "התעודה ריקה או גדולה מ-12MB"}), 400

    combined = fitz.open()
    try:
        cert_pdf, _ = _as_pdf(cert_bytes, certificate.filename)
        for template_id in ids:
            item = templates_by_id[template_id]
            source = fitz.open(stream=_read_template(item.storage_path), filetype="pdf")
            try:
                _overlay_mapped_values(source, item, values)
                combined.insert_pdf(source)
            finally:
                source.close()
        attachment = fitz.open(stream=cert_pdf, filetype="pdf")
        try:
            combined.insert_pdf(attachment)
        finally:
            attachment.close()
        output = combined.tobytes(garbage=4, deflate=True)
    except Exception:
        current_app.logger.exception("Fire forms batch print generation failed")
        return jsonify({"error": "הפקת חבילת ההדפסה נכשלה. הקבצים הזמניים לא נשמרו"}), 400
    finally:
        combined.close()

    response = send_file(
        io.BytesIO(output),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="fire-forms-print-package.pdf",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Temp-Certificate-Persisted"] = "false"
    return response


@fire_forms_bp.route("/api/fire-form-templates/<int:template_id>/print-package", methods=["POST"])
def create_fire_form_print_package(template_id):
    """Append a one-time professional certificate to the selected official form."""
    _user()
    item = db.session.get(FireFormTemplate, template_id)
    if not item or not item.active:
        return jsonify({"error": "הטופס לא נמצא"}), 404
    if not _has_valid_fire_form_mapping(item):
        return jsonify({"error": "לא ניתן להפיק PDF: לטופס עדיין לא הוגדר מיפוי שדות תקין"}), 409

    certificate = request.files.get("certificate")
    if certificate is None or not certificate.filename:
        return jsonify({"error": "יש לצרף תעודת הסמכה או רישיון לצורך ההדפסה"}), 400
    try:
        values = json.loads(request.form.get("values", "{}"))
        if not isinstance(values, dict):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "נתוני השדות אינם תקינים"}), 400

    # Do not log the uploaded filename or contents. Read once, process in memory,
    # append to the selected PDF, and never persist certificate bytes or metadata.
    cert_bytes = certificate.read(MAX_CERTIFICATE_BYTES + 1)
    if not cert_bytes or len(cert_bytes) > MAX_CERTIFICATE_BYTES:
        return jsonify({"error": "התעודה ריקה או גדולה מ-12MB"}), 400
    try:
        cert_pdf, _ = _as_pdf(cert_bytes, certificate.filename)
        source_pdf = _read_template(item.storage_path)
        merged = fitz.open(stream=source_pdf, filetype="pdf")
        # Date and signature are intentionally not mapped; they remain handwritten.
        _overlay_mapped_values(merged, item, values)
        attachment = fitz.open(stream=cert_pdf, filetype="pdf")
        merged.insert_pdf(attachment)
        attachment.close()
        output = merged.tobytes(garbage=4, deflate=True)
        merged.close()
    except Exception:
        current_app.logger.exception("Fire form print package generation failed for template id=%s", template_id)
        return jsonify({"error": "הפקת חבילת ההדפסה נכשלה. הקובץ הזמני לא נשמר במערכת"}), 400

    response = send_file(
        io.BytesIO(output),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"fire-form-{item.id}-print.pdf",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Temp-Certificate-Persisted"] = "false"
    return response
