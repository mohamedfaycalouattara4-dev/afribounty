from django.conf import settings
from django.db import models
from apps.organizations.models import Organization


class Program(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        PRIVATE_ACTIVE = "private_active", "Privé actif"
        PUBLIC_ACTIVE = "public_active", "Public actif"
        SUSPENDED = "suspended", "Suspendu"
        CLOSED = "closed", "Fermé"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="programs")
    name = models.CharField(max_length=180)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    policy_version = models.CharField(max_length=40)
    policy_hash = models.CharField(max_length=128)
    safe_harbor_version = models.CharField(max_length=40, blank=True)
    emergency_closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_program_name_per_organization")]


class AssetScope(models.Model):
    class AssetType(models.TextChoices):
        WEB = "web", "Application web"
        API = "api", "API"
        MOBILE = "mobile", "Application mobile"

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="scopes")
    asset = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=16, choices=AssetType.choices, default=AssetType.WEB)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    is_excluded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["program", "asset"], name="unique_asset_scope_per_program")]


class ProgramPolicyVersion(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="policy_versions")
    version = models.CharField(max_length=40)
    content_hash = models.CharField(max_length=128)
    safe_harbor_text = models.TextField()
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["program", "version"], name="unique_program_policy_version")]


class AssetOwnershipProof(models.Model):
    scope = models.OneToOneField(AssetScope, on_delete=models.CASCADE, related_name="ownership_proof")
    evidence_reference = models.CharField(max_length=256)
    reviewed_by_reference = models.CharField(max_length=128)
    approved_at = models.DateTimeField(null=True, blank=True)


class ProgramInvitation(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="invitations")
    researcher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="program_invitations")
    accepted_at = models.DateTimeField(null=True, blank=True)
    rules_accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["program", "researcher"], name="unique_program_researcher_invitation")]


class ProgramDecisionEvent(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="decision_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=96)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ProgramServiceLevel(models.Model):
    program = models.OneToOneField(Program, on_delete=models.CASCADE, related_name="service_level")
    acknowledgement_hours = models.PositiveIntegerField(default=72)
    triage_hours = models.PositiveIntegerField(default=168)
    resolution_target_days = models.PositiveIntegerField(default=30)
