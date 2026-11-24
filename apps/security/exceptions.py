class SecurityDomainError(Exception):
    """Erreur métier de sécurité sans exposition de détail sensible."""


class AccountFrozen(SecurityDomainError):
    """Action refusée tant qu’une revue humaine n’a pas levé le gel."""


class ForbiddenNotificationContext(SecurityDomainError):
    """Un modèle de notification reçoit une donnée qui ne doit jamais quitter la plateforme."""
