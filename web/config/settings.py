import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR.parent))
LOCAL_DEV = os.environ.get("LAB_LOCAL_DEV") == "1"
if not LOCAL_DEV:
    raise ImproperlyConfigured("M0/M1 is localhost-only. Internet release requires MFA and deployment review.")
SECRET_KEY = os.environ.get("LAB_SECRET_KEY", "")
if len(SECRET_KEY) < 40:
    raise ImproperlyConfigured("Set LAB_SECRET_KEY to a random secret of at least 40 characters.")
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles", "lab",
]
MIDDLEWARE = [
    "lab.middleware.PrivateResponseMiddleware",
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "lab.middleware.SessionEpochMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"],
              "APP_DIRS": True, "OPTIONS": {"context_processors": [
                  "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
                  "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
if os.environ.get("LAB_DB", "postgres") == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("LAB_SQLITE_PATH", str(BASE_DIR.parent / ".local" / "lab.sqlite3"))}}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.environ["PGDATABASE"],
                            "USER": os.environ["PGUSER"], "PASSWORD": os.environ["PGPASSWORD"],
                            "HOST": os.environ.get("PGHOST", "127.0.0.1"), "PORT": os.environ.get("PGPORT", "5432")}}
AUTH_USER_MODEL = "lab.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = False
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
USE_TZ = True
TIME_ZONE = "America/Los_Angeles"
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR.parent / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = BASE_DIR.parent / ".local" / "mail"
DEFAULT_FROM_EMAIL = "local-recovery@localhost"
ARTIFACT_ROOT = BASE_DIR.parent / ".local" / "artifacts"
MAX_INPUT_BYTES = 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
PASSWORD_RESET_TIMEOUT = 1800
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "filters": {"redact_recovery": {"()": "lab.logging.RedactRecoveryFilter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["redact_recovery"]}},
    "loggers": {
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security.csrf": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
