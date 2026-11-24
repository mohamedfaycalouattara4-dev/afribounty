from django.core.exceptions import ImproperlyConfigured
from cryptography.fernet import Fernet


def validate_production_values(
    *,
    debug: bool,
    secret_key: str,
    allowed_hosts: list[str],
    database_engine: str,
    redis_url: str,
    csrf_trusted_origins: list[str] | None = None,
    environment: str = "production",
    evidence_storage_backend: str = "private-object",
    evidence_scan_required: bool = True,
    evidence_encryption_key: str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    metrics_auth_token: str = "x" * 32,
    audit_integrity_key: str = "x" * 32,
) -> None:
    if debug:
        raise ImproperlyConfigured("DEBUG doit être désactivé en production.")
    if secret_key == "development-only-not-for-production" or len(secret_key) < 50:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY doit être fourni et robuste en production.")
    if not allowed_hosts:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS doit être défini en production.")
    if database_engine != "django.db.backends.postgresql":
        raise ImproperlyConfigured("La production AfriBounty requiert PostgreSQL.")
    if not redis_url.startswith(("redis://", "rediss://")):
        raise ImproperlyConfigured("La production AfriBounty requiert un broker Redis privé.")
    if environment != "production":
        raise ImproperlyConfigured("AFRIBOUNTY_ENVIRONMENT doit valoir production dans ce profil.")
    if any(host in {"*", "localhost", "127.0.0.1"} for host in allowed_hosts):
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS ne peut contenir ni joker ni hôte local en production.")
    if not csrf_trusted_origins or any(not origin.startswith("https://") for origin in csrf_trusted_origins):
        raise ImproperlyConfigured("DJANGO_CSRF_TRUSTED_ORIGINS doit contenir des origines HTTPS explicites en production.")
    if evidence_storage_backend != "private-object":
        raise ImproperlyConfigured("La production requiert un stockage de preuves privé de type objet.")
    if not evidence_scan_required:
        raise ImproperlyConfigured("L’analyse de sécurité des preuves doit être obligatoire en production.")
    try:
        Fernet(evidence_encryption_key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("La clé de chiffrement des preuves doit être une clé Fernet valide en production.") from exc
    if len(metrics_auth_token) < 32:
        raise ImproperlyConfigured("Un jeton d’observabilité distinct et robuste est obligatoire en production.")
    if audit_integrity_key == "development-only-audit-integrity-key-not-for-production" or len(audit_integrity_key) < 32:
        raise ImproperlyConfigured("Une clé distincte et robuste de signature des journaux d’audit est obligatoire en production.")
