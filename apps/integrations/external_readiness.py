"""Registre de préparation des intégrations réelles, volontairement inactives par défaut."""

from django.core.exceptions import ImproperlyConfigured


EXTERNAL_SERVICE_REQUIREMENTS = {
    "transactional_email": "fournisseur, domaine d’envoi, authentification et validation opérationnelle",
    "regional_payment": "prestataire, contrat, clés de production, conformité et validation financière",
    "kyc_verification": "prestataire, contrat, base légale, analyse de confidentialité et validation conformité",
    "private_object_storage": "fournisseur, chiffrement, rétention, contrôle d’accès et validation sécurité",
    "malware_scanning": "fournisseur, politique de quarantaine et validation sécurité",
    "dlp_inspection": "fournisseur, règles validées et revue de confidentialité",
    "external_security_audit": "cabinet autorisé, périmètre écrit et engagement de confidentialité",
}


def external_service_readiness() -> dict:
    """Retourne les prérequis sans exposer de secret ni prétendre à une connexion active."""
    return {
        service: {
            "enabled": False,
            "provider": "disabled",
            "activation_requires": requirement,
        }
        for service, requirement in EXTERNAL_SERVICE_REQUIREMENTS.items()
    }


def external_service_registry_integrity_report() -> dict:
    """Vérifie le contrat local « disabled » sans activer ni joindre de fournisseur."""
    registry = external_service_readiness()
    invalid_count = sum(1 for readiness in registry.values() if readiness.get("enabled") is not False or readiness.get("provider") != "disabled")
    return {"checked_count": len(registry), "invalid_count": invalid_count, "valid": invalid_count == 0}


def require_external_service_activation(*, service: str) -> None:
    requirement = EXTERNAL_SERVICE_REQUIREMENTS.get(service)
    if requirement is None:
        raise ImproperlyConfigured("Le service externe demandé est inconnu.")
    raise ImproperlyConfigured(f"Le service externe « {service} » est désactivé. Activation requise : {requirement}.")
