"""Render background worker for queued Gemini document analysis.

The web service only enqueues jobs. This process consumes them and is safe to
restart: jobs stuck in processing beyond AI_WORKER_STALE_MINUTES are returned
to the queue, and failed jobs are retried up to AI_MAX_ATTEMPTS times.
"""
import logging
import os
import signal
import time
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Document
from app.services.gemini_document_service import analyze_and_persist, is_configured

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("document-ai-worker")

app = create_app()
shutdown_requested = False


def _shutdown(signum, _frame):
    global shutdown_requested
    shutdown_requested = True
    log.info("Received signal %s; finishing current job and shutting down.", signum)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


def _recover_stale_jobs():
    minutes = max(5, int(os.environ.get("AI_WORKER_STALE_MINUTES", "30")))
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    stale = (
        Document.query
        .filter(Document.ai_status == "processing")
        .filter(Document.ai_started_at.isnot(None))
        .filter(Document.ai_started_at < cutoff)
        .all()
    )
    if not stale:
        return 0

    recovered = 0
    for doc in stale:
        doc.ai_status = "queued"
        doc.ai_started_at = None
        doc.ai_error = "הניתוח הופסק לפני השלמתו והוחזר אוטומטית לתור."
        recovered += 1
    db.session.commit()
    log.warning("Recovered %s stale Gemini jobs.", recovered)
    return recovered


def _claim():
    query = (
        Document.query
        .filter(Document.ai_status == "queued")
        .order_by(Document.uploaded_at.asc(), Document.id.asc())
    )
    bind = db.session.get_bind()
    if bind.dialect.name == "postgresql":
        doc = query.with_for_update(skip_locked=True).first()
    else:
        doc = query.first()

    if not doc:
        return None

    doc.ai_status = "processing"
    doc.ai_started_at = datetime.utcnow()
    doc.ai_attempts = (doc.ai_attempts or 0) + 1
    db.session.commit()
    return doc.id, doc.ai_attempts


def _handle_failure(doc_id, attempts, exc):
    max_attempts = max(1, int(os.environ.get("AI_MAX_ATTEMPTS", "3")))
    doc = db.session.get(Document, doc_id)
    if not doc:
        return

    if attempts < max_attempts:
        doc.ai_status = "queued"
        doc.ai_started_at = None
        doc.ai_error = f"ניסיון {attempts} נכשל; הוחזר לתור לניסיון נוסף: {str(exc)[:1500]}"
        db.session.commit()
        log.warning("Gemini job %s failed on attempt %s/%s; requeued.", doc_id, attempts, max_attempts)
    else:
        doc.ai_status = "failed"
        doc.ai_started_at = None
        doc.ai_error = f"נכשל לאחר {attempts} ניסיונות: {str(exc)[:1500]}"
        db.session.commit()
        log.error("Gemini job %s permanently failed after %s attempts.", doc_id, attempts)


def main():
    with app.app_context():
        if not is_configured():
            raise RuntimeError("GEMINI_API_KEY is required for the document AI worker")

        poll_seconds = max(1, int(os.environ.get("AI_WORKER_POLL_SECONDS", "5")))

        while not shutdown_requested:
            try:
                _recover_stale_jobs()
                claimed = _claim()
                if not claimed:
                    time.sleep(poll_seconds)
                    continue

                doc_id, attempts = claimed
                log.info("Analyzing document %s (attempt %s).", doc_id, attempts)
                try:
                    analyze_and_persist(doc_id)
                    log.info("Document %s analyzed successfully.", doc_id)
                except Exception as exc:
                    db.session.rollback()
                    log.exception("Gemini analysis failed for document %s.", doc_id)
                    _handle_failure(doc_id, attempts, exc)
            except Exception:
                db.session.rollback()
                log.exception("Worker loop error.")
                time.sleep(poll_seconds)

        log.info("Worker stopped cleanly.")


if __name__ == "__main__":
    main()
