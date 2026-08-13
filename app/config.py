import os
import secrets
import warnings
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
    ENV = os.environ.get('FLASK_ENV', os.environ.get('ENV', 'development')).strip().lower()
    IS_PRODUCTION = ENV in {'production', 'prod'}
    SECRET_KEY = os.environ.get('SECRET_KEY') or (
        None if IS_PRODUCTION else secrets.token_hex(32)
    )

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{DB_PATH}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    UPLOAD_FOLDER = os.environ.get('STORAGE_DIR', os.path.join(BASE_DIR, 'uploads'))
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = IS_PRODUCTION or _env_bool('SESSION_COOKIE_SECURE', False)
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    PERMANENT_SESSION_LIFETIME = int(os.environ.get('SESSION_LIFETIME_SECONDS', '28800'))

    TRUSTED_ORIGINS = tuple(
        origin.strip().rstrip('/')
        for origin in os.environ.get('TRUSTED_ORIGINS', '').split(',')
        if origin.strip()
    )

    # A shared Redis backend is recommended for multi-instance production.
    # When Redis is not configured, fall back to memory so the application
    # remains available; the startup log clearly warns that rate-limit state
    # is process-local and should be replaced with Redis before scaling out.
    _rate_limit_storage = os.environ.get('RATELIMIT_STORAGE_URI', '').strip()
    if _rate_limit_storage:
        RATELIMIT_STORAGE_URI = _rate_limit_storage
    else:
        RATELIMIT_STORAGE_URI = 'memory://'
        if IS_PRODUCTION:
            warnings.warn(
                'RATELIMIT_STORAGE_URI is not configured; using process-local memory. '
                'Configure Redis for shared production rate limiting before scaling.',
                RuntimeWarning,
            )
    RATELIMIT_HEADERS_ENABLED = True

    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
    SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'documents')

    MAX_PDF_BYTES = int(os.environ.get('MAX_PDF_BYTES', str(100 * 1024 * 1024)))
    ALLOWED_PDF_MIME_TYPES = ('application/pdf', 'application/x-pdf')

    AUTO_CREATE_DB = _env_bool('AUTO_CREATE_DB', not IS_PRODUCTION)

    @classmethod
    def validate(cls):
        errors = []
        if cls.IS_PRODUCTION and not cls.SECRET_KEY:
            errors.append('SECRET_KEY must be set in production')
        if not cls.SQLALCHEMY_DATABASE_URI:
            errors.append('DATABASE_URL must be set')
        if errors:
            raise RuntimeError('; '.join(errors))
