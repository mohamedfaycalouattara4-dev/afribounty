from django.conf import settings
from django.db import models


class Organization(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "En attente"
        VERIFIED = "verified", "Vérifiée"
        SUSPENDED = "suspended", "Suspendue"

    name = models.CharField(max_length=180, unique=True)
    verification_status = models.CharField(max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    privacy_retention_days = models.PositiveIntegerField(default=365)
    exports_enabled = models.BooleanField(default=False)


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Propriétaire"
        PROGRAM_MANAGER = "program_manager", "Responsable programme"
        TRIAGER = "triager", "Analyste de triage"
        VIEWER = "viewer", "Lecteur"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="afribounty_memberships")
    role = models.CharField(max_length=32, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="unique_organization_membership")]


class OrganizationVerification(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="verification")
    status = models.CharField(max_length=16, choices=Organization.VerificationStatus.choices, default=Organization.VerificationStatus.PENDING)
    reviewer_reference = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class OrganizationComplianceEvidence(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="compliance_evidence")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    label = models.CharField(max_length=120)
    local_reference = models.CharField(max_length=255)
    status = models.CharField(max_length=24, default="submitted")
    created_at = models.DateTimeField(auto_now_add=True)


class OrganizationComplianceRequest(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="compliance_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    message = models.TextField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SecurityContact(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="security_contacts")
    label = models.CharField(max_length=80)
    email = models.EmailField()
    emergency = models.BooleanField(default=False)


class ConflictDeclaration(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="conflicts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_conflicts")
    reason = models.CharField(max_length=240)
    active = models.BooleanField(default=True)


class OrganizationChangeEvent(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="change_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=96)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
