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


def reanalyze_all(include_archived=False):
    """Analyze every stored PDF without destructively erasing known DB values.

    If a new analysis cannot establish an expiry date, an existing DB expiry is
    preserved. The response separately reports that the new analysis needs
    review, so the dashboard can remain operational while the operator sees
    that re-validation is incomplete.
    """
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

            # If the analyzer cannot classify the zone confidently, do not
            # overwrite an existing correct association.
            if zone_id is not None:
                doc.zone_id = zone_id
                doc.req_id = req.id if req else None

            # Keep known DB dates when the new parser has no evidence. This is
            # intentionally done before apply_analysis_to_document; that helper
            # only writes non-null analysis dates.
            previous_issue = doc.issue_date
            previous_expiry = doc.expiry_date
            apply_analysis_to_document(doc, analysis)
            if not analysis.get('inspection_date') and previous_issue:
                doc.issue_date = previous_issue
            if not analysis.get('expiry_date') and previous_expiry:
                doc.expiry_date = previous_expiry

            db.session.commit()

            analysis_expiry = analysis.get('expiry_date')
            preserved_expiry = not analysis_expiry and bool(previous_expiry)
            effective_expiry = analysis_expiry or previous_expiry
            effective_status = validity_status(effective_expiry)

            row = {
                'document_id': doc.id,
                'file_name': doc.file_name,
                'source': source,
                'form_number': analysis.get('form_number'),
                'zone_code': analysis.get('zone_code'),
                'issue_date': doc.issue_date.isoformat() if doc.issue_date else None,
                'expiry_date': doc.expiry_date.isoformat() if doc.expiry_date else None,
                'analysis_expiry_date': analysis_expiry.isoformat() if analysis_expiry else None,
                'previous_expiry_preserved': preserved_expiry,
                'validity_status': effective_status,
                'analysis_validity_status': analysis.get('validity_status'),
                'validity_source': analysis.get('validity_source'),
                'validity_rule': analysis.get('validity_rule'),
                'validity_rule_label': analysis.get('validity_rule_label'),
                'requirement_cycle': analysis.get('requirement_cycle'),
                'requirement_source': analysis.get('requirement_source'),
                'requirement_note': analysis.get('requirement_note'),
                'confidence': analysis.get('confidence'),
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
