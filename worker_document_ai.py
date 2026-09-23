"""Render worker for queued Gemini analysis."""
import logging, os, time
from app import create_app
from app.extensions import db
from app.models import Document
from app.services.gemini_document_service import analyze_and_persist, is_configured

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log=logging.getLogger("document-ai-worker")
app=create_app()

def claim():
    query=Document.query.filter_by(ai_status="queued").order_by(Document.uploaded_at.asc())
    if db.session.get_bind().dialect.name=="postgresql":
        doc=query.with_for_update(skip_locked=True).first()
    else:
        doc=query.first()
    if not doc: return None
    doc.ai_status="processing"
    db.session.commit()
    return doc.id

def main():
    with app.app_context():
        if not is_configured(): raise RuntimeError("GEMINI_API_KEY is required")
        while True:
            doc_id=claim()
            if doc_id:
                try: analyze_and_persist(doc_id); log.info("Analyzed document %s",doc_id)
                except Exception: log.exception("Analysis failed for %s",doc_id)
            else:
                time.sleep(int(os.environ.get("AI_WORKER_POLL_SECONDS","5")))

if __name__=="__main__": main()
