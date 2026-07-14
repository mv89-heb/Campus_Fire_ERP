from flask import Blueprint, jsonify, request, current_app, render_template, send_file, redirect
from app.extensions import db
from app.models import Zone, SystemRequirement, Document
from app.services.dms_service import DMSService
from app.services import storage
from app.utils.security import validate_and_save_pdf
from datetime import date
import platform
import os

main_bp = Blueprint('main', __name__)

OUTLOOK_ENABLED = platform.system() == 'Windows'

@main_bp.route('/')
def index():
    return render_template('index.html', active_nav='permits')

@main_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    """
    פותח/מוריד מסמך. תומך בשני מקורות אחסון במקביל לצורך תאימות לאחור:
    - מסמכים חדשים: file_path בפורמט 'documents/uuid.pdf' -> Supabase (signed URL)
    - מסמכים ישנים: file_path בפורמט 'uuid.pdf' בלבד -> דיסק מקומי (uploads/)
    אם Supabase נכשל (או שהמסמך לא נמצא ב-DB), נופלים חזרה לדיסק המקומי -
    תיקיית uploads/ לא בוטלה בכוונה, בדיוק בשביל המקרה הזה.
    """
    fname = os.path.basename(filename)

    # מזהים את הרשומה ב-DB לפי שם הקובץ הפיזי, כדי לדעת היכן הוא מאוחסן בפועל
    doc = Document.query.filter(
        db.or_(Document.file_path == fname, Document.file_path.like(f"%/{fname}"))
    ).first()
    stored_path = doc.file_path if doc else fname

    if storage.is_supabase_path(stored_path) and storage.is_configured():
        signed_url = storage.get_signed_url(stored_path)
        if signed_url:
            return redirect(signed_url)
        current_app.logger.warning(f"Supabase signed URL failed for {stored_path}, falling back to local disk")

    # נתיב התיקייה הראשית (איפה שקובץ ה-uploads נמצא בשרת) - fallback מקומי
    base_dir = os.path.abspath(os.path.join(current_app.root_path, '..', 'uploads'))
    full_path = os.path.join(base_dir, fname)

    if os.path.exists(full_path):
        return send_file(full_path, mimetype='application/pdf')
    else:
        return f"File not found. Looking in: {full_path}", 404

@main_bp.route('/api/dashboard')
def dashboard():
    try:
        zones = Zone.query.all()
        requirements_processed = []
        alerts = {"expired": [], "critical_14": [], "warning_30": []}
        valid_count = 0
        total_reqs = 0

        for zone in zones:
            for req in zone.requirements:
                total_reqs += 1
                docs = Document.query.filter_by(req_id=req.id, status='active').order_by(Document.uploaded_at.desc()).all()
                latest = docs[0] if docs else None
                
                days_left = (latest.expiry_date - date.today()).days if latest and latest.expiry_date else None
                
                label = "missing"
                if days_left is not None:
                    if days_left < 0: label = "expired"
                    elif days_left <= 14: label = "critical"
                    elif days_left <= 30: label = "warning"
                    else: label = "valid"

                entry = {
                    "req_id": req.id, "zone_id": zone.id, "zone_name": zone.zone_name, "file_number": zone.file_number,
                    "system_name": req.system_name, "required_form": req.required_form,
                    "doc_id": latest.id if latest else None,
                    "file_path": latest.file_path if latest else None,
                    "file_name": latest.file_name if latest else None,
                    "expiry_date": str(latest.expiry_date) if latest else None,
                    "status": label, "doc_count": len(docs),
                    "doc_names": [d.file_name for d in docs]
                }
                requirements_processed.append(entry)
                
                if label == "valid": valid_count += 1
                elif label == "expired": alerts["expired"].append(entry)
                elif label == "critical": alerts["critical_14"].append(entry)
                elif label == "warning": alerts["warning_30"].append(entry)

        recent_docs = []
        for d in Document.query.order_by(Document.uploaded_at.desc()).limit(50).all():
            z_name = d.zone.zone_name if d.zone else "לא משויך"
            r_form = d.requirement.required_form if d.requirement else "-"
            recent_docs.append({
                "file_name": d.file_name, "zone_name": z_name, "form_code": r_form, 
                "expiry_date": str(d.expiry_date) if d.expiry_date else "", "file_path": d.file_path
            })

        score = round((valid_count / total_reqs * 100) if total_reqs else 0, 1)

        return jsonify({
            "readiness_score": score, "valid_count": valid_count, "alerts": alerts,
            "requirements": requirements_processed, "recent_docs": recent_docs,
            "outlook_enabled": OUTLOOK_ENABLED, 
            "zones": [{"id": z.id, "zone_name": z.zone_name} for z in zones]
        })
    except Exception as e:
        current_app.logger.error(f"Dashboard Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@main_bp.route('/api/documents/upload_bulk', methods=['POST'])
def upload_bulk():
    processed = 0
    skipped_duplicates = 0
    errors = []
    files = request.files.getlist('file')
    for f in files:
        if not f or not f.filename:
            continue
        if not f.filename.lower().endswith('.pdf'):
            errors.append({"file": f.filename, "reason": "הקובץ אינו PDF"})
            continue
        try:
            safe_path = validate_and_save_pdf(f, current_app.config['UPLOAD_FOLDER'])
            result = DMSService.ingest_document(safe_path, f.filename)
            if result is not None:
                processed += 1
            else:
                skipped_duplicates += 1
        except Exception as e:
            current_app.logger.error(f"Upload error for {f.filename}: {e}")
            errors.append({"file": f.filename, "reason": str(e)})

    # אם לא הועלה אף קובץ ויש שגיאות אמיתיות (לא רק כפילויות) - זו כשלון אמיתי,
    # ככל הנראה בעיית חיבור למסד הנתונים (למשל Neon לא מוגדר/לא נגיש).
    success = processed > 0 or (skipped_duplicates > 0 and not errors)
    return jsonify({
        "success": success,
        "processed": processed,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
        "total_files": len(files),
    })


@main_bp.route('/api/system/health')
def system_health():
    """
    בדיקת תקינות מהירה: חיבור ל-DB, קיום נתוני בסיס (seed), ותיקיית העלאות.
    שימושי לאבחון בעיות כמו הגדרת DATABASE_URL שגויה (למשל Neon לא מחובר).
    """
    result = {"db_connected": False, "zones_seeded": False, "upload_folder_writable": False}
    try:
        zone_count = Zone.query.count()
        result["db_connected"] = True
        result["zones_seeded"] = zone_count > 0
        result["zone_count"] = zone_count
    except Exception as e:
        result["db_error"] = str(e)

    try:
        test_path = os.path.join(current_app.config['UPLOAD_FOLDER'], '.write_test')
        with open(test_path, 'w') as f:
            f.write('ok')
        os.remove(test_path)
        result["upload_folder_writable"] = True
    except Exception as e:
        result["upload_folder_error"] = str(e)

    result["database_url_source"] = "DATABASE_URL (custom, e.g. Neon)" if os.environ.get("DATABASE_URL") else "SQLite מקומי (ברירת מחדל - DATABASE_URL לא הוגדר)"

    result["supabase_configured"] = storage.is_configured()
    if result["supabase_configured"]:
        connected, storage_error = storage.check_connection()
        result["storage_connected"] = connected
        if storage_error:
            result["storage_error"] = storage_error
    else:
        result["storage_connected"] = False
        result["storage_note"] = "Supabase לא מוגדר - מסמכים חדשים יישמרו מקומית (תאימות לאחור)"

    status_code = 200 if result["db_connected"] and result["upload_folder_writable"] else 503
    return jsonify(result), status_code

@main_bp.route('/api/outlook', methods=['POST'])
def outlook():
    if not OUTLOOK_ENABLED: return jsonify({"error": "Windows only"}), 400
    try:
        import win32com.client, pythoncom
        pythoncom.CoInitialize()
        outlook = win32.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)
        mail.To = "tservice@102.gov.il"
        mail.Subject = "הגשת מסמכי רישוי"
        mail.Body = "שלום רב,\nמצ\"ב מסמכים מעודכנים."
        mail.Display(False)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
