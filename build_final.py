import os
import shutil

def build_clean_project():
    print("🧹 מתחיל בבניית המערכת (מבנה נקי, ללא התנגשויות)...")

    # 1. יצירת עץ התיקיות (שים לב: אין פה תיקיית models, אלא רק קובץ בהמשך)
    directories = [
        'app', 
        'app/api', 
        'app/services', 
        'app/utils', 
        'app/templates', 
        'uploads'
    ]
    for d in directories:
        os.makedirs(d, exist_ok=True)

    # יצירת קבצי __init__.py ריקים לתיקיות הפנימיות כדי שפייתון יזהה אותן
    for d in ['app/api', 'app/services', 'app/utils']:
        open(os.path.join(d, '__init__.py'), 'a').close()

    # 2. יצירת קובץ .env
    with open('.env', 'w', encoding='utf-8') as f:
        f.write("FLASK_DEBUG=true\nSECRET_KEY=super-secret-local-key-123\nSTORAGE_DIR=uploads\n")

    # 3. הגדרת התוכן של כל קובצי המערכת
    files_to_create = {}

    # --- Requirements ---
    files_to_create['requirements.txt'] = """Flask==3.0.0
Flask-SQLAlchemy==3.1.1
PyMuPDF==1.23.8
werkzeug==3.0.1
python-dotenv==1.0.0
pywin32==306 ; sys_platform == 'win32'
"""

    # --- run.py ---
    files_to_create['run.py'] = """from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
"""

    # --- app/extensions.py ---
    files_to_create['app/extensions.py'] = """from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()
"""

    # --- app/config.py ---
    files_to_create['app/config.py'] = """import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'fire_safety.db')

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get("STORAGE_DIR", os.path.join(BASE_DIR, "uploads"))
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024
"""

    # --- app/models.py (קובץ, לא תיקייה!) ---
    files_to_create['app/models.py'] = """from .extensions import db
from datetime import datetime

class Zone(db.Model):
    __tablename__ = 'zones'
    id = db.Column(db.Integer, primary_key=True)
    zone_name = db.Column(db.String(100), nullable=False)
    file_number = db.Column(db.String(50), unique=True, nullable=False)
    requirements = db.relationship('SystemRequirement', backref='zone', lazy=True)
    documents = db.relationship('Document', backref='zone', lazy=True)

class SystemRequirement(db.Model):
    __tablename__ = 'system_requirements'
    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id'), nullable=False)
    system_name = db.Column(db.String(100), nullable=False)
    required_form = db.Column(db.String(50), nullable=False)
    documents = db.relationship('Document', backref='requirement', lazy=True)

class Document(db.Model):
    __tablename__ = 'documents'
    id = db.Column(db.Integer, primary_key=True)
    req_id = db.Column(db.Integer, db.ForeignKey('system_requirements.id'), nullable=True)
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id'), nullable=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_hash = db.Column(db.String(64), unique=True, nullable=False)
    expiry_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='active', nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
"""

    # --- app/utils/security.py ---
    files_to_create['app/utils/security.py'] = """import os
from werkzeug.utils import secure_filename

def validate_and_save_pdf(file_obj, destination_dir: str) -> str:
    if not file_obj.filename.lower().endswith('.pdf'):
        raise Exception("Only PDF files are allowed.")
    
    safe_filename = secure_filename(file_obj.filename)
    os.makedirs(destination_dir, exist_ok=True)
    safe_path = os.path.join(destination_dir, safe_filename)
    file_obj.save(safe_path)
    return safe_path
"""

    # --- app/services/dms_service.py ---
    files_to_create['app/services/dms_service.py'] = """import hashlib
import os
from datetime import date, timedelta
from app.extensions import db
from app.models import Document, Zone, SystemRequirement
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
        file_hash = DMSService.calculate_hash(filepath)
        if Document.query.filter_by(file_hash=file_hash).first():
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

        new_doc = Document(
            req_id=detected_req_id,
            zone_id=detected_zone_id,
            file_name=original_filename,
            file_path=os.path.basename(filepath),
            file_hash=file_hash,
            expiry_date=date.today() + timedelta(days=365)
        )
        db.session.add(new_doc)
        db.session.commit()
        return new_doc
"""

    # --- app/api/routes.py ---
    files_to_create['app/api/routes.py'] = """from flask import Blueprint, jsonify, request, current_app, render_template, send_from_directory
from app.extensions import db
from app.models import Zone, SystemRequirement, Document
from app.services.dms_service import DMSService
from app.utils.security import validate_and_save_pdf
from datetime import date
import platform
from werkzeug.utils import secure_filename

main_bp = Blueprint('main', __name__)

OUTLOOK_ENABLED = platform.system() == 'Windows'

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], secure_filename(filename))

@main_bp.route('/api/dashboard')
def dashboard():
    try:
        zones = Zone.query.all()
        requirements_processed = []
        alerts = {"expired": [], "critical_14": [], "warning_30": []}
        valid_count = 0
        total_reqs = 0

        for zone in zones:
            for req in zone.requirements:
                total_reqs += 1
                docs = Document.query.filter_by(req_id=req.id, status='active').order_by(Document.uploaded_at.desc()).all()
                latest = docs[0] if docs else None
                
                days_left = (latest.expiry_date - date.today()).days if latest and latest.expiry_date else None
                
                label = "missing"
                if days_left is not None:
                    if days_left < 0: label = "expired"
                    elif days_left <= 14: label = "critical"
                    elif days_left <= 30: label = "warning"
                    else: label = "valid"

                entry = {
                    "req_id": req.id, "zone_name": zone.zone_name, "file_number": zone.file_number,
                    "system_name": req.system_name, "required_form": req.required_form,
                    "file_path": latest.file_path if latest else None,
                    "file_name": latest.file_name if latest else None,
                    "expiry_date": str(latest.expiry_date) if latest else None,
                    "status": label, "doc_count": len(docs),
                    "doc_names": [d.file_name for d in docs]
                }
                requirements_processed.append(entry)
                
                if label == "valid": valid_count += 1
                elif label == "expired": alerts["expired"].append(entry)
                elif label == "critical": alerts["critical_14"].append(entry)
                elif label == "warning": alerts["warning_30"].append(entry)

        recent_docs = []
        for d in Document.query.order_by(Document.uploaded_at.desc()).limit(50).all():
            z_name = d.zone.zone_name if d.zone else "לא משויך"
            r_form = d.requirement.required_form if d.requirement else "-"
            recent_docs.append({
                "file_name": d.file_name, "zone_name": z_name, "form_code": r_form, 
                "expiry_date": str(d.expiry_date) if d.expiry_date else "", "file_path": d.file_path
            })

        score = round((valid_count / total_reqs * 100) if total_reqs else 0, 1)

        return jsonify({
            "readiness_score": score, "valid_count": valid_count, "alerts": alerts,
            "requirements": requirements_processed, "recent_docs": recent_docs,
            "outlook_enabled": OUTLOOK_ENABLED, 
            "zones": [{"id": z.id, "zone_name": z.zone_name} for z in zones]
        })
    except Exception as e:
        current_app.logger.error(f"Dashboard Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@main_bp.route('/api/documents/upload_bulk', methods=['POST'])
def upload_bulk():
    processed = 0
    for f in request.files.getlist('file'):
        if f and f.filename.lower().endswith('.pdf'):
            try:
                safe_path = validate_and_save_pdf(f, current_app.config['UPLOAD_FOLDER'])
                if DMSService.ingest_document(safe_path, f.filename):
                    processed += 1
            except Exception as e:
                current_app.logger.error(f"Upload error: {e}")
    return jsonify({"success": True, "processed": processed})

@main_bp.route('/api/outlook', methods=['POST'])
def outlook():
    if not OUTLOOK_ENABLED: return jsonify({"error": "Windows only"}), 400
    try:
        import win32com.client, pythoncom
        pythoncom.CoInitialize()
        outlook = win32.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)
        mail.To = "tservice@102.gov.il"
        mail.Subject = "הגשת מסמכי רישוי"
        mail.Body = "שלום רב,\\nמצ\\"ב מסמכים מעודכנים."
        mail.Display(False)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
"""

    # --- app/__init__.py ---
    files_to_create['app/__init__.py'] = """from flask import Flask
from .extensions import db
from .config import Config

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        seed_data()

    from .api.routes import main_bp
    app.register_blueprint(main_bp)

    return app

def seed_data():
    from .models import Zone, SystemRequirement
    if not Zone.query.first():
        zones_data = [
            ("תשתיות כלליות", "ראשי"), ("מגורים (פנימייה)", "8855-7"), 
            ("מטבח וחדר אוכל", "8859-7"), ("אולם ספורט", "8853-7"), ("בית מדרש", "8860-7")
        ]
        zones = []
        for name, fn in zones_data:
            z = Zone(zone_name=name, file_number=fn)
            db.session.add(z)
            zones.append(z)
        db.session.commit()

        reqs = [
            (zones[1].id, "ציוד כיבוי", "טופס 1"), (zones[1].id, "תחזוקת מטפים", "טופס 2"),
            (zones[1].id, "חשמל", "טופס 3"), (zones[1].id, "גילוי אש", "טופס 4"),
            (zones[1].id, "לוחות חשמל", "טופס 5"), (zones[1].id, "כריזה", "טופס 6"),
            (zones[1].id, "ספרינקלרים", "טופס 7"), (zones[1].id, "תיק שטח", "טופס 13"),
            (zones[1].id, "הדרכת עובדים", "טופס 14"), (zones[2].id, "מערכת גז", "טופס 18"),
            (zones[3].id, "שחרור עשן", "טופס 10"), (zones[4].id, "גילוי אש", "טופס 4")
        ]
        for zid, sname, form in reqs:
            db.session.add(SystemRequirement(zone_id=zid, system_name=sname, required_form=form))
        db.session.commit()
"""

    # --- app/templates/index.html ---
    files_to_create['app/templates/index.html'] = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>מערכת בטיחות אש | קמפוס ראשית</title>
<style>
:root { --bg: #0d1117; --bg-card: #161b22; --bg-hover: #1c2330; --border: rgba(255,255,255,0.07); --border-mid: rgba(255,255,255,0.12); --text: #e6edf3; --text-muted: #7d8590; --accent: #f78166; --valid: #3fb950; --warning: #e3b341; --critical: #f85149; --radius: 8px; font-family: system-ui, sans-serif;}
body { background: var(--bg); color: var(--text); margin: 0; padding: 0; line-height: 1.6; }
header { background: var(--bg-card); border-bottom: 1px solid var(--border); padding: 15px 28px; display: flex; justify-content: space-between; align-items: center; position: sticky; top:0; z-index:100; }
.btn { padding: 8px 14px; border-radius: var(--radius); font-size: 0.85rem; font-weight: bold; border: none; cursor: pointer; color: white; background: var(--border-mid); transition: 0.2s;}
.btn:hover { opacity: 0.8; } .btn-primary { background: var(--accent); } .btn-folder { background: #1f6feb; } .btn-outlook { background: #6f42c1; display: none; }
main { padding: 28px; max-width: 1400px; margin: 0 auto; }
.score-hero { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 30px; display: flex; align-items: center; gap: 40px; margin-bottom: 20px;}
.score-num { font-size: 3rem; font-weight: bold; color: var(--valid); }
.score-kpis { display: flex; gap: 30px; margin-right: auto; }
.kpi { text-align: center; } .kpi-v { font-size: 1.5rem; font-weight: bold; }
.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 20px; overflow: hidden;}
.panel-header { padding: 15px; border-bottom: 1px solid var(--border); font-weight: bold; display: flex; justify-content: space-between;}
table { width: 100%; border-collapse: collapse; }
th { text-align: right; padding: 12px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-size: 0.8rem; background: rgba(0,0,0,0.2); }
td { padding: 12px; border-bottom: 1px solid var(--border); font-size: 0.9rem;}
tr:hover td { background: var(--bg-hover); }
.pill { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; }
.pill.valid { background: rgba(63,185,80,0.15); color: var(--valid); }
.pill.warning { background: rgba(227,179,65,0.15); color: var(--warning); }
.pill.critical { background: rgba(248,81,73,0.15); color: var(--critical); }
.pill.missing { background: rgba(110,118,129,0.15); color: var(--text-muted); }
.modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 200; align-items: center; justify-content: center; }
.modal.open { display: flex; }
.modal-content { background: var(--bg-card); border-radius: var(--radius); width: 85%; height: 85%; display: flex; flex-direction: column; padding: 20px;}
iframe { flex: 1; border: none; width: 100%; border-radius: 4px; background: white;}
.toast-container { position: fixed; bottom: 20px; left: 20px; z-index: 500; display: flex; flex-direction: column; gap: 10px; }
.toast { background: var(--bg-card); border: 1px solid var(--border-mid); padding: 12px 20px; border-radius: var(--radius); font-weight: bold; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
</style>
</head>
<body>
<header>
  <div style="display:flex; align-items:center; gap:12px;">
    <div style="font-size:1.6rem;">🛡️</div>
    <div><strong>מערכת בטיחות אש Enterprise</strong><span style="display:block; font-size:0.75rem; color:var(--text-muted);">קמפוס ראשית</span></div>
  </div>
  <div style="display:flex; gap:10px; align-items:center;">
    <input type="file" id="folderInput" webkitdirectory directory multiple style="display:none" onchange="App.onFolderSelect(event)">
    <button class="btn btn-folder" onclick="document.getElementById('folderInput').click()">📁 סריקת תיקייה (DMS)</button>
    <button id="btnMail" class="btn btn-outlook" onclick="App.triggerMail()">✉️ דוא"ל אוטומטי (Outlook)</button>
  </div>
</header>
<main>
  <div class="score-hero">
    <div class="score-num" id="scoreNum">0%</div>
    <div><h3>מדד מוכנות קמפוס</h3><p style="color:var(--text-muted); font-size:0.8rem;">מחושב עפ"י מסמכים תקינים מתוך סך הדרישות</p></div>
    <div class="score-kpis">
      <div class="kpi"><div class="kpi-v" id="kpiExpired" style="color:var(--critical)">0</div><div style="font-size:0.75rem; color:var(--text-muted)">פג תוקף</div></div>
      <div class="kpi"><div class="kpi-v" id="kpiCritical" style="color:var(--accent)">0</div><div style="font-size:0.75rem; color:var(--text-muted)">קריטי (14 יום)</div></div>
      <div class="kpi"><div class="kpi-v" id="kpiWarning" style="color:var(--warning)">0</div><div style="font-size:0.75rem; color:var(--text-muted)">אזהרה (30 יום)</div></div>
      <div class="kpi"><div class="kpi-v" id="kpiValid" style="color:var(--valid)">0</div><div style="font-size:0.75rem; color:var(--text-muted)">תקין</div></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-header">
      <span>📄 סטטוס אישורים וטפסים מרוכז</span>
      <select id="filterZone" onchange="App.refresh()" style="background:var(--bg); color:white; border:1px solid var(--border); padding:4px 10px; border-radius:4px;"><option value="all">כל המתחמים</option></select>
    </div>
    <table>
      <thead><tr><th>מתחם</th><th>דרישה (טופס)</th><th>סטטוס / תוקף</th><th>פעולות</th></tr></thead>
      <tbody id="tblReqs"></tbody>
    </table>
  </div>

  <div class="panel">
    <div class="panel-header">🗂️ ארכיון מסמכים מלא (50 אחרונים)</div>
    <table>
      <thead><tr><th>שם קובץ</th><th>מתחם ששויך</th><th>דרישה שזוהתה</th><th>תאריך העלאה</th><th>פעולות</th></tr></thead>
      <tbody id="tblArchive"></tbody>
    </table>
  </div>
</main>

<div class="modal" id="pdfModal">
  <div class="modal-content">
    <div style="display:flex; justify-content:space-between; margin-bottom:15px;"><h3 id="pdfTitle">צפייה</h3><button class="btn" onclick="App.closePdf()">סגור ✕</button></div>
    <iframe id="pdfFrame"></iframe>
  </div>
</div>

<div class="toast-container" id="toastContainer"></div>

<script>
const App = (() => {
  let _data = null;
  const showToast = (msg, type='success') => {
    const c = document.getElementById('toastContainer');
    const t = document.createElement('div'); t.className = 'toast';
    t.innerHTML = (type==='success'?'✅ ':(type==='warning'?'⏳ ':'❌ '))+msg;
    c.appendChild(t); setTimeout(() => t.remove(), 4000);
  };

  async function init() {
    await refresh();
    if(_data && _data.zones) {
      const fz = document.getElementById('filterZone');
      if (fz.options.length === 1) {
          _data.zones.forEach(z => fz.innerHTML += `<option value="${z.zone_name}">${z.zone_name}</option>`);
      }
    }
  }

  async function refresh() {
    try {
        const r = await fetch('/api/dashboard');
        _data = await r.json();
        renderAll();
    } catch(e) { showToast("שגיאת רשת מול השרת", "error"); }
  }

  function renderAll() {
    if(!_data) return;
    document.getElementById('scoreNum').textContent = _data.readiness_score + '%';
    document.getElementById('kpiExpired').textContent = _data.alerts.expired.length;
    document.getElementById('kpiCritical').textContent = _data.alerts.critical_14.length;
    document.getElementById('kpiWarning').textContent = _data.alerts.warning_30.length;
    document.getElementById('kpiValid').textContent = _data.valid_count;

    if(_data.outlook_enabled) document.getElementById('btnMail').style.display = 'inline-block';

    const fz = document.getElementById('filterZone').value;
    const tBody = document.getElementById('tblReqs');
    tBody.innerHTML = '';
    
    _data.requirements.forEach(r => {
      if(fz !== 'all' && r.zone_name != fz) return;
      
      let btn = `<span style="color:var(--text-muted)">אין קובץ</span>`;
      let status = `<span class="pill missing">חסר מסמך</span>`;
      let docMeta = r.doc_count > 0 ? `<div style="font-size:0.75rem; color:var(--text-muted); margin-top:5px; line-height:1.2;">📎 סה"כ ${r.doc_count} מסמכים מוצמדים<br>${r.doc_names.join(', ')}</div>` : '';

      if (r.file_path) {
        btn = `<button class="btn btn-primary" onclick="App.previewDoc('/uploads/${r.file_path}', '${r.file_name}')">👁 צפה קובץ אחרון</button>`;
        status = `<span class="pill ${r.status}">בתוקף: ${r.expiry_date}</span>`;
      }

      tBody.innerHTML += `<tr><td><b>${r.zone_name}</b> <div style="font-size:0.75rem;color:var(--text-muted);">${r.file_number}</div></td><td><div style="font-weight:bold;">${r.system_name}</div><div style="font-size:0.8rem;color:var(--text-muted)">${r.required_form}</div>${docMeta}</td><td>${status}</td><td>${btn}</td></tr>`;
    });

    const aBody = document.getElementById('tblArchive');
    aBody.innerHTML = '';
    _data.recent_docs.forEach(doc => {
        aBody.innerHTML += `<tr><td style="font-family:monospace;">${doc.file_name}</td><td>${doc.zone_name}</td><td>${doc.form_code}</td><td style="font-size:0.8rem; color:var(--text-muted);">${doc.expiry_date}</td><td><button class="btn btn-primary" onclick="App.previewDoc('/uploads/${doc.file_path}', '${doc.file_name}')">👁 צפה</button></td></tr>`;
    });
  }

  async function onFolderSelect(e) {
    const files = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if(files.length === 0) { showToast('לא נמצאו קבצי PDF בתיקייה', 'error'); return; }
    
    showToast(`מעלה וסורק ${files.length} מסמכים... אנא המתן`, 'warning');
    const fd = new FormData();
    files.forEach(f => fd.append('file', f));
    
    try {
      const res = await fetch('/api/documents/upload_bulk', { method: 'POST', body: fd });
      const data = await res.json();
      if(data.success) { showToast(`✅ סריקה הושלמה! עובדו ${data.processed} מסמכים בהצלחה.`); refresh(); }
    } catch(err) { showToast('שגיאה בתקשורת עם השרת', 'error'); }
    e.target.value = '';
  }

  async function triggerMail() {
    await fetch('/api/outlook', { method: 'POST', headers: {'Content-Type': 'application/json'}});
    showToast('חלון חדש נפתח באאוטלוק');
  }

  return { init, refresh, onFolderSelect, triggerMail,
    previewDoc: (url, title) => { document.getElementById('pdfTitle').innerText=title; document.getElementById('pdfFrame').src=url; document.getElementById('pdfModal').classList.add('open'); },
    closePdf: () => { document.getElementById('pdfModal').classList.remove('open'); document.getElementById('pdfFrame').src=''; }
  };
})();
document.addEventListener('DOMContentLoaded', App.init);
</script>
</body>
</html>
"""

    # 4. כתיבת כל הקבצים למערכת
    for path, content in files_to_create.items():
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"📄 קובץ נכתב: {path}")

    print("\n✅ הפרויקט נבנה בהצלחה ללא שגיאות!")
    print("--------------------------------------------------")
    print("הרץ את הפקודות הבאות:")
    print("pip install -r requirements.txt")
    print("python run.py")
    print("--------------------------------------------------")

if __name__ == "__main__":
    build_clean_project()