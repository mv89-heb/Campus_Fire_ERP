"""Reusable official fire-form library and transient print-package generation."""
import hashlib
import io
import json
import os
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
    _user()
    return render_template("fire_forms.html", active_nav="fire_forms")


@fire_forms_bp.route("/api/fire-form-templates", methods=["GET"])
def list_fire_form_templates():
    _user()
    rows = FireFormTemplate.query.filter_by(active=True).order_by(FireFormTemplate.uploaded_at.desc()).all()
    return jsonify([_serialize(row) for row in rows])


@fire_forms_bp.route("/api/fire-form-templates", methods=["POST"])
def upload_fire_form_templates():
    user = _user()
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
    _user()
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


@fire_forms_bp.route("/api/fire-form-templates/<int:template_id>/mapping", methods=["GET", "PUT"])
def fire_form_mapping(template_id):
    _user()
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

@fire_forms_bp.route("/api/fire-form-templates/<int:template_id>/print-package", methods=["POST"])
def create_fire_form_print_package(template_id):
    """Append a one-time professional certificate to the selected official form."""
    _user()
    item = db.session.get(FireFormTemplate, template_id)
    if not item or not item.active:
        return jsonify({"error": "הטופס לא נמצא"}), 404

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
        # Overlay only explicitly mapped values; handwritten date/signature stay blank.
        schema = json.loads(item.fields_schema or "[]")
        for field in schema:
            value = str(values.get(field["key"], "") or "").strip()
            if not value:
                continue
            value = "".join(ch for ch in value if ch >= " " and ch != chr(127))[:500]
            page = merged[int(field["page"])]
            rect = page.rect
            page.insert_text((float(field["x"]) * rect.width, float(field["y"]) * rect.height),
                             value, fontsize=float(field.get("font_size", 10)),
                             fontname="helv", color=(0, 0, 0), overlay=True)
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
