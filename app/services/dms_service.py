import hashlib
import os
from datetime import date, timedelta
from app.extensions import db
from app.models import Document, Zone, SystemRequirement
import logging

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

logger = logging.getLogger(__name__)

class DMSService:
    @staticmethod
    def calculate_hash(filepath: str) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def ingest_document(filepath: str, original_filename: str):
        file_hash = DMSService.calculate_hash(filepath)
        if Document.query.filter_by(file_hash=file_hash).first():
            return None 

        text = ""
        if HAS_FITZ:
            try:
                with fitz.open(filepath) as doc:
                    text = " ".join(page.get_text() for page in doc)
            except Exception as e:
                logger.warning(f"Could not read PDF text: {e}")

        combined_context = (text + " " + original_filename).replace(" ", "")
        
        detected_zone_id = None
        if "8855" in combined_context: detected_zone_id = Zone.query.filter_by(file_number="8855-7").first().id
        elif "8859" in combined_context: detected_zone_id = Zone.query.filter_by(file_number="8859-7").first().id
        elif "8853" in combined_context: detected_zone_id = Zone.query.filter_by(file_number="8853-7").first().id
        elif "8860" in combined_context: detected_zone_id = Zone.query.filter_by(file_number="8860-7").first().id
        elif "ראשי" in combined_context: detected_zone_id = Zone.query.filter_by(file_number="ראשי").first().id
        
        detected_req_id = None
        reqs = SystemRequirement.query.all()
        for req in reqs:
            if req.required_form.replace(" ","") in combined_context:
                detected_req_id = req.id
                detected_zone_id = req.zone_id
                break

        if not detected_zone_id:
            zone = Zone.query.filter_by(file_number="8855-7").first()
            if zone: detected_zone_id = zone.id

        new_doc = Document(
            req_id=detected_req_id,
            zone_id=detected_zone_id,
            file_name=original_filename,
            file_path=os.path.basename(filepath),
            file_hash=file_hash,
            expiry_date=date.today() + timedelta(days=365)
        )
        db.session.add(new_doc)
        db.session.commit()
        return new_docד
