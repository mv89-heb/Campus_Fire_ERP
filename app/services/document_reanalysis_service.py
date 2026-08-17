"""Re-analyze existing documents from their real stored PDF content."""
from __future__ import annotations

import os

from flask import current_app

from app.extensions import db
from app.models import Document, Zone, SystemRequirement
from app.services import storage
from app.services.document_analysis_service import analyze_pdf_bytes, apply_analysis_to_document, validity_status


def _requirement_for(form_number, zone_id):
    if form_number is None or zone_id is None:
        return None
    label = f"טופס {form_number}"
    return SystemRequirement.query.filter(
        SystemRequirement.zone_id == zone_id,
        db.func.replace(SystemRequirement.required_form, ' ', '') == label.replace(' ', ''),
    ).first()


def _read_document_bytes(doc):
    if storage.is_supabase_path(doc.file_path) and storage.is_configured():
        return storage.download_bytes(doc.file_path), "supabase"

    resolved = storage.find_supabase_legacy_path(doc.file_path)
    if resolved and storage.is_configured():
        return storage.download_bytes(resolved), "supabase_legacy"

    upload_folder = current_app.config['UPLOAD_FOLDER']
    path = os.path.abspath(os.path.join(upload_folder, os.path.basename(doc.file_path or '')))
    root = os.path.abspath(upload_folder)
    if os.path.commonpath([path, root]) != root or not os.path.isfile(path):
        raise FileNotFoundError(f"Document file not found: {doc.file_path}")
    with open(path, 'rb') as handle:
        return handle.read(), "local"


def _persist_analysis(doc, analysis, previous_issue, previous_expiry):
    """Persist the analysis as the current compliance truth.

    If the PDF cannot prove an expiry, the old expiry is retained only in
    previous_expiry_date. It is never used as the current compliance expiry.
    This prevents an old/manual date from making an unverified document appear
    valid after re-analysis.
    """
    analysis_expiry = analysis.get('expiry_date')
    analysis_issue = analysis.get('issue_date')

    if previous_expiry and previous_expiry != analysis_expiry:
        doc.previous_expiry_date = previous_expiry
    elif analysis_expiry is not None:
        doc.previous_expiry_date = None
    if previous_issue and previous_issue != analysis_issue:
        doc.previous_issue_date = previous_issue
    elif analysis_issue is not None:
        doc.previous_issue_date = None

    doc.analysis_expiry_date = analysis_expiry
    doc.analysis_issue_date = analysis_issue
    doc.analysis_validity_status = analysis.get('validity_status') or 'needs_review'
    doc.analysis_validity_source = analysis.get('validity_source')
    doc.analysis_validity_rule = analysis.get('validity_rule')
    doc.analysis_validity_rule_label = analysis.get('validity_rule_label')
    doc.analysis_validity_rule_evidence = analysis.get('validity_rule_evidence')
    doc.requirement_cycle = analysis.get('requirement_cycle')
    doc.requirement_source = analysis.get('requirement_source')
    doc.requirement_note = analysis.get('requirement_note')
    doc.analysis_confidence = analysis.get('confidence')
    doc.analysis_review_required = analysis.get('status') == 'needs_review'

    # Only a date proven by the current analysis becomes the effective expiry.
    doc.expiry_date = analysis_expiry
    doc.issue_date = analysis_issue


def reanalyze_all(include_archived=False):
    """Analyze every stored PDF and make the analyzed result authoritative."""
    query = Document.query.filter(Document.status != 'deleted')
    if not include_archived:
        query = query.filter(Document.status != 'archived')

    documents = query.order_by(Document.id.asc()).all()
    updated, reviewed, failed = [], [], []

    for doc in documents:
        old = {
            'zone_id': doc.zone_id,
            'req_id': doc.req_id,
            'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
            'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None,
            'category': doc.category,
        }
        try:
            data, source = _read_document_bytes(doc)
            analysis = analyze_pdf_bytes(data, doc.file_name or '')
            if not analysis.get('text_extracted'):
                doc.analysis_review_required = True
                doc.analysis_validity_status = 'needs_review'
                db.session.commit()
                reviewed.append({
                    'document_id': doc.id,
                    'file_name': doc.file_name,
                    'status': 'needs_review',
                    'source': source,
                    'reason': analysis.get('analysis_notes'),
                    'old': old,
                })
                continue

            zone_id = None
            zone_code = analysis.get('zone_code')
            if zone_code:
                zone = Zone.query.filter_by(file_number=zone_code).first()
                zone_id = zone.id if zone else None

            req = _requirement_for(analysis.get('form_number'), zone_id)
            if req:
                zone_id = req.zone_id

            if zone_id is not None:
                doc.zone_id = zone_id
                doc.req_id = req.id if req else None

            previous_issue = doc.issue_date
            previous_expiry = doc.expiry_date
            apply_analysis_to_document(doc, analysis)
            _persist_analysis(doc, analysis, previous_issue, previous_expiry)
            db.session.commit()

            analysis_expiry = analysis.get('expiry_date')
            row = {
                'document_id': doc.id,
                'file_name': doc.file_name,
                'source': source,
                'form_number': analysis.get('form_number'),
                'zone_code': analysis.get('zone_code'),
                'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
                'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None,
                'analysis_expiry_date': analysis_expiry.isoformat() if analysis_expiry else None,
                'previous_expiry_preserved': bool(doc.previous_expiry_date),
                'previous_expiry_date': doc.previous_expiry_date.isoformat() if doc.previous_expiry_date else None,
                'validity_status': doc.analysis_validity_status,
                'analysis_validity_status': analysis.get('validity_status'),
                'validity_source': analysis.get('validity_source'),
                'validity_rule': analysis.get('validity_rule'),
                'validity_rule_label': analysis.get('validity_rule_label'),
                'validity_rule_evidence': analysis.get('validity_rule_evidence'),
                'requirement_cycle': analysis.get('requirement_cycle'),
                'requirement_source': analysis.get('requirement_source'),
                'requirement_note': analysis.get('requirement_note'),
                'confidence': analysis.get('confidence'),
                'analysis_review_required': doc.analysis_review_required,
                'notes': analysis.get('analysis_notes'),
                'old': old,
            }
            if analysis.get('status') == 'needs_review':
                reviewed.append(row)
            else:
                updated.append(row)
        except Exception as exc:
            db.session.rollback()
            failed.append({'document_id': doc.id, 'file_name': doc.file_name, 'error': str(exc)})

    return {
        'success': not failed,
        'total': len(documents),
        'updated': updated,
        'needs_review': reviewed,
        'failed': failed,
        'counts': {
            'total': len(documents),
            'updated': len(updated),
            'needs_review': len(reviewed),
            'failed': len(failed),
        },
    }
