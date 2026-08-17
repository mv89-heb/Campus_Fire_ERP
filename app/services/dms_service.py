import hashlib
import os
import logging

from app.extensions import db
from app.models import Document, Zone, SystemRequirement
from app.services import storage
from app.services.document_analysis_service import analyze_pdf_bytes, apply_analysis_to_document

logger = logging.getLogger(__name__)


class DMSService:
    @staticmethod
    def calculate_hash(filepath: str) -> str:
        return storage.calculate_file_hash(filepath)

    @staticmethod
    def _find_requirement(form_number, zone_id=None):
        """Resolve a requirement by form number, preferring the detected zone.

        Form numbers are reused across zones (for example form 6 exists for
        several campus areas), so matching by form number alone is unsafe.
        """
        if form_number is None:
            return None
        form_label = f"טופס {form_number}"
        query = SystemRequirement.query.filter(
            db.func.replace(SystemRequirement.required_form, ' ', '') == form_label.replace(' ', '')
        )
        if zone_id:
            zone_match = query.filter(SystemRequirement.zone_id == zone_id).first()
            if zone_match:
                return zone_match
        matches = query.all()
        if len(matches) == 1:
            return matches[0]
        # Multiple requirements share the same form number and no reliable
        # zone match exists: leave req_id unset rather than assigning the
        # document to an arbitrary zone.
        return None

    @staticmethod
    def ingest_document(filepath: str, original_filename: str):
        """Ingest a validated PDF, analyze its content, then persist it."""
        file_hash = DMSService.calculate_hash(filepath)
        if Document.query.filter_by(file_hash=file_hash).filter(Document.status != 'deleted').first():
            DMSService._cleanup_local_temp(filepath)
            return None

        with open(filepath, 'rb') as f:
            file_bytes = f.read()

        analysis = analyze_pdf_bytes(file_bytes, original_filename)
        detected_zone_id = None
        zone_code = analysis.get('zone_code')
        if zone_code:
            zone = Zone.query.filter_by(file_number=zone_code).first()
            if zone:
                detected_zone_id = zone.id

        detected_req_id = None
        req = DMSService._find_requirement(analysis.get('form_number'), detected_zone_id)
        if req:
            detected_req_id = req.id
            detected_zone_id = req.zone_id

        # Never silently put an unclassified document into the residence zone.
        # A fallback is only safe when the document has no detected form/zone
        # at all and the legacy application explicitly needs a holding zone.
        if not detected_zone_id and analysis.get('form_number') is None:
            zone = Zone.query.filter_by(file_number='8855-7').first()
            if zone:
                detected_zone_id = zone.id

        uploaded_to_supabase = False
        stored_path = os.path.basename(filepath)
        if storage.is_configured():
            remote_filename = os.path.basename(filepath)
            try:
                stored_path = storage.upload_bytes(remote_filename, file_bytes)
                uploaded_to_supabase = True
            except storage.StorageError:
                DMSService._cleanup_local_temp(filepath)
                raise

        new_doc = Document(
            req_id=detected_req_id,
            zone_id=detected_zone_id,
            file_name=original_filename,
            file_path=stored_path,
            file_hash=file_hash,
            file_size=len(file_bytes),
            expiry_date=analysis.get('expiry_date'),
            issue_date=analysis.get('issue_date'),
            category=analysis.get('category'),
            status='active',
        )
        apply_analysis_to_document(new_doc, analysis)
        db.session.add(new_doc)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if uploaded_to_supabase:
                storage.delete_object(stored_path)
            raise
        finally:
            if uploaded_to_supabase:
                DMSService._cleanup_local_temp(filepath)

        if analysis.get('status') == 'needs_review':
            logger.warning(
                'Document %s imported without reliable inspection date: %s',
                original_filename,
                analysis.get('analysis_notes'),
            )
        return new_doc

    @staticmethod
    def _cleanup_local_temp(filepath: str):
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            logger.warning(f"Could not remove local temp file {filepath}: {e}")
