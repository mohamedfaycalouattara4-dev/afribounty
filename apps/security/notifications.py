from apps.security.exceptions import ForbiddenNotificationContext


FORBIDDEN_CONTEXT_KEYS = {"token", "password", "proof", "evidence", "report_content"}
TEMPLATES = {
    "account_frozen": "Votre accès est temporairement gelé pour revue de sécurité. Référence : {reference}.",
    "security_review": "Une revue de sécurité est en cours. Référence : {reference}.",
}


def render_security_notification(*, template: str, context: dict[str, str]) -> str:
    if template not in TEMPLATES:
        raise ValueError("Modèle de notification inconnu.")
    if FORBIDDEN_CONTEXT_KEYS.intersection(context):
        raise ForbiddenNotificationContext("Le contexte de notification contient une donnée interdite.")
    return TEMPLATES[template].format(reference=context.get("reference", "non-disponible"))
