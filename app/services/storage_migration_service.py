"""Safe migration/recovery helpers for legacy Document.file_path values."""
from __future__ import annotations

import hashlib
import os
import posixpath
import zipfile
from io import BytesIO

from app.extensions import db
from app.models import Document
from app.services import storage
from app.services import audit_log_service as alog


def scan_legacy_documents(upload_folder: str) -> dict:
    """Classify legacy Document.file_path values without modifying data."""
    docs = Document.query.filter(Document.status != 'deleted').all()
    inventory = storage.list_supabase_files() if storage.is_configured() else []
    inventory_names = [item.get('filename') for item in inventory if item.get('filename')]
    rows = []
    counts = {'native': 0, 'recoverable_supabase': 0, 'migratable_local': 0, 'missing': 0, 'ambiguous': 0}

    for doc in docs:
        if not doc.file_path:
            counts['missing'] += 1
            rows.append({'document_id': doc.id, 'file_name': doc.file_name, 'file_path': None, 'state': 'missing'})
            continue
        if storage.is_supabase_path(doc.file_path):
            counts['native'] += 1
            rows.append({'document_id': doc.id, 'file_name': doc.file_name, 'file_path': doc.file_path, 'state': 'native'})
            continue
        basename = os.path.basename(doc.file_path)
        local_path = os.path.join(upload_folder, basename)
        if os.path.isfile(local_path):
            counts['migratable_local'] += 1
            rows.append({'document_id': doc.id, 'file_name': doc.file_name, 'file_path': doc.file_path, 'state': 'migratable_local'})
            continue
        matches = [name for name in inventory_names if name == basename]
        if len(matches) == 1:
            counts['recoverable_supabase'] += 1
            rows.append({'document_id': doc.id, 'file_name': doc.file_name, 'file_path': doc.file_path, 'state': 'recoverable_supabase', 'resolved_path': f'{storage.get_bucket_name()}/{basename}'})
        elif len(matches) > 1:
            counts['ambiguous'] += 1
            rows.append({'document_id': doc.id, 'file_name': doc.file_name, 'file_path': doc.file_path, 'state': 'ambiguous'})
        else:
            counts['missing'] += 1
            rows.append({'document_id': doc.id, 'file_name': doc.file_name, 'file_path': doc.file_path, 'state': 'missing'})
    return {'counts': counts, 'items': rows}


def migrate(upload_folder: str, acting_user_id) -> dict:
    """Migrate/relink safe legacy records; never deletes source data."""
    if not storage.is_configured():
        return {'success': False, 'error': 'Supabase אינו מוגדר', 'migrated': [], 'failed': []}
    report = scan_legacy_documents(upload_folder)
    migrated, failed = [], []
    for item in report['items']:
        if item['state'] not in {'migratable_local', 'recoverable_supabase'}:
            continue
        doc = db.session.get(Document, item['document_id'])
        if not doc or doc.status == 'deleted':
            continue
        old_path = doc.file_path
        try:
            if item['state'] == 'recoverable_supabase':
                new_path = item['resolved_path']
            else:
                local_path = os.path.join(upload_folder, os.path.basename(old_path))
                with open(local_path, 'rb') as f:
                    data = f.read()
                new_path = storage.upload_bytes(os.path.basename(old_path), data)
            doc.file_path = new_path
            db.session.commit()
            alog.log('document_storage_migrated', 'document', doc.id, entity_label=doc.file_name,
                     old_value={'file_path': old_path}, new_value={'file_path': new_path})
            db.session.commit()
            migrated.append({'document_id': doc.id, 'file_name': doc.file_name, 'old_path': old_path, 'new_path': new_path})
        except Exception as exc:
            db.session.rollback()
            failed.append({'document_id': doc.id, 'file_name': doc.file_name, 'error': str(exc)})
    return {'success': not failed, 'migrated': migrated, 'failed': failed, 'report': scan_legacy_documents(upload_folder)}


def _norm(value: str) -> str:
    value = (value or '').replace('\\', '/').strip('/')
    while '//' in value:
        value = value.replace('//', '/')
    return value.lower()


def _path_variants(value: str) -> set[str]:
    normalized = _norm(value)
    if not normalized:
        return set()
    variants = {normalized}
    for prefix in ('uploads/', './uploads/', 'upload/', './upload/'):
        if normalized.startswith(prefix):
            variants.add(normalized[len(prefix):])
    marker = '/uploads/'
    if marker in normalized:
        variants.add(normalized.split(marker, 1)[1])
    return {v.strip('/') for v in variants if v.strip('/')}


def _zip_entries(zip_bytes: bytes) -> list[dict]:
    entries = []
    with zipfile.ZipFile(BytesIO(zip_bytes), 'r') as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            raw = info.filename.replace('\\', '/')
            normalized = posixpath.normpath(raw).lstrip('/')
            if normalized.startswith('../') or normalized == '..':
                continue
            data = zf.read(info)
            entries.append({'zip_path': normalized, 'basename': posixpath.basename(normalized), 'data': data,
                            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    return entries


def _match_document(doc: Document, entries: list[dict]) -> tuple[dict | None, str, list[str]]:
    path_values = []
    for value in (doc.file_path, doc.file_name):
        path_values.extend(_path_variants(value))
    path_values = list(dict.fromkeys(path_values))
    exact_matches = []
    for entry in entries:
        entry_variants = _path_variants(entry['zip_path'])
        if any(candidate in entry_variants for candidate in path_values):
            exact_matches.append(entry)
    if len(exact_matches) == 1:
        return exact_matches[0], 'exact_path', []
    if len(exact_matches) > 1:
        return None, 'ambiguous', [x['zip_path'] for x in exact_matches]
    basename = _norm(os.path.basename(doc.file_name or doc.file_path or ''))
    by_base = [e for e in entries if _norm(e['basename']) == basename] if basename else []
    if len(by_base) == 1:
        return by_base[0], 'basename', []
    if len(by_base) > 1:
        return None, 'ambiguous', [x['zip_path'] for x in by_base]
    legacy_base = _norm(os.path.basename(doc.file_path or ''))
    by_legacy = [e for e in entries if _norm(e['basename']) == legacy_base] if legacy_base else []
    if len(by_legacy) == 1:
        return by_legacy[0], 'legacy_basename', []
    if len(by_legacy) > 1:
        return None, 'ambiguous', [x['zip_path'] for x in by_legacy]
    return None, 'missing', []


def _safe_restore_name(doc_id: int, entry: dict) -> str:
    """Create an ASCII-only, deterministic Storage object key."""
    digest = entry['sha256']
    extension = '.pdf' if entry['basename'].lower().endswith('.pdf') else ''
    return f'restored/{doc_id}/{digest}{extension}'


def _validate_native_storage(doc: Document) -> dict:
    """Actually download a native Supabase object and validate it."""
    result = {'healthy': False, 'path': doc.file_path, 'bytes': None, 'sha256': None,
              'pdf_valid': False, 'error': None}
    try:
        data = storage.download_bytes(doc.file_path)
        result['bytes'] = len(data)
        result['sha256'] = hashlib.sha256(data).hexdigest()
        if doc.file_hash and result['sha256'] != doc.file_hash:
            result['error'] = 'SHA-256 של הקובץ ב-Supabase אינו תואם ל-DB'
            return result
        if doc.file_size is not None and len(data) != int(doc.file_size):
            result['error'] = 'גודל הקובץ ב-Supabase אינו תואם ל-DB'
            return result
        if (doc.file_name or '').lower().endswith('.pdf') or (doc.file_path or '').lower().endswith('.pdf'):
            validation = storage.verify_pdf_bytes(data)
            result['pdf_valid'] = bool(validation.get('status'))
            if not result['pdf_valid']:
                result['error'] = validation.get('error') or 'PDF לא תקין'
                return result
        else:
            result['pdf_valid'] = True
        result['healthy'] = True
        return result
    except Exception as exc:
        result['error'] = str(exc)
        return result


def plan_zip_restore(zip_bytes: bytes, document_id: int | None = None, validate_native: bool = True) -> dict:
    """Create a non-mutating recovery plan from a ZIP backup.

    Preview validates existing native objects. Restore can skip that repeated
    validation because the Preview has already established native integrity;
    the actual replacement files are independently verified after upload.
    """
    if not storage.is_configured():
        return {'success': False, 'error': 'Supabase אינו מוגדר', 'items': [], 'counts': {}}
    try:
        entries = _zip_entries(zip_bytes)
    except zipfile.BadZipFile:
        return {'success': False, 'error': 'קובץ ZIP אינו תקין', 'items': [], 'counts': {}}
    query = Document.query.filter(Document.status != 'deleted')
    if document_id:
        query = query.filter(Document.id == document_id)
    docs = query.order_by(Document.id.asc()).all()
    counts = {'matched': 0, 'ambiguous': 0, 'missing': 0, 'invalid_pdf': 0, 'skipped_native': 0, 'unhealthy_native': 0}
    items = []
    for doc in docs:
        if storage.is_supabase_path(doc.file_path):
            native = _validate_native_storage(doc) if validate_native else {'healthy': True, 'bytes': None, 'sha256': None, 'error': None}
            if native['healthy']:
                counts['skipped_native'] += 1
                item = {'document_id': doc.id, 'file_name': doc.file_name, 'status': 'skipped_native',
                        'reason': ('קובץ Supabase קיים, ניתן להורדה ועבר אימות SHA/PDF' if validate_native
                                   else 'קיים ב-Supabase; אומת ב-Preview, אין צורך בבדיקה כפולה'),
                        'storage_path': doc.file_path}
                if validate_native:
                    item.update({'bytes': native['bytes'], 'sha256': native['sha256']})
                items.append(item)
                continue
            counts['unhealthy_native'] += 1
            native_reason = native['error'] or 'קובץ Supabase אינו זמין/תקין'
        else:
            native_reason = None

        entry, method, candidates = _match_document(doc, entries)
        if not entry:
            counts[method] += 1
            item = {'document_id': doc.id, 'file_name': doc.file_name, 'status': method, 'candidates': candidates}
            if native_reason:
                item.update({'previous_storage_status': 'unhealthy_native', 'previous_storage_error': native_reason})
            items.append(item)
            continue
        validation = storage.verify_pdf_bytes(entry['data']) if entry['basename'].lower().endswith('.pdf') else {'status': True, 'error': None}
        if not validation.get('status'):
            counts['invalid_pdf'] += 1
            item = {'document_id': doc.id, 'file_name': doc.file_name, 'status': 'invalid_pdf', 'source': entry['zip_path'], 'error': validation.get('error')}
            if native_reason:
                item.update({'previous_storage_status': 'unhealthy_native', 'previous_storage_error': native_reason})
            items.append(item)
            continue
        counts['matched'] += 1
        remote_name = _safe_restore_name(doc.id, entry)
        item = {'document_id': doc.id, 'file_name': doc.file_name, 'status': 'matched', 'match_method': method,
                'source': entry['zip_path'], 'size': entry['size'], 'sha256': entry['sha256'],
                'storage_path': f'{storage.get_bucket_name()}/{remote_name}'}
        if native_reason:
            item.update({'reason': 'ה-DB הצביע ל-Supabase אך הקובץ הקיים לא עבר בדיקת הורדה/שלמות; יוחלף מהגיבוי',
                         'previous_storage_status': 'unhealthy_native', 'previous_storage_error': native_reason})
        items.append(item)
    return {'success': True, 'zip_files': len(entries), 'counts': counts, 'items': items}


def restore_zip(zip_bytes: bytes, acting_user_id, document_id: int | None = None) -> dict:
    """Restore matched ZIP files; verify every uploaded object before DB update."""
    plan = plan_zip_restore(zip_bytes, document_id, validate_native=False)
    if not plan.get('success'):
        return plan
    entries = {e['zip_path']: e for e in _zip_entries(zip_bytes)}
    restored, failed = [], []
    for item in plan['items']:
        if item['status'] != 'matched':
            continue
        doc = db.session.get(Document, item['document_id'])
        entry = entries.get(item['source'])
        if not doc or not entry:
            failed.append({'document_id': item['document_id'], 'error': 'מסמך/קובץ מקור לא נמצא'})
            continue
        try:
            remote_name = _safe_restore_name(doc.id, entry)
            stored_path = storage.upload_bytes(remote_name, entry['data'],
                                               'application/pdf' if entry['basename'].lower().endswith('.pdf') else 'application/octet-stream')
            downloaded = storage.download_bytes(stored_path)
            actual_hash = hashlib.sha256(downloaded).hexdigest()
            if actual_hash != entry['sha256'] or len(downloaded) != entry['size']:
                raise RuntimeError('אימות העלאה נכשל: hash או גודל אינם תואמים')
            if entry['basename'].lower().endswith('.pdf'):
                validation = storage.verify_pdf_bytes(downloaded)
                if not validation.get('status'):
                    raise RuntimeError(validation.get('error') or 'PDF verification failed')
            old_path = doc.file_path
            doc.file_path = stored_path
            doc.file_hash = entry['sha256']
            doc.file_size = entry['size']
            db.session.commit()
            try:
                alog.log('document_storage_restored', 'document', doc.id, entity_label=doc.file_name,
                         old_value={'file_path': old_path}, new_value={'file_path': stored_path})
                db.session.commit()
            except Exception:
                db.session.rollback()
            restored.append({'document_id': doc.id, 'file_name': doc.file_name, 'source': entry['zip_path'],
                             'storage_path': stored_path, 'sha256': actual_hash, 'size': len(downloaded)})
        except Exception as exc:
            db.session.rollback()
            failed.append({'document_id': doc.id, 'file_name': doc.file_name, 'error': str(exc)})
    return {'success': not failed, 'restored': restored, 'failed': failed, 'plan': plan}
