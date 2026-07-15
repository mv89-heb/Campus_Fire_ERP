from .extensions import db
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
    # --- status: מחרוזת חופשית (אין CHECK constraint / Enum ברמת ה-DB).
    # ערכים בשימוש בפועל, ומשמעותם - חובה לעדכן כאן אם מוסיפים ערך חדש:
    #   'draft'    - טיוטת חידוש בלי קובץ מצורף עדיין (ר' duplicate_permit).
    #                file_path='' (ריק, לא NULL), file_hash=placeholder ייחודי.
    #   'active'   - ברירת המחדל. אישור תקף/בתוקף, יש קובץ פיזי אמיתי.
    #   'archived' - הועבר לארכיון ידנית ע"י המשתמש. הקובץ הפיזי עדיין קיים,
    #                רק מוסתר מתצוגות ברירת המחדל.
    #   'deleted'  - נמחק ע"י Admin דרך safe_delete_document (Commit 4,
    #                Document Storage Management). הקובץ הפיזי נמחק בפועל
    #                מה-Storage, אבל file_path/file_hash/file_size *נשארים*
    #                ברשומה כפי שהיו (Option B - הוחלט במפורש לא לאפס אותם,
    #                כדי לא לגעת שוב בסכימת ה-DB). המשמעות: כל שאילתה
    #                שמחזירה "מסמכים פעילים/רלוונטיים" *חייבת* להחריג גם
    #                'deleted' וגם 'archived' - לא מספיק להחריג רק את אחד
    #                מהם! ה-Audit Log (לא העמודות האלה) הוא מקור האמת
    #                להיסטוריה המלאה של מה שהיה לפני המחיקה.
    status = db.Column(db.String(20), default='active', nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # --- שלב 2: הרחבת מודול אישורים (שדות חדשים, כולם אופציונליים) ---
    permit_number = db.Column(db.String(80), nullable=True)      # מספר אישור
    issuing_body = db.Column(db.String(150), nullable=True)      # גוף מנפיק
    issue_date = db.Column(db.Date, nullable=True)               # תאריך הנפקה
    contact_name = db.Column(db.String(120), nullable=True)      # איש קשר
    notes = db.Column(db.Text, nullable=True)                    # הערות
    category = db.Column(db.String(80), nullable=True)           # קטגוריה
    tags = db.Column(db.String(255), nullable=True)              # תגיות, מופרדות בפסיק

    # --- שלב 9: הרחבת מודול מסמכים ---
    locked = db.Column(db.Boolean, default=False, nullable=False)  # נעילה מפני עריכה/מחיקה

    # --- Document Storage Management, Commit 2: תמיכה ב-safe delete/replace ---
    # כל השדות nullable כדי שרשומות קיימות לא יידרשו ערך בזמן ה-migration.
    file_size = db.Column(db.Integer, nullable=True)               # בבתים
    deleted_at = db.Column(db.DateTime, nullable=True)             # None = לא נמחק
    deleted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)


# ============================================================================
# שלב 10 — ניהול אתרים: היררכיה של אתר -> מבנה -> קומה -> אזור
# הטבלאות האלה חדשות ואינן נוגעות בטבלת Zone הקיימת. Zone נשארת כפי שהיא
# לצורך תאימות לאחור; area_id (למטה) הוא קישור אופציונלי בלבד.
# ============================================================================

class Site(db.Model):
    __tablename__ = 'sites'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    contact_name = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(30), nullable=True)
    contact_email = db.Column(db.String(120), nullable=True)
    map_lat = db.Column(db.Float, nullable=True)
    map_lng = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    buildings = db.relationship('Building', backref='site', lazy=True, cascade='all, delete-orphan')


class Building(db.Model):
    __tablename__ = 'buildings'
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    floors = db.relationship('Floor', backref='building', lazy=True, cascade='all, delete-orphan')


class Floor(db.Model):
    __tablename__ = 'floors'
    id = db.Column(db.Integer, primary_key=True)
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # לדוגמה: "קומת קרקע", "קומה 2"
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    areas = db.relationship('Area', backref='floor', lazy=True, cascade='all, delete-orphan')


class Area(db.Model):
    __tablename__ = 'areas'
    id = db.Column(db.Integer, primary_key=True)
    floor_id = db.Column(db.Integer, db.ForeignKey('floors.id'), nullable=False)
    # קישור אופציונלי לאזור הרישוי הקיים (Zone), לצורך גישור בין המערכת
    # הישנה (תיקי רישוי) לבין ההיררכיה הפיזית החדשה. לא חובה למלא.
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id'), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================================
# תשתית מודלים לשלבים 4-8 (ספקים, ביקורות, ליקויים, משימות, ציוד).
# בשלב זה (Sprint 1) אלו טבלאות שלד: השדות המרכזיים מוגדרים כך שהיחסים בין
# הישויות יעבדו, אבל ה-API/UI המלאים לכל מודול ייבנו בספרינטים הייעודיים
# להם בהמשך (ראו Roadmap). המטרה כאן היא רק שהבסיס יהיה קיים ולא ישבור כלום.
# ============================================================================

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    supplier_number = db.Column(db.String(50), nullable=True)
    contact_name = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    phone_secondary = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    service_type = db.Column(db.String(100), nullable=True)
    service_area = db.Column(db.String(150), nullable=True)
    active_days = db.Column(db.String(100), nullable=True)
    active_hours = db.Column(db.String(100), nullable=True)
    contract_number = db.Column(db.String(50), nullable=True)
    contract_expiry = db.Column(db.Date, nullable=True)
    insurance_expiry = db.Column(db.Date, nullable=True)
    rating = db.Column(db.Integer, nullable=True)  # 1-5
    status = db.Column(db.String(20), default='active', nullable=False)
    notes = db.Column(db.Text, nullable=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Equipment(db.Model):
    __tablename__ = 'equipment'
    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(100), nullable=True)
    qr_code = db.Column(db.String(150), nullable=True)
    barcode = db.Column(db.String(150), nullable=True)
    equipment_type = db.Column(db.String(100), nullable=False)  # מטף, גלגלון, גלאי וכו'
    manufacturer = db.Column(db.String(120), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'), nullable=True)
    install_date = db.Column(db.Date, nullable=True)
    last_check_date = db.Column(db.Date, nullable=True)
    next_check_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='ok', nullable=False)  # ok / faulty / in_repair
    warranty_expiry = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    assignee = db.Column(db.String(120), nullable=True)
    priority = db.Column(db.String(20), default='normal', nullable=False)  # low/normal/high/urgent
    status = db.Column(db.String(20), default='open', nullable=False)  # open/in_progress/done/cancelled
    due_date = db.Column(db.Date, nullable=True)
    is_recurring = db.Column(db.Boolean, default=False, nullable=False)
    recurrence_rule = db.Column(db.String(50), nullable=True)  # weekly/monthly/etc
    checklist_json = db.Column(db.Text, nullable=True)  # JSON: [{"text": "...", "done": false}, ...]
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Audit(db.Model):
    __tablename__ = 'audits'
    id = db.Column(db.Integer, primary_key=True)
    audit_number = db.Column(db.String(50), nullable=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=True)
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=True)
    floor_id = db.Column(db.Integer, db.ForeignKey('floors.id'), nullable=True)
    inspector_name = db.Column(db.String(120), nullable=True)
    audit_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='scheduled', nullable=False)  # scheduled/in_progress/completed
    result = db.Column(db.String(20), nullable=True)  # pass/fail/conditional
    score = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    signature_data = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    deficiencies = db.relationship('Deficiency', backref='audit', lazy=True)


class Deficiency(db.Model):
    __tablename__ = 'deficiencies'
    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey('audits.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(20), default='medium', nullable=False)  # low/medium/high/critical
    responsible = db.Column(db.String(120), nullable=True)
    opened_at = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='open', nullable=False)  # open/in_progress/resolved
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================================
# שלב 9: היסטוריית שינויים למסמכים/אישורים
# ============================================================================

class DocumentHistory(db.Model):
    __tablename__ = 'document_history'
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False)
    field_name = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================================
# תשתית משתמשים (הקדם-דרישה לשלב 13 - הרשאות).
# חשוב: המודל וה-API החדשים הם תוספת בלבד. אין עדיין אכיפת התחברות (login
# required) על אף מסך קיים - זו החלטה מכוונת שתתקבל במפורש בספרינט הבא
# יחד עם בניית מערכת ההרשאות, כדי לא לשבור גישה למערכת הקיימת בפתאומיות.
# ============================================================================

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    role = db.Column(db.String(30), default='viewer', nullable=False)
    # super_admin / admin / manager / inspector / technician / viewer
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)


# ============================================================================
# שלב 3: מערכת תזכורות. התראה אחת פר-ישות (ref_type + ref_id), מתעדכנת
# כשהדחיפות גוברת (חלון זמן קטן יותר) ונשמרת גם אחרי שנקראה, לצורך
# היסטוריית התראות.
# ============================================================================

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    ref_type = db.Column(db.String(30), nullable=False)   # permit / task / audit / equipment
    ref_id = db.Column(db.Integer, nullable=False)
    window_days = db.Column(db.Integer, nullable=False)   # 90/60/30/14/7/1/0(=expired)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)
    dismissed = db.Column(db.Boolean, default=False, nullable=False)


# ============================================================================
# שלב 12: Audit Log מערכתי. מתעד כל פעולת יצירה/עריכה/מחיקה במודולים
# המרכזיים. אינו תלוי בהרשאות (שלב 13 טרם מיושם) - user_id יהיה ריק כשאין
# משתמש מחובר, וזה תקין ומצופה בשלב הנוכחי.
# ============================================================================

class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username_snapshot = db.Column(db.String(80), nullable=True)  # נשמר גם אם המשתמש יימחק בעתיד
    action = db.Column(db.String(20), nullable=False)  # create / update / delete
    entity_type = db.Column(db.String(40), nullable=False)  # site / permit / supplier / task / ...
    entity_id = db.Column(db.Integer, nullable=True)
    entity_label = db.Column(db.String(200), nullable=True)  # תיאור קריא (לדוגמה שם הישות)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
