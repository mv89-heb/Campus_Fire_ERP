import hashlib
import os
from datetime import date, timedelta
from app.extensions import db
from app.models import Document, Zone, SystemRequirement
from app.services import storage
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
        """
        קולט מסמך שכבר נשמר זמנית בדיסק המקומי (ב-filepath, ע"י
        validate_and_save_pdf). ה-API הזה לא השתנה כדי לא לשבור קריאות קיימות.

        שינוי פנימי (Supabase): אם Supabase מוגדר, המסמך מועלה ל-Supabase
        Storage ו-file_path נשמר בפורמט 'documents/uuid.pdf'; הקובץ הזמני
        בדיסק המקומי נמחק אחרי הצלחה, כי Supabase הופך למקור האמת. אם
        Supabase לא מוגדר, ההתנהגות הישנה נשמרת במלואה: הקובץ נשאר בדיסק
        המקומי לצמיתות ו-file_path נשמר כ-'uuid.pdf' בלבד.
        """
        file_hash = DMSService.calculate_hash(filepath)
        if Document.query.filter_by(file_hash=file_hash).first():
            DMSService._cleanup_local_temp(filepath)
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

        # --- אחסון: Supabase אם מוגדר, אחרת דיסק מקומי (תאימות לאחור) ---
        uploaded_to_supabase = False
        stored_path = os.path.basename(filepath)  # ברירת מחדל: פורמט מקומי ישן

        if storage.is_configured():
            remote_filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                file_bytes = f.read()
            try:
                stored_path = storage.upload_bytes(remote_filename, file_bytes)
                uploaded_to_supabase = True
            except storage.StorageError:
                DMSService._cleanup_local_temp(filepath)
                raise  # לא יוצרים רשומת Document אם ההעלאה ל-Supabase נכשלה

        new_doc = Document(
            req_id=detected_req_id,
            zone_id=detected_zone_id,
            file_name=original_filename,
            file_path=stored_path,
            file_hash=file_hash,
            expiry_date=date.today() + timedelta(days=365)
        )
        db.session.add(new_doc)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if uploaded_to_supabase:
                # לא משאירים קובץ יתום ב-Supabase אם ה-Neon נכשל
                storage.delete_object(stored_path)
            raise
        finally:
            if uploaded_to_supabase:
                # Supabase הוא כעת מקור האמת - לא משאירים עותק קבוע בדיסק של Render
                DMSService._cleanup_local_temp(filepath)

        return new_doc

    @staticmethod
    def _cleanup_local_temp(filepath: str):
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            logger.warning(f"Could not remove local temp file {filepath}: {e}")
