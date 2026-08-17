#!/usr/bin/env python3
"""Restore document files from a local directory or ZIP backup into Supabase.

The backup produced by Campus Fire ERP preserves the original folders, e.g.:
    uploads/אישורים אולם ספורט 8853-8/טופס 6.pdf
or directly:
    אישורים אולם ספורט 8853-8/טופס 6.pdf

The important rule is: match a DB document by its original relative path when
available. Basename-only matching is used only when the basename is unique.
This avoids accidentally assigning the same 'טופס 3.pdf' from one zone to
another zone.

The script never deletes objects. A DB row is updated only after Supabase
upload + download verification (size, SHA-256, and PDF validation).

Examples:
    python scripts/restore_documents_to_supabase.py --source ./uploads --dry-run
    python scripts/restore_documents_to_supabase.py --source ./16.zip --dry-run
    python scripts/restore_documents_to_supabase.py --source ./16.zip
    python scripts/restore_documents_to_supabase.py --source ./16.zip --document-id 13
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Document  # noqa: E402
from app.services import storage  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_rel(value: str) -> str:
    """Normalize backup/DB paths for safe, case-insensitive comparison."""
    value = unicodedata.normalize("NFC", str(value or ""))
    value = value.replace("\\", "/").strip().lstrip("./")
    while value.startswith("uploads/"):
        value = value[len("uploads/"):]
    return "/".join(part for part in value.split("/") if part and part != ".")


def safe_name(name: str) -> str:
    name = os.path.basename(name).strip().replace("/", "_").replace("\\", "_")
    return name or "document.pdf"


def validate_pdf(data: bytes) -> tuple[bool, str | None]:
    result = storage.verify_pdf_bytes(data)
    return bool(result.get("status")), result.get("error")


def prepare_source(source: Path):
    """Return (directory, cleanup_callback). Supports directory or .zip."""
    if source.is_dir():
        return source, lambda: None
    if source.is_file() and source.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="campus_restore_"))
        try:
            with zipfile.ZipFile(source, "r") as zf:
                for member in zf.infolist():
                    # Protect against ZIP path traversal.
                    target = (tmp / member.filename).resolve()
                    if not str(target).startswith(str(tmp.resolve()) + os.sep):
                        raise RuntimeError(f"Unsafe ZIP entry: {member.filename}")
                zf.extractall(tmp)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return tmp, lambda: shutil.rmtree(tmp, ignore_errors=True)
    raise ValueError("--source must be an existing directory or .zip file")


def build_index(source: Path) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """Build exact-relative and unique-basename indexes."""
    by_rel: dict[str, list[Path]] = {}
    by_name: dict[str, list[Path]] = {}
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = normalize_rel(path.relative_to(source).as_posix())
        if not rel:
            continue
        by_rel.setdefault(rel, []).append(path)
        by_name.setdefault(path.name, []).append(path)
    return by_rel, by_name


def find_candidates(doc: Document, by_rel: dict[str, list[Path]], by_name: dict[str, list[Path]]) -> list[Path]:
    """Prefer the DB's original path; only fall back to a unique basename."""
    db_path = normalize_rel(doc.file_name)
    if db_path and db_path in by_rel:
        return by_rel[db_path]

    basename = os.path.basename(doc.file_name or "")
    candidates = by_name.get(basename, [])
    if len(candidates) == 1:
        return candidates
    return []


def process_document(doc: Document, candidates: list[Path], source_root: Path, dry_run: bool) -> dict:
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

    if not candidates:
        result["status"] = "missing_or_ambiguous_source"
        result["error"] = "לא נמצא קובץ מקור בהתאמה מדויקת; basename fallback לא חד-משמעי"
        return result
    if len(candidates) > 1:
        result["status"] = "ambiguous_source"
        result["error"] = "נמצאו מספר קבצי מקור לאותו נתיב"
        result["source_candidates"] = [str(p) for p in candidates]
        return result

    source = candidates[0]
    result["source"] = str(source.relative_to(source_root))
    try:
        data = source.read_bytes()
    except OSError as exc:
        result["status"] = "read_failed"
        result["error"] = str(exc)
        return result

    result["bytes"] = len(data)
    result["sha256"] = sha256(data)
    if not data:
        result["status"] = "invalid_file"
        result["error"] = "קובץ ריק"
        return result

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
        downloaded = storage.download_bytes(stored_path)
        downloaded_hash = sha256(downloaded)
        if downloaded_hash != result["sha256"] or len(downloaded) != len(data):
            raise RuntimeError("אימות העלאה נכשל: hash/גודל הקובץ שהורד אינו זהה למקור")
        if source.suffix.lower() == ".pdf":
            valid, error = validate_pdf(downloaded)
            if not valid:
                raise RuntimeError(f"אימות PDF לאחר העלאה נכשל: {error}")

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
    parser.add_argument("--source", required=True, help="Directory or ZIP containing the original document files")
    parser.add_argument("--document-id", type=int, help="Restore only one document")
    parser.add_argument("--dry-run", action="store_true", help="Validate/report without uploading or changing DB")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        print(f"ERROR: source does not exist: {source}")
        return 2

    try:
        source_root, cleanup = prepare_source(source)
    except Exception as exc:
        print(f"ERROR: cannot prepare source: {exc}")
        return 2

    try:
        app = create_app()
        with app.app_context():
            if not storage.is_configured():
                print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_KEY are not configured")
                return 2

            ok, error = storage.check_connection()
            if not ok:
                print(f"ERROR: cannot connect to Supabase Storage: {error}")
                return 2

            by_rel, by_name = build_index(source_root)
            query = Document.query
            if args.document_id:
                query = query.filter(Document.id == args.document_id)
            documents = query.order_by(Document.id.asc()).all()

            print(f"Source: {source}")
            print(f"Supabase bucket: {storage.get_bucket_name()}")
            print(f"Documents selected: {len(documents)}")
            print(f"Source files indexed: {sum(len(v) for v in by_rel.values())}")
            print("Mode: DRY RUN" if args.dry_run else "Mode: RESTORE")
            print()

            counts: dict[str, int] = {}
            for doc in documents:
                candidates = find_candidates(doc, by_rel, by_name)
                result = process_document(doc, candidates, source_root, args.dry_run)
                status = result["status"]
                counts[status] = counts.get(status, 0) + 1
                print(
                    f"[{status}] document={doc.id} file={doc.file_name!r} "
                    f"source={result.get('source')!r} storage={result.get('storage_path')!r} "
                    f"error={result.get('error')!r}"
                )

            print("\nSummary:")
            for key in sorted(counts):
                print(f"  {key}: {counts[key]}")
            return 1 if counts.get("failed", 0) else 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
