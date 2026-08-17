from flask import Blueprint, jsonify, request, current_app, render_template, send_file, redirect, session
from app.extensions import db
from app.models import Zone, SystemRequirement, Document
from app.services.dms_service import DMSService
from app.services import storage
from app.services.document_analysis_service import validity_status
from app.utils.security import validate_and_save_pdf
from datetime import date
import io
import platform
import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

main_bp = Blueprint('main', __name__)
OUTLOOK_ENABLED = platform.system() == 'Windows'
DOCUMENT_TOKEN_SALT = 'campus-fire-document-access-v1'
DOCUMENT_TOKEN_MAX_AGE = 300


def _document_token_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=DOCUMENT_TOKEN_SALT)


def _document_token_valid(token, doc_id):
    if not token:
        return False
    try:
        payload = _document_token_serializer().loads(token, max_age=DOCUMENT_TOKEN_MAX_AGE)
        return int(payload.get('doc_id')) == int(doc_id)
    except (BadSignature, SignatureExpired, TypeError, ValueError, AttributeError):
        return False


def _document_access_allowed(doc_id):
    if session.get('user_id'):
        return True
    token = request.args.get('access_token') or request.headers.get('X-Document-Access-Token') or request.cookies.get(f'doc_access_{int(doc_id)}')
    return _document_token_valid(token, doc_id)


def _safe_pdf_filename(doc, doc_id):
    filename = os.path.basename(doc.file_name or '') or f'document-{doc_id}.pdf'
    if not filename.lower().endswith('.pdf'):
        filename += '.pdf'
    return filename


def _pdf_response(data, filename, download=False):
    if not data or not data.startswith(b'%PDF-'):
        raise ValueError('אחסון המסמך החזיר תוכן שאינו PDF תקין')
    response = send_file(io.BytesIO(data), mimetype='application/pdf', as_attachment=download,
                         download_name=filename, max_age=0, conditional=False)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Length'] = str(len(data))
    response.headers['Cache-Control'] = 'private, no-store, max-age=0, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def _supabase_remote_path(resolved_path):
    bucket = storage.get_bucket_name()
    prefix = f'{bucket}/'
    return resolved_path[len(prefix):] if resolved_path.startswith(prefix) else resolved_path


def _download_supabase_pdf(resolved_path, doc_id):
    if not storage.is_configured():
        return None, 'Supabase אינו מוגדר'
    try:
        remote_path = _supabase_remote_path(resolved_path)
        data = storage.download_bytes(resolved_path)
        if not data:
            return None, f'Supabase החזיר קובץ ריק עבור {remote_path}'
        validation = storage.verify_pdf_bytes(data)
        if not validation['status']:
            current_app.logger.error('Document %s resolved to %s but PDF validation failed: %s', doc_id, resolved_path, validation['error'])
            return None, validation['error']
        return data, None
    except Exception as exc:
        current_app.logger.exception('Direct Supabase download failed for document %s path=%s', doc_id, resolved_path)
        return None, str(exc)


def _supabase_signed_redirect(resolved_path, doc_id):
    try:
        signed_url = storage.get_signed_url(resolved_path, expires_in=300)
        if signed_url:
            response = redirect(signed_url, code=302)
            response.headers['Cache-Control'] = 'private, no-store, max-age=0'
            return response
    except Exception:
        current_app.logger.exception('Signed Supabase redirect failed for document %s path=%s', doc_id, resolved_path)
    return None


@main_bp.route('/')
def index():
    if not session.get('user_id'):
        return redirect('/login')
    return render_template('index.html', active_nav='permits')


@main_bp.route('/favicon.ico')
def favicon():
    return '', 204


@main_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    fname = os.path.basename(filename)
    doc = Document.query.filter(db.or_(Document.file_path == fname, Document.file_path.like(f'%/{fname}'))).first()
    if not doc or doc.status == 'deleted' or not doc.file_path:
        return jsonify({'error': 'File not found'}), 404
    if not _document_access_allowed(doc.id):
        return jsonify({'error': 'נדרשת התחברות'}), 401
    resolved = storage.find_supabase_legacy_path(doc.file_path)
    if resolved and storage.is_configured():
        data, error = _download_supabase_pdf(resolved, doc.id)
        if data:
            return _pdf_response(data, _safe_pdf_filename(doc, doc.id), download=False)
        if error:
            current_app.logger.warning('Legacy upload route could not load document %s: %s', doc.id, error)
            fallback = _supabase_signed_redirect(resolved, doc.id)
            if fallback:
                return fallback
    if storage.is_supabase_path(doc.file_path) and storage.is_configured():
        data, error = _download_supabase_pdf(doc.file_path, doc.id)
        if data:
            return _pdf_response(data, _safe_pdf_filename(doc, doc.id), download=False)
        if error:
            current_app.logger.warning('Supabase upload route could not load document %s: %s', doc.id, error)
            fallback = _supabase_signed_redirect(doc.file_path, doc.id)
            if fallback:
                return fallback
    base_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, fname))
    if os.path.commonpath([full_path, base_dir]) != base_dir:
        return jsonify({'error': 'Invalid file path'}), 400
    if os.path.isfile(full_path):
        with open(full_path, 'rb') as local_file:
            data = local_file.read()
        try:
            return _pdf_response(data, _safe_pdf_filename(doc, doc.id), download=False)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 502
    return jsonify({'error': f'File not found. Looking in: {full_path}'}), 404


@main_bp.route('/api/documents/<int:doc_id>/file', methods=['GET'])
def document_file(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc or doc.status == 'deleted' or not doc.file_path:
        return jsonify({'error': 'File not found'}), 404
    if not _document_access_allowed(doc_id):
        return jsonify({'error': 'נדרשת התחברות'}), 401
    download = request.args.get('download', '').lower() in {'1', 'true', 'yes'}
    filename = _safe_pdf_filename(doc, doc_id)
    resolved_path = doc.file_path if storage.is_supabase_path(doc.file_path) else storage.find_supabase_legacy_path(doc.file_path)
    if resolved_path and storage.is_configured():
        data, error = _download_supabase_pdf(resolved_path, doc_id)
        if data:
            return _pdf_response(data, filename, download=download)
        current_app.logger.error('Document %s resolved in Supabase but direct download failed. db_path=%s resolved=%s error=%s', doc_id, doc.file_path, resolved_path, error)
        if not download:
            fallback = _supabase_signed_redirect(resolved_path, doc_id)
            if fallback:
                return fallback
        return jsonify({'error': 'המסמך נמצא ב-Supabase אך לא ניתן להוריד אותו', 'document_id': doc_id,
                        'resolved_path': resolved_path, 'details': error}), 502
    base_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, os.path.basename(doc.file_path)))
    if os.path.commonpath([full_path, base_dir]) != base_dir:
        return jsonify({'error': 'Invalid file path'}), 400
    if not os.path.isfile(full_path):
        return jsonify({'error': 'File not found', 'document_id': doc_id, 'db_file_path': doc.file_path,
                        'looking_in': full_path, 'supabase_resolved': False}), 404
    try:
        with open(full_path, 'rb') as local_file:
            data = local_file.read()
        return _pdf_response(data, filename, download=download)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 502


@main_bp.route('/api/dashboard')
def dashboard():
    try:
        zones = Zone.query.all()
        requirements_processed = []
        alerts = {'expired': [], 'critical_14': [], 'warning_30': [], 'needs_review': []}
        valid_count = 0
        total_reqs = 0
        for zone in zones:
            for req in zone.requirements:
                total_reqs += 1
                docs = Document.query.filter_by(req_id=req.id, status='active').order_by(Document.uploaded_at.desc()).all()
                latest = docs[0] if docs else None
                if not latest or not latest.expiry_date:
                    label = 'needs_review' if latest else 'missing'
                else:
                    days_left = (latest.expiry_date - date.today()).days
                    if days_left <= 0:
                        label = 'expired'
                    elif days_left <= 14:
                        label = 'critical'
                    elif days_left <= 30:
                        label = 'warning'
                    else:
                        label = 'valid'
                entry = {
                    'req_id': req.id, 'zone_id': zone.id, 'zone_name': zone.zone_name,
                    'file_number': zone.file_number, 'system_name': req.system_name,
                    'required_form': req.required_form, 'doc_id': latest.id if latest else None,
                    'file_path': latest.file_path if latest else None,
                    'file_name': latest.file_name if latest else None,
                    'file_access_url': f'/api/documents/{latest.id}/file' if latest and latest.file_path else None,
                    'issue_date': str(latest.issue_date) if latest and latest.issue_date else None,
                    'expiry_date': str(latest.expiry_date) if latest and latest.expiry_date else None,
                    'status': label, 'doc_count': len(docs), 'doc_names': [d.file_name for d in docs],
                    'analysis_tags': latest.tags if latest else None,
                }
                requirements_processed.append(entry)
                if label == 'valid': valid_count += 1
                elif label == 'expired': alerts['expired'].append(entry)
                elif label == 'critical': alerts['critical_14'].append(entry)
                elif label == 'warning': alerts['warning_30'].append(entry)
                elif label == 'needs_review': alerts['needs_review'].append(entry)
        recent_docs = []
        for d in Document.query.filter(Document.status.notin_(['deleted', 'archived'])).order_by(Document.uploaded_at.desc()).limit(50).all():
            recent_docs.append({'doc_id': d.id, 'file_name': d.file_name,
                                'zone_name': d.zone.zone_name if d.zone else 'לא משויך',
                                'form_code': d.requirement.required_form if d.requirement else '-',
                                'issue_date': str(d.issue_date) if d.issue_date else '',
                                'expiry_date': str(d.expiry_date) if d.expiry_date else '',
                                'validity_status': ('missing' if not d.file_path else validity_status(d.expiry_date)),
                                'file_path': d.file_path,
                                'file_access_url': f'/api/documents/{d.id}/file' if d.file_path else None})
        score = round((valid_count / total_reqs * 100) if total_reqs else 0, 1)
        return jsonify({'readiness_score': score, 'valid_count': valid_count, 'alerts': alerts,
                        'requirements': requirements_processed, 'recent_docs': recent_docs,
                        'outlook_enabled': OUTLOOK_ENABLED,
                        'zones': [{'id': z.id, 'zone_name': z.zone_name} for z in zones]})
    except Exception:
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
            safe_path = validate_and_save_pdf(f, current_app.config['UPLOAD_FOLDER'], max_bytes=max_pdf_bytes)
            result = DMSService.ingest_document(safe_path, f.filename)
            if result is not None:
                processed += 1
            else:
                skipped_duplicates += 1
        except Exception as e:
            current_app.logger.warning(f'Upload rejected/failed for {f.filename}: {e}')
            errors.append({'file': f.filename, 'reason': str(e)})
    success = processed > 0 or (skipped_duplicates > 0 and not errors)
    return jsonify({'success': success, 'processed': processed, 'skipped_duplicates': skipped_duplicates,
                    'errors': errors, 'total_files': len(files)})


@main_bp.route('/api/system/health')
def system_health():
    result = {'db_connected': False, 'zones_seeded': False, 'upload_folder_writable': False}
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
    result['database_url_source'] = 'DATABASE_URL (custom, e.g. Neon)' if os.environ.get('DATABASE_URL') else 'SQLite מקומי (ברירת מחדל - DATABASE_URL לא הוגדר)'
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
    except Exception:
        current_app.logger.exception('Outlook integration failed')
        return jsonify({'error': 'שגיאת Outlook'}), 500
