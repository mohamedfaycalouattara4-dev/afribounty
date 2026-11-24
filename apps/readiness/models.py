from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ReadinessCheck(models.Model):
    class Status(models.TextChoices):
        PASS = "pass", "Conforme"
        BLOCKED = "blocked", "Bloqué"
        EXTERNAL_REQUIRED = "external_required", "Validation externe requise"

    check_code = models.CharField(max_length=80)
    status = models.CharField(max_length=24, choices=Status.choices)
    evidence = models.JSONField(default=dict)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="readiness_checks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk and ReadinessCheck.objects.filter(pk=self.pk).exists():
            raise ValidationError("Un contrôle de préparation est append-only et ne peut pas être modifié.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Un contrôle de préparation ne peut pas être supprimé.")


class ResilienceExercise(models.Model):
    class Dependency(models.TextChoices):
        REDIS = "redis", "Redis"
        WORKER = "worker", "Worker"
        EXTERNAL_PROVIDER = "external_provider", "Fournisseur externe"
        DATABASE = "database", "Base de données"

    dependency = models.CharField(max_length=32, choices=Dependency.choices)
    operation = models.CharField(max_length=80)
    expected_mode = models.CharField(max_length=40)
    observed_mode = models.CharField(max_length=40)
    passed = models.BooleanField()
    evidence = models.JSONField(default=dict)
    executed_at = models.DateTimeField(auto_now_add=True)


class GoNoGoAssessment(models.Model):
    status = models.CharField(max_length=24, default="pending_human_decision")
    blockers = models.JSONField(default=list)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
