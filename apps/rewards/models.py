from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.reports.models import Report


class RewardEntitlement(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        APPROVED = "approved", "Approuvé"
        CANCELLED = "cancelled", "Annulé"

    report = models.OneToOneField(Report, on_delete=models.PROTECT, related_name="reward_entitlement")
    beneficiary = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reward_entitlements")
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="proposed_reward_entitlements")
    amount_xof = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="XOF")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    rationale = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)


class RewardApproval(models.Model):
    entitlement = models.ForeignKey(RewardEntitlement, on_delete=models.CASCADE, related_name="approvals")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reward_approvals")
    approved = models.BooleanField()
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["entitlement", "approver"], name="unique_reward_approval_reviewer")]


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        PROMISE = "promise", "Promesse"
        PAYMENT = "payment", "Paiement"
        FEE = "fee", "Frais"
        CANCELLATION = "cancellation", "Annulation"

    entitlement = models.ForeignKey(RewardEntitlement, on_delete=models.PROTECT, related_name="ledger_entries")
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    amount_xof = models.IntegerField()
    reference = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=128, unique=True)
    compensates = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="compensations")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk and LedgerEntry.objects.filter(pk=self.pk).exists():
            raise ValidationError("Une écriture de grand livre est append-only et ne peut pas être modifiée.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Une écriture de grand livre ne peut pas être supprimée.")


class BeneficiaryProfile(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "En attente"
        VERIFIED = "verified", "Vérifié"
        REJECTED = "rejected", "Rejeté"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="beneficiary_profile")
    provider_code = models.CharField(max_length=32)
    recipient_reference = models.CharField(max_length=160)
    verification_status = models.CharField(max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.PENDING)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="verified_beneficiaries")
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        SUBMITTED = "submitted", "Soumis sandbox"
        SUCCEEDED = "succeeded", "Réussi"
        FAILED = "failed", "Échoué"
        CANCELLED = "cancelled", "Annulé"

    entitlement = models.OneToOneField(RewardEntitlement, on_delete=models.PROTECT, related_name="payment_order")
    beneficiary = models.ForeignKey(BeneficiaryProfile, on_delete=models.PROTECT, related_name="payment_orders")
    amount_xof = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=128, unique=True)
    provider_code = models.CharField(max_length=32)
    provider_reference = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentWebhookEvent(models.Model):
    provider_code = models.CharField(max_length=32)
    event_id = models.CharField(max_length=128, unique=True)
    provider_reference = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    signature = models.CharField(max_length=128)
    occurred_at = models.DateTimeField()
    processed_at = models.DateTimeField(auto_now_add=True)


class ReconciliationReport(models.Model):
    provider_code = models.CharField(max_length=32)
    aggregate = models.JSONField(default=dict)
    exception_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reconciliation_reports")
    created_at = models.DateTimeField(auto_now_add=True)
