"""
app.py
Enterprise Fire Safety ERP — Flask API & Security Layer
Yeshivat Ohavei Yerushalayim / G. Beit Shemesh Assets
"""

import os
import logging
from datetime import date, datetime
from pathlib import Path

from flask import (Flask, request, jsonify, send_from_directory,
                   render_template, abort)
from werkzeug.utils import secure_filename

import database_core as db
from dms_engine import process_file, sha256_file

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024   # 50 MB hard limit
app.config["UPLOAD_FOLDER"]      = os.environ.get("STORAGE_DIR", "uploads")
app.config["SECRET_KEY"]         = os.environ.get("SECRET_KEY", "dev-secret-key-123")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("app")

Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

def _days_until(expiry_val):
    if not expiry_val: 
        return None
    try:
        d = datetime.strptime(str(expiry_val).split(' ')[0], "%Y-%m-%d").date()
        return (d - date.today()).days
    except Exception: 
        return None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    fname = os.path.basename(filename)
    return send_from_directory(app.config["UPLOAD_FOLDER"], fname)

@app.route("/api/dashboard", methods=["GET"])
def dashboard_api():
    try:
        zones = db.fetchall("SELECT id, zone_name, file_number FROM zones ORDER BY id ASC")
        docs = db.fetchall("SELECT * FROM documents WHERE status='active' ORDER BY uploaded_at DESC")
        
        # בניית מפה לשליפה מהירה
        doc_map = {}
        for d in docs:
            key = f"{d.get('zone_id')}_{d.get('form_type_id')}"
            if key not in doc_map:
                doc_map[key] = d

        req_rows = db.fetchall("""
            SELECT sr.zone_id, sr.form_type_id, z.zone_name, z.file_number, ft.name as form_name
            FROM system_requirements sr
            JOIN zones z ON sr.zone_id = z.id
            JOIN form_types ft ON sr.form_type_id = ft.id
        """)

        requirements_processed = []
        stats = {"valid": 0, "warning": 0, "critical": 0, "expired": 0}

        for r in req_rows:
            key = f"{r['zone_id']}_{r['form_type_id']}"
            matched_doc = doc_map.get(key)
            
            status = "missing"
            days = None
            if matched_doc:
                days = _days_until(matched_doc.get("expiry_date"))
                if days is None:
                    status = "valid"
                elif days < 0:
                    status = "expired"
                elif days <= 14:
                    status = "critical"
                elif days <= 30:
                    status = "warning"
                else:
                    status = "valid"
            else:
                stats["expired"] += 1

            if matched_doc:
                stats[status] += 1

            requirements_processed.append({
                "zone_id": r["zone_id"],
                "zone_name": r["zone_name"],
                "file_number": r["file_number"],
                "form_name": r["form_name"],
                "file_name": matched_doc["file_name"] if matched_doc else None,
                "file_path": matched_doc["file_path"] if matched_doc else None,
                "expiry_date": str(matched_doc["expiry_date"]) if matched_doc and matched_doc["expiry_date"] else None,
                "status": status
            })

        total = len(requirements_processed)
        score = round((stats["valid"] / total * 100), 1) if total > 0 else 0

        # קבלת שמות המתחמים עבור הארכיון
        zone_names = {z['id']: z['zone_name'] for z in zones}
        recent_docs = []
        for d in docs[:15]:
            recent_docs.append({
                "file_name": d["file_name"],
                "file_path": d["file_path"],
                "zone_name": zone_names.get(d["zone_id"], "כללי"),
                "uploaded_at": str(d["uploaded_at"])
            })

        return jsonify({
            "readiness_score": score,
            "stats": stats,
            "zones": zones,
            "requirements": requirements_processed,
            "recent_docs": recent_docs
        })
    except Exception as e:
        logger.exception("Dashboard error")
        return jsonify({"error": str(e)}), 500

@app.route("/api/upload", methods=["POST"])
def upload_single_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400
    
    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        temp_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        file.save(str(temp_path))
        
        try:
            res = process_file(temp_path)
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Only PDF allowed"}), 400

@app.route("/api/dms/run-batch", methods=["POST"])
def run_dms_batch():
    from dms_engine import run_batch
    results = run_batch()
    ingested = sum(1 for r in results if r.get("status") == "ingested")
    return jsonify({"processed": len(results), "ingested": ingested, "results": results})

if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
