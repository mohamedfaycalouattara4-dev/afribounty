"""Réglages partagés, sans valeurs de production ni secret dans le dépôt."""

import os
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Variable d’environnement obligatoire absente : {name}")
    return value


def csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


def database_from_url(url: str) -> dict[str, object]:
    if url.startswith("sqlite:///"):
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": url.removeprefix("sqlite:///")}
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DJANGO_DATABASE_URL doit utiliser PostgreSQL ou SQLite de test.")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }


SECRET_KEY = env("DJANGO_SECRET_KEY", "development-only-not-for-production")
DEBUG = env("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = csv_env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = csv_env("DJANGO_CSRF_TRUSTED_ORIGINS")
default_database_url = env("DJANGO_DATABASE_URL", f"sqlite:///{BASE_DIR / 'afribounty.sqlite3'}")
DATABASES = {"default": database_from_url(default_database_url)}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.security",
    "apps.identity",
    "apps.organizations",
    "apps.programs",
    "apps.reports",
    "apps.academy",
    "apps.reputation",
    "apps.rewards",
    "apps.integrations",
    "apps.experience",
    "apps.readiness",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.core.middleware.CorrelationIdMiddleware",
    "apps.security.middleware.SensitiveRateLimitMiddleware",
    "apps.security.middleware.OperationalMetricsMiddleware",
    "apps.security.middleware.HttpSecurityHeadersMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.identity.middleware.LocalEnrollmentRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "fr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "local_secure_evidence"
MEDIA_URL = "/private-media/"
AFRIBOUNTY_EVIDENCE_STORAGE_BACKEND = env("AFRIBOUNTY_EVIDENCE_STORAGE_BACKEND", "local-private")
EVIDENCE_SCAN_REQUIRED = env("EVIDENCE_SCAN_REQUIRED", "1") == "1"
EVIDENCE_ENCRYPTION_KEY = env("EVIDENCE_ENCRYPTION_KEY", "")
METRICS_AUTH_TOKEN = env("METRICS_AUTH_TOKEN", "")
AUDIT_INTEGRITY_KEY = env("AUDIT_INTEGRITY_KEY", "development-only-audit-integrity-key-not-for-production")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "identity.User"

REDIS_URL = env("DJANGO_REDIS_URL", "redis://127.0.0.1:6379/0")
READINESS_CHECK_EXTERNAL_DEPENDENCIES = False
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
LOGIN_URL = "/access-required/"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
CSRF_TRUSTED_ORIGINS = csv_env("DJANGO_CSRF_TRUSTED_ORIGINS")
CORS_ALLOWED_ORIGINS = csv_env("DJANGO_CORS_ALLOWED_ORIGINS")
CSP_DEFAULT_SRC = ("'self'",)
CSP_BASE_URI = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_OBJECT_SRC = ("'none'",)
CSP_FORM_ACTION = ("'self'",)
RATE_LIMIT_REDIS_PREFIX = "afribounty:ratelimit:"
RATE_LIMIT_DEFAULT_WINDOW_SECONDS = 60
RATE_LIMIT_DEFAULT_REQUESTS = 60
RATE_LIMIT_BACKEND = "redis"
RATE_LIMIT_AUTH_REQUESTS = 10
RATE_LIMIT_AUTH_WINDOW_SECONDS = 300
RATE_LIMIT_UPLOAD_REQUESTS = 20
RATE_LIMIT_UPLOAD_WINDOW_SECONDS = 300
RATE_LIMIT_API_KEY_REQUESTS = 60
RATE_LIMIT_API_KEY_WINDOW_SECONDS = 60
AFRIBOUNTY_ENVIRONMENT = env("AFRIBOUNTY_ENVIRONMENT", "development")
IDENTITY_TOTP_FERNET_KEY = env("IDENTITY_TOTP_FERNET_KEY", "")
IDENTITY_EMAIL_VERIFICATION_TTL_SECONDS = 3600
IDENTITY_RECOVERY_TTL_SECONDS = 1800
IDENTITY_STEP_UP_TTL_SECONDS = 600
AUTH_RP_ID = env("AFRIBOUNTY_AUTH_RP_ID", "localhost")
AUTH_ORIGIN = env("AFRIBOUNTY_AUTH_ORIGIN", "http://localhost:8000")
AUTH_CHALLENGE_TTL_SECONDS = 120
AUTH_RECOVERY_CODE_COUNT = 10

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
