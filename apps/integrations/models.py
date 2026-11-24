from django.conf import settings
from django.db import models

from apps.organizations.models import Organization
from apps.reports.models import Report


class NotificationPreference(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "Dans l’application"
        EMAIL = "email", "E-mail"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    event_type = models.CharField(max_length=64)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    enabled = models.BooleanField(default=True)
    max_per_day = models.PositiveSmallIntegerField(default=5)
    consented_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "event_type", "channel"], name="unique_notification_preference")]


class NotificationDelivery(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notification_deliveries")
    event_type = models.CharField(max_length=64)
    channel = models.CharField(max_length=16, choices=NotificationPreference.Channel.choices)
    safe_reference = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)


class LocalNotification(models.Model):
    class EventType(models.TextChoices):
        REPORT = "report", "Rapport"
        TRIAGE = "triage", "Triage"
        REWARD = "reward", "Récompense"
        CHALLENGE = "challenge", "Challenge"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="local_notifications")
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=500)
    safe_reference = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=160, unique=True)
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class TicketingIntegration(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="ticketing_integration")
    provider_code = models.CharField(max_length=32, default="sandbox-ticketing")
    project_reference = models.CharField(max_length=128)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TicketingSync(models.Model):
    integration = models.ForeignKey(TicketingIntegration, on_delete=models.CASCADE, related_name="syncs")
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="ticketing_syncs")
    ticket_reference = models.CharField(max_length=128, unique=True)
    idempotency_key = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, default="synced")
    created_at = models.DateTimeField(auto_now_add=True)


class OidcEnterpriseConnection(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="oidc_connection")
    issuer = models.URLField()
    client_identifier = models.CharField(max_length=160)
    scopes = models.JSONField(default=list)
    active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class ApiKey(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys")
    label = models.CharField(max_length=80)
    key_prefix = models.CharField(max_length=16, unique=True)
    secret_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    rotated_from = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="rotations")
    created_at = models.DateTimeField(auto_now_add=True)


class ApiKeyUsageEvent(models.Model):
    key = models.ForeignKey(ApiKey, on_delete=models.CASCADE, related_name="usage_events")
    scope = models.CharField(max_length=96)
    safe_reference = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)


class ContentPage(models.Model):
    slug = models.SlugField(max_length=96, unique=True)
    title = models.CharField(max_length=180)
    body = models.TextField()
    published = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="content_pages")
    updated_at = models.DateTimeField(auto_now=True)


class SupportCase(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        CLOSED = "closed", "Fermé"

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_cases")
    subject = models.CharField(max_length=180)
    sanitized_message = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)


class SupportCaseReply(models.Model):
    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_replies")
    sanitized_message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ComplianceExportEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="compliance_exports")
    export_type = models.CharField(max_length=48)
    aggregate = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
