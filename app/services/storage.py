"""
Service Layer עבור Supabase Storage.
"""
import hashlib
import logging
import os
from datetime import datetime

from flask import current_app

logger = logging.getLogger(__name__)


class StorageError(Exception):
    pass


_client_cache = {}


def _get_client():
    url = current_app.config.get('SUPABASE_URL')
    key = current_app.config.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        raise StorageError('Supabase אינו מוגדר (חסרים SUPABASE_URL / SUPABASE_SERVICE_KEY)')
    cache_key = (url, key)
    if cache_key in _client_cache:
        return _client_cache[cache_key]
    from supabase import create_client
    client = create_client(url, key)
    _client_cache[cache_key] = client
    return client


def _bucket_name():
    return current_app.config.get('SUPABASE_BUCKET', 'documents')


def get_bucket_name() -> str:
    return _bucket_name()


def is_configured() -> bool:
    return bool(current_app.config.get('SUPABASE_URL')) and bool(current_app.config.get('SUPABASE_SERVICE_KEY'))


def check_connection():
    if not is_configured():
        return False, 'Supabase לא מוגדר'
    try:
        client = _get_client()
        client.storage.from_(_bucket_name()).list()
        return True, None
    except Exception as e:
        logger.error(f'Supabase connection check failed: {e}')
        return False, str(e)


def is_supabase_path(file_path: str) -> bool:
    if not file_path:
        return False
    return file_path.startswith(f'{_bucket_name()}/')


def upload_bytes(remote_filename: str, data: bytes, content_type: str = 'application/pdf') -> str:
    client = _get_client()
    bucket = _bucket_name()
    try:
        client.storage.from_(bucket).upload(
            path=remote_filename,
            file=data,
            file_options={'content-type': content_type},
        )
    except Exception as e:
        logger.error(f'Supabase upload failed for {remote_filename}: {e}')
        raise StorageError(f'העלאה ל-Supabase Storage נכשלה: {e}')
    return f'{bucket}/{remote_filename}'


def delete_object(stored_path: str):
    if not stored_path:
        return
    bucket = _bucket_name()
    remote_filename = stored_path[len(bucket) + 1:] if stored_path.startswith(f'{bucket}/') else stored_path
    try:
        client = _get_client()
        client.storage.from_(bucket).remove([remote_filename])
    except Exception as e:
        logger.error(f'Supabase cleanup delete failed for {stored_path}: {e}')


def get_signed_url(stored_path: str, expires_in: int = 300):
    bucket = _bucket_name()
    remote_filename = stored_path[len(bucket) + 1:] if stored_path.startswith(f'{bucket}/') else stored_path
    try:
        client = _get_client()
        res = client.storage.from_(bucket).create_signed_url(remote_filename, expires_in)
        if isinstance(res, dict):
            return res.get('signedURL') or res.get('signedUrl') or res.get('signed_url')
        return getattr(res, 'signed_url', None)
    except Exception as e:
        logger.error(f'Supabase signed URL failed for {stored_path}: {e}')
        return None


def calculate_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def calculate_file_hash(local_path: str) -> str:
    h = hashlib.sha256()
    with open(local_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def file_exists(file_path: str, upload_folder: str) -> dict:
    if not file_path:
        return {'status': False, 'location': None, 'error': 'file_path ריק'}
    if is_supabase_path(file_path) and is_configured():
        signed_url = get_signed_url(file_path)
        if signed_url:
            return {'status': True, 'location': 'supabase', 'error': None}
    local_full_path = os.path.join(upload_folder, os.path.basename(file_path))
    if os.path.isfile(local_full_path):
        return {'status': True, 'location': 'local', 'error': None}
    return {'status': False, 'location': None, 'error': 'לא נמצא לא ב-Supabase ולא מקומית'}


def list_local_files(upload_folder: str) -> list:
    results = []
    if not os.path.isdir(upload_folder):
        return results
    for root, dirs, files in os.walk(upload_folder):
        for fname in files:
            full_path = os.path.join(root, fname)
            try:
                stat = os.stat(full_path)
                size = stat.st_size
                modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError:
                size = None
                modified_at = None
            results.append({'filename': fname, 'path': os.path.abspath(full_path), 'size': size, 'modified_at': modified_at})
    return results


def build_local_hash_index(upload_folder: str) -> dict:
    index = {}
    for entry in list_local_files(upload_folder):
        try:
            index[calculate_file_hash(entry['path'])] = entry['path']
        except Exception as e:
            logger.warning(f"Could not hash {entry['path']}: {e}")
    return index


def build_local_basename_index(upload_folder: str) -> dict:
    index = {}
    for entry in list_local_files(upload_folder):
        index.setdefault(entry['filename'], []).append(entry['path'])
    return index


def delete_file(file_path: str, upload_folder: str) -> dict:
    if not file_path:
        return {'status': False, 'error': 'file_path ריק'}
    if is_supabase_path(file_path) and is_configured():
        try:
            delete_object(file_path)
        except Exception as e:
            return {'status': False, 'error': f'Supabase deletion failed: {e}'}
        still_accessible = get_signed_url(file_path) is not None
        if still_accessible:
            return {'status': False, 'error': 'הקובץ עדיין נגיש ב-Supabase אחרי ניסיון המחיקה'}
        return {'status': True, 'error': None}

    local_root = os.path.abspath(upload_folder)
    local_full_path = os.path.abspath(os.path.join(local_root, os.path.basename(file_path)))
    if os.path.commonpath([local_full_path, local_root]) != local_root:
        return {'status': False, 'error': 'נתיב קובץ לא חוקי'}
    if not os.path.isfile(local_full_path):
        return {'status': False, 'error': f'קובץ מקומי לא נמצא: {local_full_path}'}
    try:
        os.remove(local_full_path)
        return {'status': True, 'error': None}
    except Exception as e:
        return {'status': False, 'error': f'מחיקה מקומית נכשלה: {e}'}


def upload_temp(data: bytes, filename: str, upload_folder: str) -> dict:
    file_hash = calculate_hash(data)
    file_size = len(data)
    try:
        if is_configured():
            stored_path = upload_bytes(filename, data)
        else:
            local_root = os.path.abspath(upload_folder)
            local_path = os.path.abspath(os.path.join(local_root, filename))
            if os.path.commonpath([local_path, local_root]) != local_root:
                raise StorageError('Invalid local storage path')
            with open(local_path, 'wb') as f:
                f.write(data)
            stored_path = filename
        return {'status': True, 'path': stored_path, 'hash': file_hash, 'size': file_size, 'error': None}
    except Exception as e:
        logger.error(f'upload_temp failed for {filename}: {e}')
        return {'status': False, 'path': None, 'hash': None, 'size': None, 'error': str(e)}


def verify_pdf_bytes(data: bytes) -> dict:
    """Validate size, PDF signature and basic PDF structure."""
    if not data:
        return {'status': False, 'error': 'קובץ ריק'}
    max_bytes = int(current_app.config.get('MAX_PDF_BYTES', 100 * 1024 * 1024))
    if len(data) > max_bytes:
        return {'status': False, 'error': 'הקובץ חורג מגודל ה-PDF המותר'}
    if not data.startswith(b'%PDF-'):
        return {'status': False, 'error': 'הקובץ אינו PDF תקין (חסר header %PDF-)'}
    try:
        import fitz
        document = fitz.open(stream=data, filetype='pdf')
        try:
            if document.page_count < 1:
                return {'status': False, 'error': 'ה-PDF אינו מכיל עמודים'}
        finally:
            document.close()
    except Exception as exc:
        logger.warning(f'PDF structural validation failed: {exc}')
        return {'status': False, 'error': 'לא ניתן לפרש את הקובץ כ-PDF תקין'}
    return {'status': True, 'error': None}
