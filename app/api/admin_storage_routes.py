from flask import Blueprint, jsonify, request, current_app, session, render_template_string
from app.services import storage_health_service as svc
from app.services import storage_migration_service as migration_svc
from app.services import storage
from app.services.auth_service import AuthServiceError
from app.api.auth_routes import admin_required

admin_storage_bp = Blueprint('admin_storage', __name__)


@admin_storage_bp.errorhandler(AuthServiceError)
def _handle_auth_error(err):
    return jsonify({'error': str(err)}), 403


@admin_storage_bp.route('/api/admin/storage/dashboard', methods=['GET'])
@admin_required
def api_dashboard():
    result = svc.dashboard_summary(current_app.config['UPLOAD_FOLDER'])
    result['migration'] = migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/scan', methods=['GET'])
@admin_required
def api_scan():
    result = svc.scan(current_app.config['UPLOAD_FOLDER'])
    result['migration'] = migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/report', methods=['GET'])
@admin_required
def api_report():
    result = svc.scan(current_app.config['UPLOAD_FOLDER'])
    result['migration'] = migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/migration-scan', methods=['GET'])
@admin_required
def api_migration_scan():
    return jsonify(migration_svc.scan_legacy_documents(current_app.config['UPLOAD_FOLDER']))


@admin_storage_bp.route('/api/admin/storage/migration-run', methods=['POST'])
@admin_required
def api_migration_run():
    result = migration_svc.migrate(current_app.config['UPLOAD_FOLDER'], session.get('user_id'))
    return jsonify(result), (200 if result.get('success') else 409)


@admin_storage_bp.route('/api/admin/storage/cleanup-preview', methods=['POST'])
@admin_required
def api_cleanup_preview():
    orphans = svc.cleanup_preview(current_app.config['UPLOAD_FOLDER'])
    return jsonify({'orphaned_items': orphans, 'count': len(orphans)})


@admin_storage_bp.route('/api/admin/storage/cleanup-confirm', methods=['POST'])
@admin_required
def api_cleanup_confirm():
    body = request.get_json(silent=True) or {}
    paths = body.get('paths')
    if not paths or not isinstance(paths, list):
        return jsonify({'error': 'יש לספק רשימת paths לא ריקה (מה שהוצג ב-Preview)'}), 400
    result = svc.cleanup_confirm(paths, session.get('user_id'), current_app.config['UPLOAD_FOLDER'])
    return jsonify(result)


@admin_storage_bp.route('/api/admin/storage/inventory', methods=['GET'])
@admin_required
def api_storage_inventory():
    if not storage.is_configured():
        return jsonify({'configured': False, 'bucket': storage.get_bucket_name(),
                        'error': 'Supabase אינו מוגדר: חסרים SUPABASE_URL / SUPABASE_SERVICE_KEY',
                        'objects': []}), 503
    try:
        objects = storage.list_supabase_files()
        query = (request.args.get('q') or '').strip().lower()
        if query:
            objects = [item for item in objects if query in str(item.get('filename', '')).lower()
                       or query in str(item.get('basename', '')).lower()]
        return jsonify({'configured': True, 'bucket': storage.get_bucket_name(),
                        'object_count': len(objects), 'query': query or None, 'objects': objects})
    except Exception as exc:
        current_app.logger.exception('Supabase inventory check failed')
        return jsonify({'configured': True, 'bucket': storage.get_bucket_name(), 'object_count': 0,
                        'objects': [], 'error': f'לא ניתן לקרוא את Supabase Storage: {exc}'}), 502


@admin_storage_bp.route('/admin/storage/recovery', methods=['GET'])
@admin_required
def storage_recovery_page():
    return render_template_string('''<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>שחזור וניתוח מסמכים ל-Supabase</title>
<style>
body{font-family:system-ui,sans-serif;background:#f5f7fb;margin:0;padding:32px;color:#172033}.card{max-width:900px;margin:auto;background:#fff;border-radius:16px;padding:28px;box-shadow:0 8px 30px #0001}h1{margin-top:0}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}button{border:0;border-radius:10px;padding:11px 18px;cursor:pointer;font-weight:700}#preview{background:#eef2ff}#restore{background:#111827;color:white}button:disabled{opacity:.5;cursor:not-allowed}pre{white-space:pre-wrap;background:#0f172a;color:#e5e7eb;border-radius:12px;padding:16px;max-height:500px;overflow:auto}.warn{background:#fff7ed;border:1px solid #fed7aa;padding:12px;border-radius:10px;margin:12px 0}.ok{background:#ecfdf5;border:1px solid #a7f3d0;padding:12px;border-radius:10px;margin:12px 0}.err{background:#fef2f2;border:1px solid #fecaca;padding:12px;border-radius:10px;margin:12px 0;color:#991b1b}.summary{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.pill{padding:7px 11px;border-radius:999px;background:#f1f5f9;font-size:14px}</style></head>
<body><main class="card"><h1>שחזור וניתוח מסמכים מגיבוי</h1>
<p>העלה ZIP של תיקיית המסמכים המקורית. קודם מתבצע Preview בלבד. לאחר מכן ניתן לבצע שחזור <b>או לעדכן ניתוח ותאריכי תוקף למסמכים שכבר קיימים ב-Supabase</b>.</p>
<div class="warn">המערכת לא מוחקת מסמכים קיימים. מסמכים קיימים ב-Supabase עוברים הורדה, אימות SHA-256/PDF וניתוח מחדש; רק לאחר הצלחה הנתונים ב-DB מתעדכנים.</div>
<input id="zip" type="file" accept=".zip,application/zip">
<div class="actions"><button id="preview">בדיקת התאמות וניתוח</button><button id="restore" disabled>בצע שחזור / עדכון ניתוח</button></div>
<div id="summary" class="summary"></div><div id="status"></div><pre id="output">בחר ZIP כדי להתחיל.</pre>
<script>
let lastPlan=null;
const zip=document.getElementById('zip'),out=document.getElementById('output'),status=document.getElementById('status'),restore=document.getElementById('restore'),summary=document.getElementById('summary');
function renderSummary(j){const c=(j&&j.counts)||{};summary.innerHTML='';[['מתאימים',c.matched||0],['כבר ב-Supabase',c.skipped_native||0],['לא תקינים',c.invalid_pdf||0],['לא נמצאו',c.missing||0],['עמומים',c.ambiguous||0]].forEach(([label,value])=>{const el=document.createElement('span');el.className='pill';el.textContent=`${label}: ${value}`;summary.appendChild(el);});}
async function readResponse(r){const text=await r.text();try{return JSON.parse(text);}catch(e){return{success:false,error:`השרת החזיר תשובה שאינה JSON (HTTP ${r.status})`,details:text.slice(0,1200)};}}
async function send(url){const f=zip.files[0];if(!f){alert('בחר קובץ ZIP');return null;}const fd=new FormData();fd.append('backup',f,f.name);status.className='';status.textContent='מעבד...';const r=await fetch(url,{method:'POST',body:fd,credentials:'same-origin'});const j=await readResponse(r);out.textContent=JSON.stringify(j,null,2);renderSummary(j);if(!r.ok)throw new Error(j.error||`הפעולה נכשלה (HTTP ${r.status})`);return j;}
document.getElementById('preview').onclick=async()=>{restore.disabled=true;lastPlan=null;summary.innerHTML='';try{const j=await send('/api/admin/storage/recovery/preview');if(j&&j.success){lastPlan=j;const c=j.counts||{};const actionable=(c.matched||0)+(c.skipped_native||0);restore.disabled=actionable===0;status.className='ok';status.textContent=actionable?`נמצאו ${actionable} מסמכים שניתן לשחזר או לעדכן בניתוח.`:'לא נמצאו מסמכים שניתן לעבד.';}else{status.className='err';status.textContent=(j&&j.error)||'ה-Preview נכשל';}}catch(e){status.className='err';status.textContent=e.message}};
restore.onclick=async()=>{if(!lastPlan)return;const c=lastPlan.counts||{};const actionable=(c.matched||0)+(c.skipped_native||0);if(!actionable)return;if(!confirm(`לבצע שחזור/עדכון ניתוח עבור ${actionable} מסמכים בטוחים?`))return;restore.disabled=true;try{const j=await send('/api/admin/storage/recovery/restore');status.className=j&&j.success?'ok':'err';status.textContent=j&&j.success?`הפעולה הושלמה: ${((j.restored||[]).length)} שוחזרו, ${((j.analyzed||[]).length)} נותחו מחדש.`:'הפעולה הושלמה חלקית — בדוק את הדוח';}catch(e){status.className='err';status.textContent=e.message}finally{restore.disabled=false}};
</script></main></body></html>''')


def _uploaded_zip():
    uploaded = request.files.get('backup')
    if not uploaded or not uploaded.filename:
        return None, ('יש להעלות קובץ ZIP בשם backup', 400)
    if not uploaded.filename.lower().endswith('.zip'):
        return None, ('יש להעלות קובץ ZIP בלבד', 400)
    max_bytes = int(current_app.config.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))
    data = uploaded.read(max_bytes + 1)
    if len(data) > max_bytes:
        return None, ('קובץ הגיבוי גדול מהמגבלה המותרת', 413)
    if not data:
        return None, ('קובץ הגיבוי ריק', 400)
    return data, None


@admin_storage_bp.route('/api/admin/storage/recovery/preview', methods=['POST'])
@admin_required
def storage_recovery_preview():
    try:
        data,error=_uploaded_zip()
        if error:
            message,status=error
            return jsonify({'success':False,'error':message}),status
        result=migration_svc.plan_zip_restore(data)
        return jsonify(result),(200 if result.get('success') else 409)
    except Exception as exc:
        current_app.logger.exception('Document recovery preview failed')
        return jsonify({'success':False,'error':'שגיאה פנימית ביצירת Preview','details':str(exc)}),500


@admin_storage_bp.route('/api/admin/storage/recovery/restore', methods=['POST'])
@admin_required
def storage_recovery_restore():
    try:
        data,error=_uploaded_zip()
        if error:
            message,status=error
            return jsonify({'success':False,'error':message}),status
        result=migration_svc.restore_zip(data,session.get('user_id'))
        return jsonify(result),(200 if result.get('success') else 409)
    except Exception as exc:
        current_app.logger.exception('Document recovery restore failed')
        return jsonify({'success':False,'error':'שגיאה פנימית בשחזור המסמכים','details':str(exc)}),500
