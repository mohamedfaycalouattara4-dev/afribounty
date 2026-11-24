from django.core.exceptions import PermissionDenied, ValidationError


class DomainPermissionDenied(PermissionDenied):
    """Accès refusé par une règle métier de domaine."""


class InvalidIdempotencyKey(ValidationError):
    """Clé d’idempotence absente ou non conforme."""


class InvalidScope(ValidationError):
    """Actif déclaré absent, exclu, non vérifié ou indisponible au dépôt."""


class InvalidTransition(ValidationError):
    """Transition de machine à états interdite."""
