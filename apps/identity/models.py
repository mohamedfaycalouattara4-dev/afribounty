from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    class PlatformRole(models.TextChoices):
        RESEARCHER = "researcher", "Chercheur"
        ORGANIZATION = "organization", "Organisation"
        TRIAGER = "triager", "Triager"
        SECURITY = "security", "Sécurité"
        FINANCE = "finance", "Finance"
        ADMIN = "admin", "Administrateur"

    # Conservé uniquement comme contact métier optionnel ; jamais utilisé pour l’authentification.
    email = models.EmailField(unique=True, null=True, blank=True)
    email_verified = models.BooleanField(default=False)
    platform_role = models.CharField(max_length=24, choices=PlatformRole.choices, default=PlatformRole.RESEARCHER)

    def __str__(self) -> str:
        return self.username


class ConsentRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents")
    policy_code = models.CharField(max_length=64)
    policy_version = models.CharField(max_length=32)
    accepted_at = models.DateTimeField(auto_now_add=True)
    correlation_id = models.CharField(max_length=128)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "policy_code", "policy_version"], name="identity_consent_version_unique")]


class EmailVerification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_verifications")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)


class LoginAttempt(models.Model):
    identifier_hash = models.CharField(max_length=64, db_index=True)
    successful = models.BooleanField(default=False)
    occurred_at = models.DateTimeField(auto_now_add=True)
    correlation_id = models.CharField(max_length=128)


class TotpDevice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp_devices")
    encrypted_secret = models.TextField()
    label = models.CharField(max_length=80)
    last_verified_counter = models.BigIntegerField(default=-1)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class WebAuthnCredential(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webauthn_credentials")
    credential_id = models.CharField(max_length=512, unique=True)
    public_key = models.TextField()
    sign_count = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class UserSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="managed_sessions")
    session_key_hash = models.CharField(max_length=64, unique=True)
    device_label = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)


class RecoveryRequest(models.Model):
    class State(models.TextChoices):
        REQUESTED = "requested", "Demandée"
        APPROVED = "approved", "Approuvée"
        CONSUMED = "consumed", "Consommée"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_requests")
    token_hash = models.CharField(max_length=64, unique=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.REQUESTED)
    expires_at = models.DateTimeField()
    approved_by_reference = models.CharField(max_length=128, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)


class MfaStepUpGrant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_grants")
    action = models.CharField(max_length=96)
    verified_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)


class AuthenticationEvent(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=96)
    correlation_id = models.CharField(max_length=128)
    metadata = models.JSONField(default=dict)

    def save(self, *args, **kwargs):
        if self.pk and AuthenticationEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError("Un événement d’authentification ne peut pas être modifié.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Un événement d’authentification ne peut pas être supprimé.")


class AccountProfile(models.Model):
    class AccountIntent(models.TextChoices):
        RESEARCHER = "researcher", "Chercheur"
        ORGANIZATION = "organization", "Organisation"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_profile")
    display_name = models.CharField(max_length=80)
    country_code = models.CharField(max_length=2)
    account_intent = models.CharField(max_length=16, choices=AccountIntent.choices)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AccountPrivacyPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="privacy_preference")
    retention_days = models.PositiveIntegerField(default=365)
    exports_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class AccountDataRequest(models.Model):
    class RequestType(models.TextChoices):
        EXPORT = "export", "Export de données"
        ERASURE = "erasure", "Effacement contrôlé"

    class State(models.TextChoices):
        REQUESTED = "requested", "Demandée"
        CANCELLED = "cancelled", "Annulée"
        COMPLETED = "completed", "Traitée"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="data_rights_requests")
    request_type = models.CharField(max_length=16, choices=RequestType.choices)
    state = models.CharField(max_length=16, choices=State.choices, default=State.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    local_summary = models.JSONField(default=dict)


class LocalAuthChallenge(models.Model):
    class Purpose(models.TextChoices):
        REGISTER = "register", "Enregistrement d’une passkey"
        LOGIN = "login", "Connexion par passkey"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="local_auth_challenges")
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    challenge = models.CharField(max_length=128, unique=True)
    session_key_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RecoveryCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64, unique=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PasswordlessAccessToken(models.Model):
    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Inscription"
        LOGIN = "login", "Connexion"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="passwordless_access_tokens")
    email = models.EmailField(db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    requested_profile = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
