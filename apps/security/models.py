from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AuditEvent(models.Model):
    """Événement append-only : modifications et suppressions ordinaires interdites."""

    occurred_at = models.DateTimeField(auto_now_add=True)
    actor_reference = models.CharField(max_length=128, blank=True)
    action = models.CharField(max_length=96)
    resource_type = models.CharField(max_length=96)
    resource_reference = models.CharField(max_length=128)
    correlation_id = models.CharField(max_length=128, db_index=True)
    metadata = models.JSONField(default=dict)
    event_nonce = models.CharField(max_length=32, unique=True)
    integrity_hash = models.CharField(max_length=64, unique=True)
    integrity_signature = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError("Un événement d’audit est append-only et ne peut pas être modifié.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Un événement d’audit ne peut pas être supprimé par le modèle ordinaire.")


class SecuritySubject(models.Model):
    """Sujet de sécurité minimal, préparatoire au modèle utilisateur du bloc identité."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Actif"
        FROZEN = "frozen", "Gelé"

    reference = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    frozen_reason = models.CharField(max_length=240, blank=True)
    frozen_at = models.DateTimeField(null=True, blank=True)
    review_required = models.BooleanField(default=False)


class RetentionRecord(models.Model):
    """Donnée de démonstration à anonymiser ; les preuves réelles arrivent au bloc rapports."""

    category = models.CharField(max_length=64)
    subject_reference = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
    anonymized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PrivilegeReviewSnapshot(models.Model):
    """Historique append-only de compteurs de privilèges, sans identifiant individuel ni secret."""

    reviewed_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="privilege_review_snapshots")
    review_reference = models.CharField(max_length=128)
    snapshot = models.JSONField(default=dict)
    snapshot_digest = models.CharField(max_length=64, db_index=True)

    class Meta:
        ordering = ["-reviewed_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk and PrivilegeReviewSnapshot.objects.filter(pk=self.pk).exists():
            raise ValidationError("Un instantané de revue des privilèges est append-only et ne peut pas être modifié.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Un instantané de revue des privilèges ne peut pas être supprimé.")
