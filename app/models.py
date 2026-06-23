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
    status = db.Column(db.String(20), default='active', nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
