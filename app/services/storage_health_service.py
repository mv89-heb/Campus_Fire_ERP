"""
Service Layer עבור Storage Health Check.

Scan/Preview are read-only. Cleanup deletes only after an explicit admin
confirmation and a fresh orphan re-check.
"""
import logging
import os
from datetime import datetime

from app.extensions import db
from app.models import Document
from app.services import storage
from app.services import auth_service
from app.services import audit_log_service as alog

logger = logging.getLogger(__name__)


def _resolved_supabase_reference(file_path: str, inventory: list) -> str | None:
    """Return the canonical bucket/path reference for a DB file_path."""
    if not file_path or not storage.is_configured():
        return None
    if storage.is_supabase_path(file_path):
        return file_path
    return storage.find_supabase_legacy_path(file_path, inventory=inventory)


def scan(upload_folder: str) -> dict:
    """Read-only storage/DB consistency scan.

    Important: legacy DB paths are resolved before orphan detection. Without
    this normalization, a healthy Supabase object referenced by an old DB path
    could incorrectly be reported as an orphan.
    """
    all_docs = Document.query.all()
    relevant_docs = [d for d in all_docs if d.status != 'deleted' and d.file_path]

    bucket_files = storage.list_supabase_files() if storage.is_configured() else []
    bucket = storage.get_bucket_name() if storage.is_configured() else None

    missing_items = []
    hash_error_items = []
    healthy_count = 0
    referenced_supabase_paths = set()
    referenced_local_basenames = set()

    for doc in relevant_docs:
        referenced_local_basenames.add(os.path.basename(doc.file_path or ''))

        resolved_supabase = _resolved_supabase_reference(doc.file_path, bucket_files)
        if resolved_supabase:
            referenced_supabase_paths.add(resolved_supabase)
            # Do not download every Supabase object on every dashboard scan;
            # existence is checked by Storage's signed URL probe. Full SHA/PDF
            # validation remains available through recovery Preview.
            result = storage.file_exists(resolved_supabase, upload_folder)
            if result.get('status'):
                healthy_count += 1
            else:
                missing_items.append({
                    'document_id': doc.id,
                    'file_name': doc.file_name,
                    'file_path': doc.file_path,
                    'resolved_path': resolved_supabase,
                })
            continue

        local_path = os.path.abspath(os.path.join(upload_folder, os.path.basename(doc.file_path)))
        base_dir = os.path.abspath(upload_folder)
        try:
            safe_local = os.path.commonpath([local_path, base_dir]) == base_dir
        except ValueError:
            safe_local = False

        if safe_local and os.path.isfile(local_path):
            try:
                actual_hash = storage.calculate_file_hash(local_path)
            except Exception as e:
                missing_items.append({
                    'document_id': doc.id,
                    'file_name': doc.file_name,
                    'file_path': doc.file_path,
                    'note': f'נמצא אך לא ניתן לקריאה: {e}',
                })
                continue
            if doc.file_hash and actual_hash != doc.file_hash:
                hash_error_items.append({
                    'document_id': doc.id,
                    'file_name': doc.file_name,
                    'expected_hash': doc.file_hash,
                    'actual_hash': actual_hash,
                })
                continue
            healthy_count += 1
            continue

        missing_items.append({
            'document_id': doc.id,
            'file_name': doc.file_name,
            'file_path': doc.file_path,
        })

    # --- Storage -> DB: locate true orphans only ---
    orphaned_items = []

    for f in storage.list_local_files(upload_folder):
        if f['filename'] not in referenced_local_basenames:
            orphaned_items.append({
                'path': f['filename'],
                'size': f['size'],
                'location': 'local',
                'modified_at': f.get('modified_at'),
                'reason': 'קובץ פיזי בדיסק המקומי ללא רשומת Document שמפנה אליו',
            })

    if bucket:
        for f in bucket_files:
            object_name = f.get('filename') or ''
            full_ref = f'{bucket}/{object_name}'
            if full_ref not in referenced_supabase_paths:
                orphaned_items.append({
                    'path': full_ref,
                    'size': f.get('size'),
                    'location': 'supabase',
                    'modified_at': f.get('modified_at'),
                    'reason': 'קובץ ב-Supabase Storage ללא רשומת Document שמפנה אליו',
                })

    return {
        'scanned_at': datetime.utcnow().isoformat(),
        'total_documents': len(relevant_docs),
        'healthy': healthy_count,
        'missing': len(missing_items),
        'orphaned': len(orphaned_items),
        'hash_errors': len(hash_error_items),
        'missing_items': missing_items,
        'orphaned_items': orphaned_items,
        'hash_error_items': hash_error_items,
    }


def cleanup_preview(upload_folder: str) -> list:
    """Preview only; nothing is deleted."""
    result = scan(upload_folder)
    return result['orphaned_items']


def cleanup_confirm(orphan_paths: list, acting_user_id, upload_folder: str) -> dict:
    """Delete only explicitly approved paths that are still true orphans."""
    auth_service.require_role(acting_user_id, ['admin', 'super_admin'])

    fresh_orphans = {item['path'] for item in cleanup_preview(upload_folder)}
    deleted, skipped, failed = [], [], []

    for path in orphan_paths:
        if path not in fresh_orphans:
            skipped.append({'path': path, 'reason': 'כבר לא orphan בפועל (כנראה קושר לרשומה חדשה בינתיים)'})
            continue

        alog.log('orphan_cleanup_pending', 'storage_file', None, entity_label=path, old_value={'path': path})
        db.session.commit()

        result = storage.delete_file(path, upload_folder)
        if result['status']:
            deleted.append(path)
            alog.log('orphan_cleanup', 'storage_file', None, entity_label=path)
        else:
            failed.append({'path': path, 'error': result['error']})
            logger.warning(f"Orphan cleanup failed for {path}: {result['error']}")
            alog.log('orphan_cleanup_failed', 'storage_file', None, entity_label=path,
                     new_value={'error': result['error']})
        db.session.commit()

    global _last_cleanup_at
    _last_cleanup_at = datetime.utcnow().isoformat()
    return {'deleted': deleted, 'skipped': skipped, 'failed': failed}


_last_scan_at = None
_last_cleanup_at = None


def get_status_counts() -> dict:
    rows = db.session.query(Document.status, db.func.count(Document.id)).group_by(Document.status).all()
    counts = {status: count for status, count in rows}
    return {
        'active': counts.get('active', 0),
        'archived': counts.get('archived', 0),
        'deleted': counts.get('deleted', 0),
        'draft': counts.get('draft', 0),
        'total': sum(counts.values()),
    }


def dashboard_summary(upload_folder: str) -> dict:
    global _last_scan_at
    result = scan(upload_folder)
    _last_scan_at = result['scanned_at']
    result.update(get_status_counts())
    result['last_scan_at'] = _last_scan_at
    result['last_cleanup_at'] = _last_cleanup_at
    return result
