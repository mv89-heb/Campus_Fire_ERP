import os
import shutil
from flask import Flask
from .extensions import db
from .config import Config

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    with app.app_context():
        # --- מנגנון ניקוי אוטומטי (Factory Reset) ---
        db.drop_all()  # מוחק את כל הטבלאות והמידע הפגום
        
        # מחיקת קבצי ה-PDF הישנים מהשרת
        upload_path = app.config.get('UPLOAD_FOLDER', 'uploads')
        if os.path.exists(upload_path):
            shutil.rmtree(upload_path, ignore_errors=True)
        os.makedirs(upload_path, exist_ok=True)
        # ----------------------------------------------

        # יצירת הכל מחדש בצורה נקייה
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
