from flask import Blueprint, jsonify, request, current_app, render_template, send_file, redirect
from app.extensions import db
from app.models import Zone, SystemRequirement, Document
from app.services.dms_service import DMSService
from app.services import storage
from app.utils.security import validate_and_save_pdf
from datetime import date
import io
import platform
import os

main_bp = Blueprint('main', __name__)

OUTLOOK_ENABLED = platform.system() == 'Windows'


@main_bp.route('/')
def index():
    return render_template('index.html', active_nav='permits')


@main_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Legacy document route kept for compatibility; requires authentication via global guard."""
    fname = os.path.basename(filename)
    doc = Document.query.filter(
        db.or_(Document.file_path == fname, Document.file_path.like(f'%/{fname}'))
    ).first()
    if not doc or doc.status == 'deleted' or not doc.file_path:
        return jsonify({'error': 'File not found'}), 404

    stored_path = doc.file_path
    if storage.is_supabase_path(stored_path) and storage.is_configured():
        signed_url = storage.get_signed_url(stored_path)
        if signed_url:
            return redirect(signed_url)
        current_app.logger.warning(
            f'Supabase signed URL failed for {stored_path}, falling back to local disk'
        )

    base_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, fname))
    if os.path.commonpath([full_path, base_dir]) != base_dir:
        return jsonify({'error': 'Invalid file path'}), 400

    if os.path.isfile(full_path):
        return send_file(full_path, mimetype='application/pdf')
    return jsonify({'error': 'File not found'}), 404


@main_bp.route('/api/documents/<int:doc_id>/file')
def document_file(doc_id):
    """Authenticated preview/download endpoint addressed by document ID.

    Using the document ID instead of a client-supplied filename prevents
    filename/path ambiguity and lets us enforce document status before access.
    For Supabase, the server fetches the object and streams it with the desired
    Content-Disposition so the Download action works consistently.
    """
    doc = db.session.get(Document, doc_id)
    if not doc or doc.status == 'deleted' or not doc.file_path:
        return jsonify({'error': 'File not found'}), 404

    download = request.args.get('download', '').lower() in {'1', 'true', 'yes'}
    filename = os.path.basename(doc.file_name or doc.file_path) or f'document-{doc_id}.pdf'
    if not filename.lower().endswith('.pdf'):
        filename = f'{filename}.pdf'

    if storage.is_supabase_path(doc.file_path) and storage.is_configured():
        try:
            bucket = storage.get_bucket_name()
            remote_path = doc.file_path[len(bucket) + 1:]
            data = storage._get_client().storage.from_(bucket).download(remote_path)
            if data:
                return send_file(
                    io.BytesIO(data),
                    mimetype='application/pdf',
                    as_attachment=download,
                    download_name=filename,
                    max_age=0,
                )
        except Exception as exc:
            current_app.logger.warning('Supabase document streaming failed for %s: %s', doc_id, exc)
            signed_url = storage.get_signed_url(doc.file_path)
            if signed_url and not download:
                return redirect(signed_url)

    base_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, os.path.basename(doc.file_path)))
    if os.path.commonpath([full_path, base_dir]) != base_dir:
        return jsonify({'error': 'Invalid file path'}), 400
    if not os.path.isfile(full_path):
        return jsonify({'error': 'File not found'}), 404

    return send_file(
        full_path,
        mimetype='application/pdf',
        as_attachment=download,
        download_name=filename,
        max_age=0,
    )


@main_bp.route('/api/dashboard')
def dashboard():
    try:
        zones = Zone.query.all()
        requirements_processed = []
        alerts = {'expired': [], 'critical_14': [], 'warning_30': []}
        valid_count = 0
        total_reqs = 0

        for zone in zones:
            for req in zone.requirements:
                total_reqs += 1
                docs = (Document.query
                        .filter_by(req_id=req.id, status='active')
                        .order_by(Document.uploaded_at.desc())
                        .all())
                latest = docs[0] if docs else None
                days_left = (
                    (latest.expiry_date - date.today()).days
                    if latest and latest.expiry_date else None
                )

                label = 'missing'
                if days_left is not None:
                    if days_left < 0:
                        label = 'expired'
                    elif days_left <= 14:
                        label = 'critical'
                    elif days_left <= 30:
                        label = 'warning'
                    else:
                        label = 'valid'

                entry = {
                    'req_id': req.id,
                    'zone_id': zone.id,
                    'zone_name': zone.zone_name,
                    'file_number': zone.file_number,
                    'system_name': req.system_name,
                    'required_form': req.required_form,
                    'doc_id': latest.id if latest else None,
                    'file_path': latest.file_path if latest else None,
                    'file_name': latest.file_name if latest else None,
                    'expiry_date': str(latest.expiry_date) if latest else None,
                    'status': label,
                    'doc_count': len(docs),
                    'doc_names': [d.file_name for d in docs],
                }
                requirements_processed.append(entry)

                if label == 'valid':
                    valid_count += 1
                elif label == 'expired':
                    alerts['expired'].append(entry)
                elif label == 'critical':
                    alerts['critical_14'].append(entry)
                elif label == 'warning':
                    alerts['warning_30'].append(entry)

        recent_docs = []
        for d in (Document.query
                  .filter(Document.status.notin_(['deleted', 'archived']))
                  .order_by(Document.uploaded_at.desc())
                  .limit(50)
                  .all()):
            z_name = d.zone.zone_name if d.zone else 'לא משויך'
            r_form = d.requirement.required_form if d.requirement else '-'
            recent_docs.append({
                'doc_id': d.id,
                'file_name': d.file_name,
                'zone_name': z_name,
                'form_code': r_form,
                'expiry_date': str(d.expiry_date) if d.expiry_date else '',
                'file_path': d.file_path,
            })

        score = round((valid_count / total_reqs * 100) if total_reqs else 0, 1)
        return jsonify({
            'readiness_score': score,
            'valid_count': valid_count,
            'alerts': alerts,
            'requirements': requirements_processed,
            'recent_docs': recent_docs,
            'outlook_enabled': OUTLOOK_ENABLED,
            'zones': [{'id': z.id, 'zone_name': z.zone_name} for z in zones],
        })
    except Exception as e:
        current_app.logger.exception('Dashboard Error')
        return jsonify({'error': 'אירעה שגיאה פנימית'}), 500


@main_bp.route('/api/documents/upload_bulk', methods=['POST'])
def upload_bulk():
    processed = 0
    skipped_duplicates = 0
    errors = []
    files = request.files.getlist('file')
    max_pdf_bytes = current_app.config['MAX_PDF_BYTES']

    for f in files:
        if not f or not f.filename:
            continue
        try:
            safe_path = validate_and_save_pdf(
                f,
                current_app.config['UPLOAD_FOLDER'],
                max_bytes=max_pdf_bytes,
            )
            result = DMSService.ingest_document(safe_path, f.filename)
            if result is not None:
                processed += 1
            else:
                skipped_duplicates += 1
        except Exception as e:
            current_app.logger.warning(f'Upload rejected/failed for {f.filename}: {e}')
            errors.append({'file': f.filename, 'reason': str(e)})

    success = processed > 0 or (skipped_duplicates > 0 and not errors)
    return jsonify({
        'success': success,
        'processed': processed,
        'skipped_duplicates': skipped_duplicates,
        'errors': errors,
        'total_files': len(files),
    })


@main_bp.route('/api/system/health')
def system_health():
    result = {
        'db_connected': False,
        'zones_seeded': False,
        'upload_folder_writable': False,
    }
    try:
        zone_count = Zone.query.count()
        result['db_connected'] = True
        result['zones_seeded'] = zone_count > 0
        result['zone_count'] = zone_count
    except Exception as e:
        result['db_error'] = str(e)

    try:
        test_path = os.path.join(current_app.config['UPLOAD_FOLDER'], '.write_test')
        with open(test_path, 'w') as f:
            f.write('ok')
        os.remove(test_path)
        result['upload_folder_writable'] = True
    except Exception as e:
        result['upload_folder_error'] = str(e)

    result['database_url_source'] = (
        'DATABASE_URL (custom, e.g. Neon)'
        if os.environ.get('DATABASE_URL')
        else 'SQLite מקומי (ברירת מחדל - DATABASE_URL לא הוגדר)'
    )
    result['supabase_configured'] = storage.is_configured()
    if result['supabase_configured']:
        connected, storage_error = storage.check_connection()
        result['storage_connected'] = connected
        if storage_error:
            result['storage_error'] = storage_error
    else:
        result['storage_connected'] = False
        result['storage_note'] = 'Supabase לא מוגדר - מסמכים חדשים יישמרו מקומית'

    status_code = 200 if result['db_connected'] and result['upload_folder_writable'] else 503
    return jsonify(result), status_code


@main_bp.route('/api/outlook', methods=['POST'])
def outlook():
    if not OUTLOOK_ENABLED:
        return jsonify({'error': 'Windows only'}), 400
    try:
        import win32com.client as win32
        import pythoncom
        pythoncom.CoInitialize()
        try:
            outlook = win32.Dispatch('outlook.application')
            mail = outlook.CreateItem(0)
            mail.To = 'tservice@102.gov.il'
            mail.Subject = 'הגשת מסמכי רישוי'
            mail.Body = 'שלום רב,\nמצ"ב מסמכים מעודכנים.'
            mail.Display(False)
            return jsonify({'success': True})
        finally:
            pythoncom.CoUninitialize()
    except Exception as e:
        current_app.logger.exception('Outlook integration failed')
        return jsonify({'error': 'שגיאת Outlook'}), 500
