"""Safe migration helpers for legacy Document.file_path values."""
from app.extensions import db
from app.models import Document
from app.services import storage
from app.services import audit_log_service as alog


def scan_legacy_documents(upload_folder: str) -> dict:
    """Classify documents that are not stored as native Supabase paths.

    A legacy document is recoverable when its basename exists exactly once in
    the configured Supabase bucket. It is locally migratable when the local
    Render filesystem still contains the file. Missing documents are reported
    but never modified.
    """
    docs = Document.query.filter(Document.status != 'deleted').all()
    inventory = storage.list_supabase_files() if storage.is_configured() else []
    inventory_names = {item.get('filename') for item in inventory if item.get('filename')}
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

        basename = storage.os.path.basename(doc.file_path)
        local_path = storage.os.path.join(upload_folder, basename)
        if storage.os.path.isfile(local_path):
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
                with open(storage.os.path.join(upload_folder, storage.os.path.basename(old_path)), 'rb') as f:
                    data = f.read()
                new_path = storage.upload_bytes(storage.os.path.basename(old_path), data)

            doc.file_path = new_path
            db.session.commit()
            alog.log('document_storage_migrated', 'document', doc.id,
                     entity_label=doc.file_name, old_value={'file_path': old_path},
                     new_value={'file_path': new_path})
            db.session.commit()
            migrated.append({'document_id': doc.id, 'file_name': doc.file_name, 'old_path': old_path, 'new_path': new_path})
        except Exception as exc:
            db.session.rollback()
            failed.append({'document_id': doc.id, 'file_name': doc.file_name, 'error': str(exc)})

    return {'success': not failed, 'migrated': migrated, 'failed': failed, 'report': scan_legacy_documents(upload_folder)}
