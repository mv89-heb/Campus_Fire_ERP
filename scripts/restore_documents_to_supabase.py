#!/usr/bin/env python3
"""
Restore document files from a local backup into Supabase Storage.

The source directory is expected to contain the original uploaded files.
The script never deletes objects and only updates a Document row after the
Supabase upload has been verified by downloading the object back and checking
its SHA-256/PDF structure.

Usage:
    python scripts/restore_documents_to_supabase.py --source C:\path\to\uploads
    python scripts/restore_documents_to_supabase.py --source ./uploads --dry-run
    python scripts/restore_documents_to_supabase.py --source ./uploads --document-id 13
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import sys
from pathlib import Path

# Allow execution from the repository root or from scripts/.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Document  # noqa: E402
from app.services import storage  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> str:
    # Keep Hebrew/unicode names, but remove path traversal and separators.
    name = os.path.basename(name).strip().replace("/", "_").replace("\\", "_")
    return name or "document.pdf"


def build_index(source: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        index.setdefault(path.name, []).append(path)
    return index


def validate_pdf(data: bytes) -> tuple[bool, str | None]:
    result = storage.verify_pdf_bytes(data)
    return bool(result.get("status")), result.get("error")


def process_document(doc: Document, candidates: list[Path], dry_run: bool) -> dict:
    result = {
        "document_id": doc.id,
        "db_file_name": doc.file_name,
        "db_file_path": doc.file_path,
        "status": None,
        "source": None,
        "storage_path": None,
        "bytes": None,
        "sha256": None,
        "error": None,
    }

    if len(candidates) == 0:
        result["status"] = "missing_source"
        result["error"] = "לא נמצא קובץ מקור בשם זה"
        return result
    if len(candidates) > 1:
        result["status"] = "ambiguous_source"
        result["error"] = "נמצאו מספר קבצי מקור בעלי אותו שם"
        result["source_candidates"] = [str(p) for p in candidates]
        return result

    source = candidates[0]
    result["source"] = str(source)
    try:
        data = source.read_bytes()
    except OSError as exc:
        result["status"] = "read_failed"
        result["error"] = str(exc)
        return result

    result["bytes"] = len(data)
    result["sha256"] = sha256(data)

    if not data:
        result["status"] = "invalid_pdf"
        result["error"] = "קובץ ריק"
        return result

    # The restore is intentionally PDF-first because these are permit documents.
    mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    if source.suffix.lower() == ".pdf":
        valid, error = validate_pdf(data)
        if not valid:
            result["status"] = "invalid_pdf"
            result["error"] = error
            return result
        mime = "application/pdf"

    remote_name = f"restored/{doc.id}/{safe_name(source.name)}"
    result["storage_path"] = f"{storage.get_bucket_name()}/{remote_name}"

    if dry_run:
        result["status"] = "dry_run"
        return result

    try:
        stored_path = storage.upload_bytes(remote_name, data, mime)
        # Verify the object really exists and that Supabase returned the exact bytes.
        downloaded = storage.download_bytes(stored_path)
        downloaded_hash = sha256(downloaded)
        if downloaded_hash != result["sha256"] or len(downloaded) != len(data):
            raise RuntimeError("אימות העלאה נכשל: ה-hash/גודל של הקובץ שהורד אינו זהה למקור")
        if source.suffix.lower() == ".pdf":
            valid, error = validate_pdf(downloaded)
            if not valid:
                raise RuntimeError(f"אימות PDF לאחר העלאה נכשל: {error}")

        # Only after upload + download verification do we touch the DB row.
        doc.file_path = stored_path
        doc.file_hash = result["sha256"]
        doc.file_size = len(data)
        db.session.commit()
        result["status"] = "restored"
    except Exception as exc:
        db.session.rollback()
        result["status"] = "failed"
        result["error"] = str(exc)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore Campus Fire ERP documents into Supabase Storage")
    parser.add_argument("--source", required=True, help="Local directory containing the original document files")
    parser.add_argument("--document-id", type=int, help="Restore only one document")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without uploading or changing the DB")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(f"ERROR: source directory does not exist: {source}")
        return 2

    app = create_app()
    with app.app_context():
        if not storage.is_configured():
            print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_KEY are not configured")
            return 2

        ok, error = storage.check_connection()
        if not ok:
            print(f"ERROR: cannot connect to Supabase Storage: {error}")
            return 2

        index = build_index(source)
        query = Document.query
        if args.document_id:
            query = query.filter(Document.id == args.document_id)
        documents = query.order_by(Document.id.asc()).all()

        print(f"Source: {source}")
        print(f"Supabase bucket: {storage.get_bucket_name()}")
        print(f"Documents selected: {len(documents)}")
        print(f"Source files indexed: {sum(len(v) for v in index.values())}")
        print("Mode: DRY RUN" if args.dry_run else "Mode: RESTORE")
        print()

        counts: dict[str, int] = {}
        for doc in documents:
            candidates = index.get(os.path.basename(doc.file_name), [])
            result = process_document(doc, candidates, args.dry_run)
            status = result["status"]
            counts[status] = counts.get(status, 0) + 1
            print(
                f"[{status}] document={doc.id} "
                f"file={doc.file_name!r} "
                f"source={result.get('source')!r} "
                f"storage={result.get('storage_path')!r} "
                f"error={result.get('error')!r}"
            )

        print("\nSummary:")
        for key in sorted(counts):
            print(f"  {key}: {counts[key]}")

        # Exit non-zero only when an actual restore failed. Missing source files
        # are reported but do not make the whole recovery unusable.
        return 1 if counts.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
