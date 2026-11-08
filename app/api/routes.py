from flask import Blueprint, jsonify, request, current_app, render_template, send_file, redirect, session
from app.extensions import db
from app.models import Zone, SystemRequirement, Document, User
from app.services import gemini_document_service as ai_svc
from app.services import document_link_service as link_svc
from app.services.dms_service import DMSService
from app.services import storage
from app.services.document_analysis_service import validity_status
from app.services.document_date_policy_service import (
    apply_document_policy, calculate_document_status, reconcile_audit_summary, STATUS_LABELS, today_israel, document_dates,
)
from app.services.audit_log_service import log as audit_log
from app.utils.security import validate_and_save_pdf
from datetime import date, datetime, timedelta, timezone
import io
import platform
import os
import tempfile
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
    user_id = session.get('user_id')
    if user_id:
        try:
            user = db.session.get(User, user_id)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Could not validate session user for document %s', doc_id)
            user = None
        if user and user.active:
            return True
        session.clear()

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
    return jsonify({'error': 'File not found'}), 404


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
        return jsonify({'error': 'המסמך נמצא באחסון אך לא ניתן להוריד אותו', 'document_id': doc_id}), 502
    base_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, os.path.basename(doc.file_path)))
    if os.path.commonpath([full_path, base_dir]) != base_dir:
        return jsonify({'error': 'Invalid file path'}), 400
    if not os.path.isfile(full_path):
        return jsonify({'error': 'File not found', 'document_id': doc_id}), 404
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
                policy_result = None
                calculated_status = None
                if not latest:
                    label = 'missing'
                else:
                    policy_result = calculate_document_status(
                        *document_dates(latest),
                        policy_year=current_app.config.get('DOCUMENT_POLICY_YEAR', 2026),
                        today=today_israel(),
                        grace_period_days=current_app.config.get('DOCUMENT_GRACE_PERIOD_DAYS', 0),
                        date_extraction_conflict=bool(latest.date_extraction_conflict),
                        date_extraction_confidence=latest.date_extraction_confidence,
                        minimum_date_confidence=current_app.config.get('DOCUMENT_DATE_CONFIDENCE_MIN', 0.80),
                        is_audit_summary=bool(latest.is_audit_summary),
                        date_policy_exempt=bool(latest.date_policy_exempt),
                    )
                    calculated_status = policy_result['status']
                    override_active = bool(
                        latest.manual_status_override and latest.override_expires_at
                        and not latest.is_audit_summary and not latest.date_policy_exempt
                        and latest.override_expires_at > datetime.utcnow()
                    )
                    if override_active:
                        calculated_status = latest.manual_status_override
                    days_left = (document_dates(latest)[1] - today_israel()).days if document_dates(latest)[1] else None
                    if calculated_status == 'active':
                        label = 'valid'
                    elif calculated_status == 'expiring_soon':
                        label = 'critical' if days_left is not None and days_left <= 14 else 'warning'
                    elif calculated_status == 'expired':
                        label = 'expired'
                    else:
                        # Old approvals, future dates, unknown dates and grace-period
                        # records must never be counted as compliant.
                        label = 'needs_review'
                entry = {
                    'req_id': req.id, 'zone_id': zone.id, 'zone_name': zone.zone_name,
                    'file_number': zone.file_number, 'system_name': req.system_name,
                    'required_form': req.required_form, 'doc_id': latest.id if latest else None,
                    'file_path': latest.file_path if latest else None,
                    'file_name': latest.file_name if latest else None,
                    'file_access_url': f'/api/documents/{latest.id}/file' if latest and latest.file_path else None,
                    'issue_date': str(latest.issue_date) if latest and latest.issue_date else None,
                    'expiry_date': str(latest.expiry_date) if latest and latest.expiry_date else None,
                    'status': label, 'calculated_status': calculated_status,
                    'calculated_status_label': STATUS_LABELS.get(calculated_status, calculated_status),
                    'status_reason': policy_result.get('reason') if policy_result else None,
                    'document_year': latest.document_year if latest else None,
                    'doc_count': len(docs), 'doc_names': [d.file_name for d in docs],
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
                                'validity_status': ('not_applicable' if d.is_audit_summary or d.date_policy_exempt else ('missing' if not d.file_path else validity_status(d.expiry_date))),
                                'ai_status': d.ai_status,
                                'ai_summary': d.ai_summary,
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
    date_warnings = []
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
                if result.calculated_status in {'future_issue_date', 'date_conflict', 'needs_manual_review', 'old_approval', 'expired', 'grace_period'}:
                    date_warnings.append({
                        'file': result.file_name,
                        'status': result.calculated_status,
                        'status_label': STATUS_LABELS.get(result.calculated_status, result.calculated_status),
                        'message': 'המסמך נשמר, אך אינו נספר כאישור תקף עד להשלמת בדיקה/תיקון.',
                        'blocked_from_compliance': True,
                    })
            else:
                skipped_duplicates += 1
        except Exception as e:
            current_app.logger.warning(f'Upload rejected/failed for {f.filename}: {e}')
            errors.append({'file': f.filename, 'reason': str(e)})
    success = processed > 0 or (skipped_duplicates > 0 and not errors)
    return jsonify({'success': success, 'processed': processed, 'skipped_duplicates': skipped_duplicates,
                    'errors': errors, 'date_warnings': date_warnings, 'total_files': len(files)})


@main_bp.route('/document-intelligence')
def document_intelligence_page():
    if not session.get('user_id'):
        return redirect('/login')
    return render_template('document_intelligence.html', active_nav='document_intelligence', user_role=session.get('role'))


def _ai_document_payload(doc, include_reconciliation=False):
    date_result = calculate_document_status(
        *document_dates(doc),
        policy_year=current_app.config.get('DOCUMENT_POLICY_YEAR', 2026),
        grace_period_days=current_app.config.get('DOCUMENT_GRACE_PERIOD_DAYS', 0),
        date_extraction_conflict=bool(doc.date_extraction_conflict),
        date_extraction_confidence=doc.date_extraction_confidence,
        minimum_date_confidence=current_app.config.get('DOCUMENT_DATE_CONFIDENCE_MIN', 0.80),
        is_audit_summary=bool(doc.is_audit_summary),
        date_policy_exempt=bool(doc.date_policy_exempt),
    )
    calculated_status = date_result['status']
    override_active = bool(
        doc.manual_status_override and doc.override_expires_at
        and not doc.is_audit_summary and not doc.date_policy_exempt
        and doc.override_expires_at > datetime.utcnow()
    )
    return {
        'document_id': doc.id,
        'file_name': doc.file_name,
        'ai_status': doc.ai_status,
        'processing_stale': ai_svc.is_processing_stale(doc, stale_after_minutes=current_app.config.get('GEMINI_PROCESSING_STALE_MINUTES', 30)),
        'ai_model': doc.ai_model,
        'ai_analyzed_at': doc.ai_analyzed_at.isoformat() if doc.ai_analyzed_at else None,
        'document_type': doc.ai_document_type,
        'summary': doc.ai_summary,
        'findings': ai_svc.findings(doc),
        'supplemental': ai_svc.actions(doc),
        'confidence': doc.ai_confidence,
        'error': doc.ai_error,
        'review_required': doc.analysis_review_required,
        'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
        'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None,
        'document_year': doc.document_year if doc.document_year is not None else (doc.issue_date.year if doc.issue_date and not doc.is_audit_summary and not doc.date_policy_exempt else None),
        'calculated_status': calculated_status,
        'calculated_status_label': STATUS_LABELS.get(calculated_status, calculated_status),
        'date_verification_status': doc.date_verification_status,
        'date_status_reason': date_result['reason'],
        'date_reviewed_at': doc.date_reviewed_at.isoformat() if doc.date_reviewed_at else None,
        'date_extraction_source': doc.date_extraction_source,
        'date_extraction_confidence': doc.date_extraction_confidence,
        'date_extraction_conflict': bool(doc.date_extraction_conflict),
        'gemini_issue_date': doc.gemini_issue_date.isoformat() if doc.gemini_issue_date else None,
        'gemini_expiry_date': doc.gemini_expiry_date.isoformat() if doc.gemini_expiry_date else None,
        'is_multi_year': bool(doc.is_multi_year),
        'is_audit_summary': bool(doc.is_audit_summary),
        'date_policy_exempt': bool(doc.date_policy_exempt),
        'audit_year': doc.audit_year,
        'effective_status': doc.manual_status_override if override_active else calculated_status,
        'manual_status_override': doc.manual_status_override if override_active else None,
        'override_reason': doc.override_reason if override_active else None,
        'reconciliation': reconcile_audit_summary(doc) if include_reconciliation and doc.is_audit_summary else None,
        'relationships': {'site_id': doc.site_id, 'audit_id': doc.audit_id, 'supplier_id': doc.supplier_id},
        'relationship_review_required': doc.ai_status == 'completed' and not (doc.site_id or doc.audit_id or doc.supplier_id),
    }


@main_bp.route('/api/document-intelligence/<int:doc_id>')
def document_intelligence_detail(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({'error': 'המסמך לא נמצא'}), 404
    return jsonify(_ai_document_payload(doc, include_reconciliation=True))


def _parse_document_date(value, field_name):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"תאריך {field_name} חייב להיות בפורמט YYYY-MM-DD")


@main_bp.route('/api/documents/<int:doc_id>/date-review', methods=['POST'])
def document_date_review(doc_id):
    """Manager-level correction of dates after manual inspection of the source PDF."""
    document = db.session.get(Document, doc_id)
    if not document or document.status in {'deleted', 'archived'}:
        return jsonify({'error': 'המסמך לא נמצא או אינו פעיל'}), 404
    if document.is_audit_summary or document.date_policy_exempt:
        return jsonify({'error': 'המסמך אינו אישור בעל תוקף ולכן אין לתקן בו תאריכי תוקף', 'code': 'DATE_POLICY_NOT_APPLICABLE'}), 409
    data = request.get_json(silent=True) or {}
    if 'issue_date' not in data and 'expiry_date' not in data:
        return jsonify({'error': 'יש למסור לפחות תאריך אחד לתיקון'}), 400
    try:
        issue_date = _parse_document_date(data.get('issue_date'), 'הנפקה') if 'issue_date' in data else document.issue_date
        expiry_date = _parse_document_date(data.get('expiry_date'), 'תפוגה') if 'expiry_date' in data else document.expiry_date
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    today = today_israel()
    if 'issue_date' in data and issue_date is None:
        return jsonify({'error': 'תאריך הנפקה נדרש; אם אינו מופיע במסמך יש להעביר לבדיקה ידנית'}), 400
    if issue_date and issue_date > today:
        return jsonify({'error': 'תאריך ההנפקה אינו יכול להיות בעתיד', 'code': 'FUTURE_ISSUE_DATE'}), 422
    if (issue_date and issue_date.year < 1900) or (expiry_date and expiry_date.year < 1900):
        return jsonify({'error': 'התאריך מוקדם באופן חריג (לפני 1900). יש לבדוק את המסמך המקורי.', 'code': 'IMPLAUSIBLE_DATE'}), 422
    if issue_date and expiry_date and expiry_date < issue_date:
        return jsonify({'error': 'תאריך התפוגה אינו יכול להיות מוקדם מתאריך ההנפקה', 'code': 'EXPIRY_BEFORE_ISSUE'}), 422

    old_values = {
        'issue_date': document.issue_date.isoformat() if document.issue_date else None,
        'expiry_date': document.expiry_date.isoformat() if document.expiry_date else None,
    }
    document.issue_date = issue_date
    document.expiry_date = expiry_date
    document.date_reviewed_at = datetime.utcnow()
    document.date_extraction_source = 'manual'
    document.date_extraction_confidence = 1.0
    document.date_extraction_conflict = False
    document.analysis_review_required = False
    # A corrected source date invalidates a previous exception; recalculate from evidence.
    document.manual_status_override = None
    document.override_reason = None
    document.override_by = None
    document.override_at = None
    document.override_expires_at = None
    result = apply_document_policy(document)
    audit_log(
        'update', 'document_date', document.id, document.file_name,
        old_values,
        {'issue_date': issue_date.isoformat() if issue_date else None,
         'expiry_date': expiry_date.isoformat() if expiry_date else None,
         'calculated_status': result['status']},
    )
    db.session.commit()
    return jsonify({
        'success': True,
        'document_id': document.id,
        'calculated_status': result['status'],
        'status_label': STATUS_LABELS.get(result['status'], result['status']),
        'date_verification_status': result['verification'],
        'reason': result['reason'],
    })


@main_bp.route('/api/admin/documents/recalculate-date-policy', methods=['POST'])
def recalculate_document_date_policy():
    """Admin-only full recalculation after an approved policy-year change."""
    documents = Document.query.filter(Document.status.notin_(['deleted', 'archived'])).all()
    counts = {}
    for document in documents:
        result = apply_document_policy(document)
        counts[result['status']] = counts.get(result['status'], 0) + 1
    audit_log(
        'update', 'document_date_policy', None, 'Recalculation of document date policy',
        None,
        {'policy_year': current_app.config.get('DOCUMENT_POLICY_YEAR', 2026),
         'documents_processed': len(documents), 'status_counts': counts},
    )
    db.session.commit()
    return jsonify({
        'success': True,
        'policy_year': current_app.config.get('DOCUMENT_POLICY_YEAR', 2026),
        'documents_processed': len(documents),
        'status_counts': counts,
    })


@main_bp.route('/api/documents/<int:doc_id>/date-override', methods=['POST'])
def document_date_override(doc_id):
    """Admin-only, reasoned exception. Calculated status remains unchanged."""
    document = db.session.get(Document, doc_id)
    if document and document.is_audit_summary:
        return jsonify({'error': 'סיכום ביקורת אינו אישור בעל תוקף ולכן לא ניתן להחיל עליו חריג תוקף', 'code': 'AUDIT_SUMMARY_NOT_CERTIFICATE'}), 409
    if document and document.date_policy_exempt:
        return jsonify({'error': 'המסמך אינו אישור בעל תוקף ולכן לא ניתן להחיל עליו חריג תוקף', 'code': 'DATE_POLICY_NOT_APPLICABLE'}), 409
    if not document or document.status in {'deleted', 'archived'}:
        return jsonify({'error': 'המסמך לא נמצא או אינו פעיל'}), 404
    data = request.get_json(silent=True) or {}
    allowed = {'active', 'old_approval', 'expired', 'grace_period', 'needs_manual_review'}
    override_status = str(data.get('status') or '').strip()
    reason = str(data.get('reason') or '').strip()
    if override_status not in allowed:
        return jsonify({'error': 'סטטוס החריג אינו מותר'}), 400
    if len(reason) < 10:
        return jsonify({'error': 'נדרשת סיבת חריג מפורטת (לפחות 10 תווים)'}), 400

    expiry_value = data.get('expires_at')
    try:
        if expiry_value:
            parsed_expiry = datetime.fromisoformat(str(expiry_value).replace('Z', '+00:00'))
            override_expires_at = (
                parsed_expiry.astimezone(timezone.utc).replace(tzinfo=None)
                if parsed_expiry.tzinfo else parsed_expiry
            )
        else:
            override_expires_at = datetime.utcnow() + timedelta(days=90)
    except (TypeError, ValueError):
        return jsonify({'error': 'תאריך פקיעת החריג אינו תקין'}), 400
    if override_expires_at <= datetime.utcnow():
        return jsonify({'error': 'תוקף החריג חייב להיות בעתיד'}), 400
    calculated = apply_document_policy(document)
    if (calculated['status'] in {'future_issue_date', 'date_conflict'} or calculated['verification'] == 'implausible_date' or document.date_extraction_conflict or (document.date_extraction_confidence is not None and document.date_extraction_confidence < current_app.config.get('DOCUMENT_DATE_CONFIDENCE_MIN', 0.80))) and override_status == 'active':
        return jsonify({'error': 'יש לתקן ולאמת את התאריכים לפני אישור המסמך', 'code': 'DATE_CORRECTION_REQUIRED'}), 409

    old_values = {
        'manual_status_override': document.manual_status_override,
        'override_reason': document.override_reason,
        'override_expires_at': document.override_expires_at.isoformat() if document.override_expires_at else None,
    }
    document.manual_status_override = override_status
    document.override_reason = reason
    document.override_by = session.get('user_id')
    document.override_at = datetime.utcnow()
    document.override_expires_at = override_expires_at
    audit_log(
        'update', 'document_status_override', document.id, document.file_name,
        old_values,
        {'manual_status_override': override_status, 'reason': reason,
         'override_expires_at': override_expires_at.isoformat()},
    )
    db.session.commit()
    return jsonify({
        'success': True,
        'document_id': document.id,
        'calculated_status': document.calculated_status,
        'effective_status': override_status,
        'override_expires_at': override_expires_at.isoformat(),
    })


@main_bp.route('/api/document-intelligence/documents')
def document_intelligence_documents():
    docs = (
        Document.query
        .filter(Document.status.notin_(['deleted', 'archived']))
        .order_by(Document.uploaded_at.desc(), Document.id.desc())
        .all()
    )
    return jsonify({
        'documents': [_ai_document_payload(doc) for doc in docs],
        'total': len(docs),
    })


@main_bp.route('/api/document-intelligence/<int:doc_id>/analyze', methods=['POST'])
def document_intelligence_analyze(doc_id):
    if not ai_svc.is_configured():
        return jsonify({'error': 'Gemini אינו מוגדר. הגדר GEMINI_API_KEY ב-Render.'}), 503

    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({'error': 'המסמך לא נמצא'}), 404
    if doc.status in {'deleted', 'archived'}:
        return jsonify({'error': 'לא ניתן לנתח מסמך שנמחק או הועבר לארכיון'}), 409
    try:
        result = ai_svc.analyze_and_persist(doc.id)
        doc = db.session.get(Document, doc.id)
        return jsonify(_ai_document_payload(doc) | {'result': result}), 200
    except ai_svc.DocumentAnalysisInProgress as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'ai_status': 'processing'}), 409
    except Exception:
        current_app.logger.exception('Web Gemini analysis failed for document %s', doc_id)
        doc = db.session.get(Document, doc_id)
        return jsonify({
            'error': doc.ai_error if doc else 'שגיאת Gemini בניתוח המסמך',
            'document_id': doc_id,
            'ai_status': 'failed',
        }), 502


@main_bp.route('/api/document-intelligence/<int:doc_id>/context', methods=['GET'])
def document_intelligence_context(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({'error': 'המסמך לא נמצא'}), 404
    try:
        links = link_svc.resolve_document(doc, persist=False)
        return jsonify({
            'document_id': doc.id,
            'file_name': doc.file_name,
            'links': links,
            'current': {'site_id': doc.site_id, 'audit_id': doc.audit_id, 'supplier_id': doc.supplier_id},
        })
    except Exception as exc:
        current_app.logger.exception('Document relationship resolution failed for %s', doc_id)
        return jsonify({'error': str(exc)}), 500


@main_bp.route('/api/document-intelligence/<int:doc_id>/links', methods=['POST'])
def document_intelligence_links(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({'error': 'המסמך לא נמצא'}), 404
    try:
        document, links = link_svc.apply_links(doc.id, request.get_json(silent=True) or {})
        return jsonify({
            'success': True,
            'current': {'site_id': document.site_id, 'audit_id': document.audit_id, 'supplier_id': document.supplier_id},
            'links': links,
        })
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Document relationship link update failed for %s', doc_id)
        return jsonify({'error': 'שגיאה בעדכון קשרי המסמך'}), 500


@main_bp.route('/api/document-intelligence/<int:doc_id>/create-actions', methods=['POST'])
def document_intelligence_create_actions(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc:
        return jsonify({'error': 'המסמך לא נמצא'}), 404
    if doc.ai_status != 'completed':
        return jsonify({'error': 'יש להשלים ניתוח AI לפני יצירת פעולות'}), 409
    try:
        return jsonify(ai_svc.create_operational_actions(doc))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('AI action creation failed')
        return jsonify({'error': str(exc)}), 500


@main_bp.route('/api/document-intelligence/overview')
def document_intelligence_overview():
    docs = Document.query.filter(Document.status.notin_(['deleted', 'archived'])).all()
    status_counts = {}
    severity_counts = {}
    recurring = {}
    missing_items = []
    contradictions = []
    actions = []
    relationship_review_required = 0

    for doc in docs:
        status_counts[doc.ai_status] = status_counts.get(doc.ai_status, 0) + 1
        if doc.ai_status != 'completed':
            continue
        if not (doc.site_id or doc.audit_id or doc.supplier_id):
            relationship_review_required += 1
        for finding in ai_svc.findings(doc):
            severity = finding.get('severity') or 'unclear'
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            title = ' '.join(str(finding.get('title') or '').lower().split())
            if title:
                item = recurring.setdefault(title, {
                    'title': finding.get('title'),
                    'count': 0,
                    'severity': severity,
                    'documents': []
                })
                item['count'] += 1
                item['documents'].append({'id': doc.id, 'file_name': doc.file_name})

        extra = ai_svc.actions(doc)
        for value in extra.get('missing_items', []):
            missing_items.append({'document_id': doc.id, 'file_name': doc.file_name, 'item': value})
        for value in extra.get('contradictions', []):
            contradictions.append({'document_id': doc.id, 'file_name': doc.file_name, 'item': value})
        for finding in ai_svc.findings(doc):
            if finding.get('recommended_action'):
                actions.append({
                    'document_id': doc.id,
                    'file_name': doc.file_name,
                    'title': finding.get('title'),
                    'action': finding.get('recommended_action'),
                    'severity': finding.get('severity')
                })

    recurring_items = sorted(
        (x for x in recurring.values() if x['count'] > 1),
        key=lambda x: (-x['count'], x['title'] or '')
    )[:20]

    return jsonify({
        'total_documents': len(docs),
        'status_counts': status_counts,
        'severity_counts': severity_counts,
        'review_required': sum(1 for d in docs if d.analysis_review_required),
        'relationship_review_required': relationship_review_required,
        'recurring_findings': recurring_items,
        'missing_items': missing_items[:50],
        'contradictions': contradictions[:50],
        'top_actions': sorted(
            actions,
            key=lambda x: {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4, 'unclear': 5}.get(x['severity'], 6)
        )[:30],
    })


@main_bp.route('/api/system/health')
def system_health():
    """Public, side-effect-light readiness probe for Render and GitHub Actions."""
    storage_required = bool(current_app.config.get(
        'REQUIRE_SUPABASE_STORAGE',
        current_app.config.get('IS_PRODUCTION', False),
    ))
    result = {
        'status': 'degraded',
        'production_mode': bool(current_app.config.get('IS_PRODUCTION')),
        'secret_key_from_environment': bool(current_app.config.get('SECRET_KEY_FROM_ENV')),
        'db_connected': False,
        'zones_seeded': False,
        'upload_folder_writable': False,
        'supabase_required': storage_required,
        'supabase_configured': False,
        'storage_connected': False,
        'gemini_configured': bool(current_app.config.get('GEMINI_API_KEY')),
        'db_backend': None,
        'db_host': None,
        'schema_revision': None,
    }

    try:
        result['db_backend'] = db.engine.url.get_backend_name()
        result['db_host'] = db.engine.url.host
        try:
            from sqlalchemy import text
            result['schema_revision'] = db.session.execute(
                text('SELECT version_num FROM alembic_version')
            ).scalar()
        except Exception:
            current_app.logger.exception('Health check Alembic revision probe failed')
        zone_count = Zone.query.count()
        result['db_connected'] = True
        result['zones_seeded'] = zone_count > 0
        result['zone_count'] = zone_count
    except Exception:
        current_app.logger.exception('Health check database probe failed')

    try:
        with tempfile.NamedTemporaryFile(
            prefix='.healthcheck-',
            dir=current_app.config['UPLOAD_FOLDER'],
            delete=True,
        ) as probe_file:
            probe_file.write(b'ok')
            probe_file.flush()
        result['upload_folder_writable'] = True
    except Exception:
        current_app.logger.exception('Health check upload-folder probe failed')

    try:
        result['supabase_configured'] = storage.is_configured()
        if result['supabase_configured']:
            connected, storage_error = storage.check_connection()
            result['storage_connected'] = bool(connected)
            if not connected:
                current_app.logger.warning(
                    'Health check Supabase Storage probe failed: %s',
                    storage_error or 'unknown storage error',
                )
        elif not storage_required:
            result['storage_note'] = 'Supabase is not configured; local storage fallback is enabled'
    except Exception:
        current_app.logger.exception('Health check Supabase Storage probe failed')
        result['storage_connected'] = False

    storage_ready = (
        not storage_required or
        (result['supabase_configured'] and result['storage_connected'])
    )
    ready = (
        result['db_connected'] and
        result['zones_seeded'] and
        result['upload_folder_writable'] and
        storage_ready
    )
    result['status'] = 'ok' if ready else 'degraded'
    return jsonify(result), (200 if ready else 503)

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
