"""Gemini-backed fire-safety document intelligence."""
from __future__ import annotations

import io
import json
import logging
import os
from datetime import date, datetime, timedelta

from flask import current_app
from app.extensions import db
from app.models import Document, Deficiency, Task
from app.services import storage

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "document_type": {"type": "STRING"},
        "document_purpose": {"type": "STRING"},
        "audit_number": {"type": "STRING", "nullable": True},
        "audit_date": {"type": "STRING", "nullable": True},
        "inspector_name": {"type": "STRING", "nullable": True},
        "summary": {"type": "STRING"},
        "overall_status": {"type": "STRING", "enum": ["ok", "needs_attention", "critical", "unclear"]},
        "key_findings": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "title": {"type": "STRING"},
            "description": {"type": "STRING"},
            "severity": {"type": "STRING", "enum": ["info", "low", "medium", "high", "critical", "unclear"]},
            "status": {"type": "STRING"},
            "why_it_matters": {"type": "STRING"},
            "recommended_action": {"type": "STRING"},
            "responsible_role": {"type": "STRING", "nullable": True},
            "due_days": {"type": "INTEGER", "nullable": True},
            "evidence_to_close": {"type": "STRING"},
            "source_quote": {"type": "STRING", "nullable": True},
            "source_page": {"type": "INTEGER", "nullable": True},
            "confidence": {"type": "NUMBER"}
        }, "required": ["title", "description", "severity", "status", "why_it_matters", "recommended_action", "evidence_to_close", "confidence"]}},
        "missing_items": {"type": "ARRAY", "items": {"type": "STRING"}},
        "contradictions": {"type": "ARRAY", "items": {"type": "STRING"}},
        "follow_up_questions": {"type": "ARRAY", "items": {"type": "STRING"}},
        "confidence": {"type": "NUMBER"}
    },
    "required": ["document_type", "document_purpose", "summary", "overall_status", "key_findings", "missing_items", "contradictions", "follow_up_questions", "confidence"]
}

SYSTEM_PROMPT = """אתה מנתח מסמכי בטיחות אש עבור ERP.
ה-PDF הוא מקור הראיות. אל תמציא עובדות, תאריכים, תקנים או חובות חוקיות.
לכל ממצא: הסבר מה נמצא, למה זה חשוב, מה צריך לעשות בפועל, מי בדרך כלל מטפל
אם אפשר להסיק זאת, ומה הראיה הדרושה לסגירה. הפרד עובדה מהמלצה וסמן אי-ודאות.
אל תציג המלצה משפטית כעובדה. כתוב בעברית ברורה ומעשית."""

def is_configured():
    return bool(current_app.config.get("GEMINI_API_KEY"))

def _client():
    if not is_configured():
        raise RuntimeError("GEMINI_API_KEY אינו מוגדר")
    from google import genai
    return genai.Client(api_key=current_app.config["GEMINI_API_KEY"])

def _bytes(document):
    if storage.is_supabase_path(document.file_path) and storage.is_configured():
        return storage.download_bytes(document.file_path)
    legacy = storage.find_supabase_legacy_path(document.file_path)
    if legacy and storage.is_configured():
        return storage.download_bytes(legacy)
    root = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    path = os.path.abspath(os.path.join(root, os.path.basename(document.file_path or "")))
    if os.path.commonpath([path, root]) != root or not os.path.isfile(path):
        raise FileNotFoundError("קובץ המסמך לא נמצא")
    with open(path, "rb") as fh:
        return fh.read()

def _parse(response):
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini החזיר תשובה ריקה")
    return json.loads(text)

def analyze(document):
    from google.genai import types
    data = _bytes(document)
    client = _client()
    context = json.dumps({
        "document_id": document.id,
        "file_name": document.file_name,
        "category": document.category,
        "zone": document.zone.zone_name if document.zone else None,
        "local_analysis": {
            "issue_date": document.analysis_issue_date.isoformat() if document.analysis_issue_date else None,
            "expiry_date": document.analysis_expiry_date.isoformat() if document.analysis_expiry_date else None,
            "validity_status": document.analysis_validity_status,
            "confidence": document.analysis_confidence
        }
    }, ensure_ascii=False)
    prompt = "נתח את ה-PDF לפי ההוראות. נתוני ERP הם הקשר בלבד ואינם מקור אמת:\n" + context
    temporary = None
    try:
        if len(data) <= current_app.config["GEMINI_MAX_INLINE_PDF_BYTES"]:
            contents = [types.Part.from_bytes(data=data, mime_type="application/pdf"), prompt]
        else:
            uploaded = client.files.upload(
                file=io.BytesIO(data),
                config=types.UploadFileConfig(mime_type="application/pdf", display_name=document.file_name)
            )
            temporary = getattr(uploaded, "name", None)
            contents = [uploaded, prompt]
        response = client.models.generate_content(
            model=current_app.config["GEMINI_MODEL"],
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=SCHEMA,
                thinking_config=types.ThinkingConfig(thinking_level=current_app.config["GEMINI_THINKING_LEVEL"])
            )
        )
        result = _parse(response)
        result["model"] = current_app.config["GEMINI_MODEL"]
        return result
    finally:
        if temporary:
            try:
                client.files.delete(name=temporary)
            except Exception:
                log.warning("Failed to delete temporary Gemini file %s", temporary)

def persist(document, result):
    document.ai_status = "completed"
    document.ai_model = result.get("model")
    document.ai_analyzed_at = datetime.utcnow()
    document.ai_document_type = result.get("document_type")
    document.ai_summary = result.get("summary")
    document.ai_findings_json = json.dumps(result.get("key_findings", []), ensure_ascii=False)
    document.ai_actions_json = json.dumps({
        "missing_items": result.get("missing_items", []),
        "contradictions": result.get("contradictions", []),
        "follow_up_questions": result.get("follow_up_questions", [])
    }, ensure_ascii=False)
    try:
        document.ai_confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        document.ai_confidence = None
    document.ai_error = None
    document.ai_started_at = None
    document.analysis_review_required = (
        document.analysis_review_required or
        result.get("overall_status") in {"critical", "unclear"} or
        any(float(x.get("confidence", 0) or 0) < current_app.config["GEMINI_REVIEW_CONFIDENCE"]
            for x in result.get("key_findings", []))
    )
    db.session.commit()

def analyze_and_persist(document_id):
    document = db.session.get(Document, document_id)
    if not document:
        raise ValueError("המסמך לא נמצא")
    document.ai_status = "processing"
    document.ai_started_at = datetime.utcnow()
    document.ai_error = None
    db.session.commit()
    try:
        result = analyze(document)
        persist(document, result)
        return result
    except Exception as exc:
        db.session.rollback()
        document = db.session.get(Document, document_id)
        document.ai_status = "failed"
        document.ai_error = str(exc)[:2000]
        db.session.commit()
        raise

def queue(document):
    document.ai_status = "queued"
    document.ai_error = None
    document.ai_started_at = None
    document.ai_attempts = 0
    db.session.commit()

def findings(document):
    try:
        value = json.loads(document.ai_findings_json or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []

def actions(document):
    try:
        value = json.loads(document.ai_actions_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}

def create_operational_actions(document):
    created = []
    existing = {d.title.strip().lower() for d in Deficiency.query.filter(Deficiency.notes.ilike(f"%document:{document.id}%")).all()}
    for item in findings(document):
        severity = item.get("severity")
        title = (item.get("title") or "").strip()
        if severity not in {"low", "medium", "high", "critical"} or not title or title.lower() in existing:
            continue
        try:
            due = date.today() + timedelta(days=max(0, int(item.get("due_days", 0) or 0)))
        except (TypeError, ValueError):
            due = None
        description = "\n".join(x for x in [
            item.get("description"),
            "למה זה חשוב: " + str(item.get("why_it_matters") or ""),
            "מה לעשות: " + str(item.get("recommended_action") or ""),
            "ראיה לסגירה: " + str(item.get("evidence_to_close") or "")
        ] if x)
        d = Deficiency(title=title, description=description, severity=severity,
                       responsible=item.get("responsible_role"), opened_at=date.today(),
                       due_date=due, status="open",
                       notes=f"document:{document.id}; ai_model:{document.ai_model or ''}")
        db.session.add(d)
        db.session.flush()
        priority = {"critical": "urgent", "high": "high", "medium": "normal", "low": "low"}[severity]
        task = Task(title=f"תיקון ליקוי AI: {title}", description=description,
                    assignee=item.get("responsible_role"), priority=priority, status="open",
                    due_date=due,
                    checklist_json=json.dumps([
                        {"text": "לבצע את הפעולה המומלצת", "done": False},
                        {"text": "לאסוף ראיה/אישור לסגירה", "done": False}
                    ], ensure_ascii=False))
        db.session.add(task)
        db.session.flush()
        d.task_id = task.id
        created.append({"deficiency_id": d.id, "task_id": task.id, "title": title})
        existing.add(title.lower())
    db.session.commit()
    return {"count": len(created), "created": created}
