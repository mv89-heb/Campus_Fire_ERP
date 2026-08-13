import os
import secrets
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'fire_safety.db')


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


class Config:
    # Never ship a predictable signing key. Production must provide SECRET_KEY.
    ENV = os.environ.get('FLASK_ENV', os.environ.get('ENV', 'production')).strip().lower()
    IS_PRODUCTION = ENV in {'production', 'prod'}
    SECRET_KEY = os.environ.get('SECRET_KEY') or (
        None if IS_PRODUCTION else secrets.token_hex(32)
    )

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    UPLOAD_FOLDER = os.environ.get("STORAGE_DIR", os.path.join(BASE_DIR, "uploads"))
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024

    # Session hardening. Secure cookies are enabled automatically in production.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = IS_PRODUCTION or _env_bool('SESSION_COOKIE_SECURE', False)
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    PERMANENT_SESSION_LIFETIME = int(os.environ.get('SESSION_LIFETIME_SECONDS', '28800'))

    # Browser CSRF protection uses Origin/Sec-Fetch-Site checks in the request guard.
    # Set TRUSTED_ORIGINS to a comma-separated list when the frontend is on another
    # trusted origin, e.g. https://erp.example.com,https://admin.example.com
    TRUSTED_ORIGINS = tuple(
        origin.strip().rstrip('/')
        for origin in os.environ.get('TRUSTED_ORIGINS', '').split(',')
        if origin.strip()
    )

    # Supabase Storage - מקור האמת לקבצי PDF חדשים.
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
    SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "documents")

    # Application security controls.
    MAX_PDF_BYTES = int(os.environ.get('MAX_PDF_BYTES', str(100 * 1024 * 1024)))
    ALLOWED_PDF_MIME_TYPES = ('application/pdf', 'application/x-pdf')

    @classmethod
    def validate(cls):
        errors = []
        if cls.IS_PRODUCTION and not cls.SECRET_KEY:
            errors.append('SECRET_KEY must be set in production')
        if not cls.SQLALCHEMY_DATABASE_URI:
            errors.append('DATABASE_URL must be set')
        if errors:
            raise RuntimeError('; '.join(errors))
