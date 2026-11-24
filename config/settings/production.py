"""Réglages stricts : l’import doit échouer plutôt que lancer une production faible."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .validators import validate_production_values

validate_production_values(
    debug=DEBUG,  # noqa: F405
    secret_key=SECRET_KEY,  # noqa: F405
    allowed_hosts=ALLOWED_HOSTS,  # noqa: F405
    database_engine=DATABASES["default"]["ENGINE"],  # noqa: F405
    redis_url=CELERY_BROKER_URL,  # noqa: F405
    csrf_trusted_origins=CSRF_TRUSTED_ORIGINS,  # noqa: F405
    environment=AFRIBOUNTY_ENVIRONMENT,  # noqa: F405
    evidence_storage_backend=AFRIBOUNTY_EVIDENCE_STORAGE_BACKEND,  # noqa: F405
    evidence_scan_required=EVIDENCE_SCAN_REQUIRED,  # noqa: F405
    evidence_encryption_key=EVIDENCE_ENCRYPTION_KEY,  # noqa: F405
    metrics_auth_token=METRICS_AUTH_TOKEN,  # noqa: F405
    audit_integrity_key=AUDIT_INTEGRITY_KEY,  # noqa: F405
)
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_RESOURCE_POLICY = "same-origin"
READINESS_CHECK_EXTERNAL_DEPENDENCIES = True
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
if not AUTH_ORIGIN.startswith("https://"):  # noqa: F405
    raise ImproperlyConfigured("AFRIBOUNTY_AUTH_ORIGIN doit être une origine HTTPS en production.")
if AUTH_RP_ID in {"localhost", "127.0.0.1"}:  # noqa: F405
    raise ImproperlyConfigured("AFRIBOUNTY_AUTH_RP_ID doit être le domaine réel en production.")
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND")  # noqa: F405
