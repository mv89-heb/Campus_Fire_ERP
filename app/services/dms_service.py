"""
dms_engine.py
Enterprise Fire Safety ERP — DMS Auto-Ingestion Engine
"""

import os
import re
import hashlib
import shutil
import logging
from datetime import date, timedelta
from pathlib import Path

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

import database_core as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dms_engine")

INCOMING_DIR = Path("incoming_files")
STORAGE_DIR  = Path("uploads")

RE_FILE_NUMBER = re.compile(r"\b(88[0-9]{2}-[0-9])\b")
RE_FORM_CODE   = re.compile(r"(טופס\s+\d+)", re.UNICODE)

def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def process_file(filepath: Path) -> dict:
    filepath = Path(filepath)
    file_hash = sha256_file(filepath)
    
    # בדיקת כפילויות
    existing = db.fetchall("SELECT id FROM documents WHERE file_hash=?", (file_hash,))
    if existing:
        return {"status": "duplicate", "doc_id": existing[0]["id"]}
        
    text = ""
    if PYMUPDF_AVAILABLE and filepath.exists():
        try:
            with fitz.open(str(filepath)) as doc:
                text = " ".join(page.get_text() for page in doc)
        except Exception as e:
            logger.warning(f"Could not read text from PDF: {e}")

    content_to_scan = text + " " + filepath.name
    
    # זיהוי מתחם
    zone_id = None
    fn_match = RE_FILE_NUMBER.search(content_to_scan)
    if fn_match:
        fn = fn_match.group(1)
        z_rows = db.fetchall("SELECT id FROM zones WHERE file_number=?", (fn,))
        if z_rows: zone_id = z_rows[0]["id"]
    
    if not zone_id:
        z_rows = db.fetchall("SELECT id FROM zones WHERE file_number='ראשי'")
        if z_rows: zone_id = z_rows[0]["id"]

    # זיהוי סוג טופס
    form_type_id = None
    form_match = RE_FORM_CODE.search(content_to_scan)
    if form_match:
        f_name = form_match.group(1)
        ft_rows = db.fetchall("SELECT id FROM form_types WHERE name=?", (f_name,))
        if ft_rows: form_type_id = ft_rows[0]["id"]

    if not form_type_id:
        ft_rows = db.fetchall("SELECT id FROM form_types WHERE name='טופס 1'")
        if ft_rows: form_type_id = ft_rows[0]["id"]

    # העברה סופית לתיקיית היעד ללא תיקיות פנימיות מורכבות
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = STORAGE_DIR / f"{file_hash}_{filepath.name}"
    shutil.copy(str(filepath), str(dest_path))

    expiry_date = (date.today() + timedelta(days=365)).isoformat()

    doc_id = db.execute("""
        INSERT INTO documents (zone_id, form_type_id, file_name, file_path, file_hash, expiry_date, status)
        VALUES (?, ?, ?, ?, ?, ?, 'active')
    """, (zone_id, form_type_id, filepath.name, str(dest_path), file_hash, expiry_date))

    return {
        "status": "ingested",
        "doc_id": doc_id,
        "zone_id": zone_id,
        "form_type_id": form_type_id
    }

def run_batch():
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    files = list(INCOMING_DIR.glob("*.pdf")) + list(INCOMING_DIR.glob("*.PDF"))
    results = []
    for f in files:
        try:
            results.append(process_file(f))
            f.unlink()  # מחיקה מתיקיית ה-Incoming לאחר עיבוד מוצלח
        except Exception as e:
            logger.error(f"Error processing batch file {f.name}: {e}")
    return results
