import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.identity.services import has_platform_permission
from apps.integrations.models import (
    ApiKey,
    ApiKeyUsageEvent,
    ComplianceExportEvent,
    ContentPage,
    NotificationDelivery,
    NotificationPreference,
    OidcEnterpriseConnection,
    SupportCase,
    SupportCaseReply,
    TicketingIntegration,
    TicketingSync,
)
from apps.organizations.services import require_organization_permission
from apps.reports.models import Report
from apps.reports.sla import collect_sla_escalations
from apps.security.models import AuditEvent
from apps.security.action_gate import require_adaptive_action


ALLOWED_API_KEY_SCOPES = frozenset({"programs.read", "report.read", "reports.read", "organization.read"})


def _require_admin(*, user) -> None:
    if not has_platform_permission(user=user, permission="platform.admin"):
        raise PermissionDenied("Un rôle administrateur est requis.")


@transaction.atomic
def set_notification_preference(*, user, event_type: str, channel: str, enabled: bool, max_per_day: int, consented: bool) -> NotificationPreference:
    if not event_type.strip() or max_per_day < 1 or max_per_day > 20:
        raise ValidationError("Le type d’événement et une fréquence quotidienne entre 1 et 20 sont obligatoires.")
    preference, _ = NotificationPreference.objects.update_or_create(
        user=user,
        event_type=event_type.strip(),
        channel=channel,
        defaults={"enabled": enabled, "max_per_day": max_per_day, "consented_at": timezone.now() if consented else None},
    )
    return preference


@transaction.atomic
def queue_safe_notification(*, user, event_type: str, safe_reference: str, idempotency_key: str) -> NotificationDelivery | None:
    preference = NotificationPreference.objects.filter(user=user, event_type=event_type, enabled=True).order_by("channel").first()
    if not preference or not preference.consented_at:
        return None
    today = timezone.now().date()
    sent_count = NotificationDelivery.objects.filter(user=user, event_type=event_type, created_at__date=today).count()
    if sent_count >= preference.max_per_day:
        return None
    delivery, _ = NotificationDelivery.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={"user": user, "event_type": event_type, "channel": preference.channel, "safe_reference": safe_reference, "status": "queued"},
    )
    return delivery


@transaction.atomic
def simulate_sla_escalations(*, at=None) -> list[NotificationDelivery]:
    now = at or timezone.now()
    deliveries = []
    for escalation in collect_sla_escalations(at=now):
        if escalation.checkpoint != "triage":
            continue
        report = escalation.report
        for membership in report.organization.memberships.filter(role__in=["owner", "program_manager"]):
            delivery = queue_safe_notification(
                user=membership.user,
                event_type="sla.escalation",
                safe_reference=f"report:{report.id}:triage-overdue",
                idempotency_key=f"sla:{escalation.id}:{membership.user_id}",
            )
            if delivery:
                deliveries.append(delivery)
    return deliveries


@transaction.atomic
def sync_ticket_sandbox(*, integration: TicketingIntegration, report: Report, actor, idempotency_key: str) -> TicketingSync:
    require_organization_permission(user=actor, organization=integration.organization, permission="program.manage")
    if not integration.active or integration.provider_code != "sandbox-ticketing" or report.organization_id != integration.organization_id:
        raise PermissionDenied("L’intégration ticketing sandbox n’est pas disponible pour ce rapport.")
    sync, _ = TicketingSync.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={"integration": integration, "report": report, "ticket_reference": f"sandbox-ticket:{report.id}", "status": "synced"},
    )
    if sync.report_id != report.id:
        raise ValidationError("La clé d’idempotence ticketing est associée à un autre rapport.")
    return sync


@transaction.atomic
def revoke_oidc_connection(*, connection: OidcEnterpriseConnection, actor) -> OidcEnterpriseConnection:
    require_organization_permission(user=actor, organization=connection.organization, permission="settings.manage")
    connection.active = False
    connection.revoked_at = timezone.now()
    connection.save(update_fields=["active", "revoked_at"])
    return connection


def simulate_oidc_callback(*, connection: OidcEnterpriseConnection, issuer: str, subject: str) -> dict:
    """Contrat sandboxé : valide seulement l’émetteur déclaré et ne contacte aucun fournisseur OIDC."""
    if not connection.active or connection.revoked_at or issuer.rstrip("/") != connection.issuer.rstrip("/") or not subject.strip():
        raise PermissionDenied("La connexion OIDC sandbox est révoquée ou l’assertion est invalide.")
    return {
        "organization_id": connection.organization_id,
        "subject_reference": hashlib.sha256(f"{connection.id}:{subject.strip()}".encode()).hexdigest(),
        "scopes": connection.scopes,
    }


def create_api_key(*, owner, label: str, scopes: list[str], ttl_days: int = 30) -> tuple[ApiKey, str]:
    require_adaptive_action(user=owner, action="api_key.create")
    return _create_api_key(owner=owner, label=label, scopes=scopes, ttl_days=ttl_days)


@transaction.atomic
def _create_api_key(*, owner, label: str, scopes: list[str], ttl_days: int) -> tuple[ApiKey, str]:
    normalized_scopes = sorted(set(scope.strip() for scope in scopes if scope.strip()))
    if not label.strip() or len(label.strip()) > 80:
        raise ValidationError("Un libellé de clé entre 1 et 80 caractères est requis.")
    if not normalized_scopes or ttl_days < 1 or ttl_days > 90:
        raise ValidationError("Au moins un scope et une durée entre 1 et 90 jours sont requis.")
    unsupported_scopes = sorted(set(normalized_scopes) - ALLOWED_API_KEY_SCOPES)
    if unsupported_scopes:
        raise ValidationError("Les scopes demandés ne sont pas autorisés pour une clé API.")
    raw = f"abk_{secrets.token_urlsafe(24)}"
    key = ApiKey.objects.create(
        owner=owner,
        label=label.strip(),
        key_prefix=raw[:16],
        secret_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes=normalized_scopes,
        expires_at=timezone.now() + timedelta(days=ttl_days),
    )
    return key, raw


def rotate_api_key(*, key: ApiKey, actor) -> tuple[ApiKey, str]:
    if key.owner_id != actor.id or key.revoked_at:
        raise PermissionDenied("Seul le propriétaire d’une clé active peut la faire tourner.")
    require_adaptive_action(user=actor, action="api_key.rotate")
    with transaction.atomic():
        key.revoked_at = timezone.now()
        key.save(update_fields=["revoked_at"])
        replacement, raw = _create_api_key(owner=actor, label=key.label, scopes=key.scopes, ttl_days=max(1, (key.expires_at - timezone.now()).days))
        replacement.rotated_from = key
        replacement.save(update_fields=["rotated_from"])
    return replacement, raw


def revoke_api_key(*, key: ApiKey, actor) -> ApiKey:
    if key.owner_id != actor.id or key.revoked_at:
        raise PermissionDenied("Seul le propriétaire d’une clé active peut la révoquer.")
    require_adaptive_action(user=actor, action="api_key.revoke")
    with transaction.atomic():
        key.revoked_at = timezone.now()
        key.save(update_fields=["revoked_at"])
    return key


@transaction.atomic
def authorize_api_key(*, raw_key: str, scope: str, safe_reference: str = "service") -> ApiKey:
    if scope not in ALLOWED_API_KEY_SCOPES or not raw_key.startswith("abk_") or not (1 <= len(safe_reference) <= 128):
        raise PermissionDenied("Clé API invalide, expirée, révoquée ou dépourvue du scope demandé.")
    key = ApiKey.objects.filter(secret_hash=hashlib.sha256(raw_key.encode()).hexdigest(), revoked_at__isnull=True, expires_at__gt=timezone.now()).first()
    if not key or scope not in key.scopes:
        raise PermissionDenied("Clé API invalide, expirée, révoquée ou dépourvue du scope demandé.")
    ApiKeyUsageEvent.objects.create(key=key, scope=scope, safe_reference=safe_reference)
    return key


@transaction.atomic
def publish_content(*, actor, slug: str, title: str, body: str, published: bool) -> ContentPage:
    _require_admin(user=actor)
    if not slug.strip() or not title.strip() or not body.strip():
        raise ValidationError("Le slug, le titre et le contenu sont obligatoires.")
    page, _ = ContentPage.objects.update_or_create(
        slug=slug.strip(),
        defaults={"title": title.strip(), "body": body.strip(), "published": published, "created_by": actor},
    )
    return page


@transaction.atomic
def open_support_case(*, requester, subject: str, message: str) -> SupportCase:
    if not subject.strip() or not _safe_support_message(message):
        raise ValidationError("Le support ne doit pas recevoir de secret, preuve ou contenu d’exploitation.")
    return SupportCase.objects.create(requester=requester, subject=subject.strip(), sanitized_message=message.strip())


def _safe_support_message(message: str) -> bool:
    forbidden = ("password", "token", "secret", "preuve", "exploit", "mot de passe")
    normalized = message.strip()
    return bool(normalized and len(normalized) <= 4000 and not any(marker in normalized.lower() for marker in forbidden))


@transaction.atomic
def reply_to_support_case(*, case: SupportCase, agent, message: str) -> SupportCaseReply:
    if not has_platform_permission(user=agent, permission="security.review") and not has_platform_permission(user=agent, permission="platform.admin"):
        raise PermissionDenied("Accès support refusé.")
    if not _safe_support_message(message):
        raise ValidationError("La réponse support ne doit pas contenir de secret, preuve ou contenu d’exploitation.")
    return SupportCaseReply.objects.create(case=case, author=agent, sanitized_message=message.strip())


@transaction.atomic
def set_support_case_status(*, case: SupportCase, agent, status: str) -> SupportCase:
    if not has_platform_permission(user=agent, permission="security.review") and not has_platform_permission(user=agent, permission="platform.admin"):
        raise PermissionDenied("Accès support refusé.")
    if status not in SupportCase.Status.values:
        raise ValidationError("Le statut de support est invalide.")
    case.status = status
    case.save(update_fields=["status"])
    return case


def support_case_view(*, case: SupportCase, agent) -> dict:
    if not has_platform_permission(user=agent, permission="security.review") and not has_platform_permission(user=agent, permission="platform.admin"):
        raise PermissionDenied("Accès support refusé.")
    return {"id": case.id, "subject": case.subject, "message": case.sanitized_message, "status": case.status, "proof_access": False}


@transaction.atomic
def export_compliance_audit(*, actor, export_type: str) -> dict:
    _require_admin(user=actor)
    if export_type not in {"audit_summary", "access_summary"}:
        raise ValidationError("Le type d’export de conformité est inconnu.")
    payload = {"export_type": export_type, "audit_event_count": AuditEvent.objects.count(), "generated_at": timezone.now().isoformat()}
    ComplianceExportEvent.objects.create(actor=actor, export_type=export_type, aggregate=payload)
    return payload
