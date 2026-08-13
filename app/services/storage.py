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
    return bool(file_path) and file_path.startswith(f'{_bucket_name()}/')


def upload_bytes(remote_filename: str, data: bytes, content_type: str = 'application/pdf') -> str:
    client = _get_client()
    bucket = _bucket_name()
    try:
        client.storage.from_(bucket).upload(path=remote_filename, file=data, file_options={'content-type': content_type})
    except Exception as e:
        logger.error(f'Supabase upload failed for {remote_filename}: {e}')
        raise StorageError(f'העלאה ל-Supabase Storage נכשלה: {e}')
    return f'{bucket}/{remote_filename}'


def delete_object(stored_path: str):
    if not stored_path:
        return
    bucket = _bucket_name()
    remote_filename = stored_path[len(bucket) + 1:] if stored_path.startswith(f'{bucket}/') else os.path.basename(stored_path)
    try:
        _get_client().storage.from_(bucket).remove([remote_filename])
    except Exception as e:
        logger.error(f'Supabase cleanup delete failed for {stored_path}: {e}')


def get_signed_url(stored_path: str, expires_in: int = 300):
    bucket = _bucket_name()
    remote_filename = stored_path[len(bucket) + 1:] if stored_path.startswith(f'{bucket}/') else stored_path
    try:
        res = _get_client().storage.from_(bucket).create_signed_url(remote_filename, expires_in)
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


def list_supabase_files() -> list:
    """Return files from the whole bucket, including nested folders."""
    if not is_configured():
        return []
    results = []
    bucket = _bucket_name()
    client = _get_client()
    visited = set()
    queue = ['']
    try:
        while queue:
            prefix = queue.pop(0)
            if prefix in visited:
                continue
            visited.add(prefix)
            limit, offset = 100, 0
            while True:
                page = client.storage.from_(bucket).list(
                    path=prefix,
                    options={'limit': limit, 'offset': offset, 'sortBy': {'column': 'name', 'order': 'asc'}},
                )
                if not page:
                    break
                for item in page:
                    name = item.get('name') if isinstance(item, dict) else getattr(item, 'name', None)
                    if not name:
                        continue
                    metadata = item.get('metadata') if isinstance(item, dict) else None
                    size = metadata.get('size') if isinstance(metadata, dict) else None
                    item_path = f'{prefix.rstrip("/")}/{name}' if prefix else name
                    if not metadata:
                        queue.append(item_path)
                    else:
                        results.append({'filename': item_path, 'basename': name, 'size': size})
                if len(page) < limit:
                    break
                offset += limit
    except Exception as e:
        logger.error(f'list_supabase_files failed: {e}')
    return results


def find_supabase_legacy_path(file_path: str, inventory: list | None = None) -> str | None:
    """Resolve old local DB paths to an actual Supabase object path."""
    if not file_path or not is_configured() or is_supabase_path(file_path):
        return None
    basename = os.path.basename(file_path)
    if not basename:
        return None
    inventory = inventory if inventory is not None else list_supabase_files()
    matches = []
    for item in inventory:
        object_name = item.get('filename') or ''
        item_basename = item.get('basename') or os.path.basename(object_name)
        if item_basename == basename:
            matches.append(object_name)
    return f'{_bucket_name()}/{matches[0]}' if len(matches) == 1 else None


def file_exists(file_path: str, upload_folder: str) -> dict:
    if not file_path:
        return {'status': False, 'location': None, 'error': 'file_path ריק'}
    if is_supabase_path(file_path) and is_configured():
        signed_url = get_signed_url(file_path)
        if signed_url:
            return {'status': True, 'location': 'supabase', 'error': None, 'resolved_path': file_path}
    legacy_supabase_path = find_supabase_legacy_path(file_path)
    if legacy_supabase_path:
        return {'status': True, 'location': 'supabase_legacy', 'error': None, 'resolved_path': legacy_supabase_path}
    local_full_path = os.path.join(upload_folder, os.path.basename(file_path))
    if os.path.isfile(local_full_path):
        return {'status': True, 'location': 'local', 'error': None, 'resolved_path': local_full_path}
    return {'status': False, 'location': None, 'error': 'לא נמצא לא ב-Supabase ולא מקומית'}


def delete_file(file_path: str, upload_folder: str) -> dict:
    if not file_path:
        return {'status': False, 'error': 'file_path ריק'}
    if is_supabase_path(file_path) and is_configured():
        try:
            delete_object(file_path)
        except Exception as e:
            return {'status': False, 'error': f'Supabase deletion failed: {e}'}
        return {'status': False, 'error': 'הקובץ עדיין נגיש ב-Supabase אחרי ניסיון המחיקה'} if get_signed_url(file_path) else {'status': True, 'error': None}
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
