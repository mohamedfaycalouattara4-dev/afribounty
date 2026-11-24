import base64
import hashlib
import hmac
import os
import struct
from datetime import timedelta

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.correlation import current_correlation_id
from apps.identity.models import (
    AccountDataRequest,
    AccountProfile,
    AuthenticationEvent,
    ConsentRecord,
    EmailVerification,
    LoginAttempt,
    MfaStepUpGrant,
    PasswordlessAccessToken,
    RecoveryRequest,
    TotpDevice,
    User,
    UserSession,
    WebAuthnCredential,
)
from apps.organizations.models import Organization, OrganizationMembership, OrganizationVerification


ROLE_PERMISSIONS = {
    User.PlatformRole.RESEARCHER: {"report.submit"},
    User.PlatformRole.ORGANIZATION: {"program.manage"},
    User.PlatformRole.TRIAGER: {"report.triage"},
    User.PlatformRole.SECURITY: {"security.review"},
    User.PlatformRole.FINANCE: {"reward.approve"},
    User.PlatformRole.ADMIN: {"platform.admin"},
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _passwordless_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


def _event(user: User | None, event_type: str, **metadata) -> AuthenticationEvent:
    return AuthenticationEvent.objects.create(
        user=user,
        event_type=event_type,
        correlation_id=current_correlation_id() or "not-provided",
        metadata=metadata,
    )


def register_user(*, email: str, password: str, consent_version: str) -> tuple[User, str]:
    normalized_email = email.strip().lower()
    user = User(username=normalized_email, email=normalized_email)
    password_validation.validate_password(password, user)
    user.set_password(password)
    user.save()
    ConsentRecord.objects.create(user=user, policy_code="terms", policy_version=consent_version, correlation_id=current_correlation_id() or "not-provided")
    token = base64.urlsafe_b64encode(os.urandom(32)).decode()
    EmailVerification.objects.create(
        user=user,
        token_hash=_hash(token),
        expires_at=timezone.now() + timedelta(seconds=settings.IDENTITY_EMAIL_VERIFICATION_TTL_SECONDS),
    )
    _event(user, "identity.registered")
    return user, token


def request_passwordless_access(*, email: str, purpose: str, requested_profile: dict | None = None) -> tuple[PasswordlessAccessToken, str]:
    normalized_email = email.strip().lower()
    if purpose not in PasswordlessAccessToken.Purpose.values:
        raise ValidationError("Le motif d’accès sans mot de passe est invalide.")
    raw_token = _passwordless_token()
    token = PasswordlessAccessToken.objects.create(
        user=User.objects.filter(email__iexact=normalized_email).first(),
        email=normalized_email,
        token_hash=_hash(raw_token),
        purpose=purpose,
        requested_profile=requested_profile or {},
        expires_at=timezone.now() + timedelta(minutes=20),
    )
    return token, raw_token


@transaction.atomic
def consume_passwordless_access(*, raw_token: str) -> User:
    token = PasswordlessAccessToken.objects.select_for_update().filter(token_hash=_hash(raw_token), consumed_at__isnull=True).first()
    if not token or token.expires_at <= timezone.now():
        raise ValidationError("Le lien de connexion est invalide, expiré ou déjà utilisé.")
    user = token.user
    if user is None:
        profile = token.requested_profile
        display_name = str(profile.get("display_name", "")).strip()
        country_code = str(profile.get("country_code", "")).strip().upper()
        account_intent = profile.get("account_intent")
        if not display_name or len(country_code) != 2 or account_intent not in AccountProfile.AccountIntent.values:
            raise ValidationError("Les informations d’inscription sont incomplètes.")
        platform_role = User.PlatformRole.RESEARCHER if account_intent == AccountProfile.AccountIntent.RESEARCHER else User.PlatformRole.ORGANIZATION
        user = User(username=token.email, email=token.email, email_verified=True, platform_role=platform_role)
        user.set_unusable_password()
        user.save()
        AccountProfile.objects.create(user=user, display_name=display_name, country_code=country_code, account_intent=account_intent)
        ConsentRecord.objects.create(
            user=user,
            policy_code="terms",
            policy_version=str(profile.get("rules_version", "platform-v1")),
            correlation_id=current_correlation_id() or "not-provided",
        )
        if account_intent == AccountProfile.AccountIntent.ORGANIZATION:
            organization_name = str(profile.get("organization_name", "")).strip()
            if not organization_name:
                raise ValidationError("Le nom de l’organisation est obligatoire.")
            organization = Organization.objects.create(name=organization_name, verification_status=Organization.VerificationStatus.PENDING)
            OrganizationMembership.objects.create(organization=organization, user=user, role=OrganizationMembership.Role.OWNER)
            OrganizationVerification.objects.create(organization=organization, status=Organization.VerificationStatus.PENDING)
        _event(user, "identity.passwordless_signup_completed")
    else:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        _event(user, "identity.passwordless_login_completed")
    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])
    return user


@transaction.atomic
def complete_account_onboarding(*, user: User) -> AccountProfile:
    profile = user.account_profile
    if not user.email_verified:
        raise PermissionDenied("La validation de l’identité locale est obligatoire avant la fin de l’onboarding.")
    profile.onboarding_completed_at = timezone.now()
    profile.save(update_fields=["onboarding_completed_at"])
    _event(user, "identity.onboarding_completed")
    return profile


def verify_email(*, token: str) -> User:
    verification = EmailVerification.objects.get(token_hash=_hash(token), consumed_at__isnull=True)
    if verification.expires_at <= timezone.now():
        raise ValidationError("Le jeton de vérification est expiré.")
    verification.consumed_at = timezone.now()
    verification.save(update_fields=["consumed_at"])
    verification.user.email_verified = True
    verification.user.save(update_fields=["email_verified"])
    _event(verification.user, "identity.email_verified")
    return verification.user


def authenticate_password(*, email: str, password: str, max_failures: int = 5) -> User:
    identity = _hash(email.strip().lower())
    failures = LoginAttempt.objects.filter(identifier_hash=identity, successful=False).order_by("-occurred_at")[:max_failures]
    if len(failures) >= max_failures and failures[max_failures - 1].occurred_at >= timezone.now() - timedelta(minutes=15):
        _event(None, "identity.login_blocked")
        raise PermissionDenied("Authentification temporairement bloquée ; réessayez plus tard.")
    user = User.objects.filter(email__iexact=email.strip()).first()
    successful = bool(user and user.check_password(password))
    LoginAttempt.objects.create(identifier_hash=identity, successful=successful, correlation_id=current_correlation_id() or "not-provided")
    _event(user, "identity.login_succeeded" if successful else "identity.login_failed")
    if not successful:
        raise PermissionDenied("Identifiants invalides.")
    return user


def _fernet() -> Fernet:
    if not settings.IDENTITY_TOTP_FERNET_KEY:
        raise ValidationError("La clé de chiffrement TOTP doit être fournie.")
    return Fernet(settings.IDENTITY_TOTP_FERNET_KEY.encode())


def _totp_code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = ((digest[offset] & 127) << 24) | (digest[offset + 1] << 16) | (digest[offset + 2] << 8) | digest[offset + 3]
    return f"{value % 1_000_000:06d}"


def enroll_totp(*, user: User, secret: str, label: str) -> TotpDevice:
    device = TotpDevice.objects.create(user=user, encrypted_secret=_fernet().encrypt(secret.encode()).decode(), label=label)
    _event(user, "mfa.totp_enrolled")
    return device


def verify_totp(*, device: TotpDevice, code: str, at_time=None) -> bool:
    if device.revoked_at:
        return False
    timestamp = int((at_time or timezone.now()).timestamp())
    counter = timestamp // 30
    secret = _fernet().decrypt(device.encrypted_secret.encode()).decode()
    if counter <= device.last_verified_counter or not hmac.compare_digest(_totp_code(secret, counter), code):
        return False
    device.last_verified_counter = counter
    device.save(update_fields=["last_verified_counter"])
    _event(device.user, "mfa.totp_verified")
    return True


def revoke_totp(*, device: TotpDevice) -> None:
    device.revoked_at = timezone.now()
    device.save(update_fields=["revoked_at"])
    _event(device.user, "mfa.totp_revoked")


def register_webauthn_credential(*, user: User, credential_id: str, public_key: str) -> WebAuthnCredential:
    return WebAuthnCredential.objects.create(user=user, credential_id=credential_id, public_key=public_key)


def create_managed_session(*, user: User, raw_session_key: str, device_label: str) -> UserSession:
    return UserSession.objects.create(
        user=user,
        session_key_hash=_hash(raw_session_key),
        device_label=device_label,
        expires_at=timezone.now() + timedelta(days=30),
    )


def revoke_session(*, session: UserSession) -> None:
    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at"])
    _event(session.user, "identity.session_revoked")


@transaction.atomic
def request_account_data_right(*, user: User, request_type: str) -> AccountDataRequest:
    if request_type not in AccountDataRequest.RequestType.values:
        raise ValidationError("Le type de demande de confidentialité est invalide.")
    if AccountDataRequest.objects.filter(user=user, request_type=request_type, state=AccountDataRequest.State.REQUESTED).exists():
        raise ValidationError("Une demande de ce type est déjà en attente de traitement local.")
    from apps.reports.models import Report

    summary = {"reports_authored": Report.objects.filter(author=user).count(), "consent_records": user.consents.count()}
    data_request = AccountDataRequest.objects.create(user=user, request_type=request_type, local_summary=summary)
    _event(user, f"privacy.{request_type}_requested", request_id=data_request.id)
    return data_request


@transaction.atomic
def cancel_account_data_right(*, user: User, request: AccountDataRequest) -> AccountDataRequest:
    if request.user_id != user.id:
        raise PermissionDenied("Cette demande de confidentialité ne relève pas de votre compte.")
    if request.state != AccountDataRequest.State.REQUESTED:
        raise ValidationError("Seule une demande en attente peut être annulée.")
    request.state = AccountDataRequest.State.CANCELLED
    request.cancelled_at = timezone.now()
    request.save(update_fields=["state", "cancelled_at"])
    _event(user, f"privacy.{request.request_type}_cancelled", request_id=request.id)
    return request


def request_recovery(*, user: User) -> str:
    token = base64.urlsafe_b64encode(os.urandom(32)).decode()
    RecoveryRequest.objects.create(user=user, token_hash=_hash(token), expires_at=timezone.now() + timedelta(seconds=settings.IDENTITY_RECOVERY_TTL_SECONDS))
    _event(user, "identity.recovery_requested")
    return token


def approve_recovery(*, request: RecoveryRequest, reviewer_reference: str) -> None:
    request.state = RecoveryRequest.State.APPROVED
    request.approved_by_reference = reviewer_reference
    request.save(update_fields=["state", "approved_by_reference"])
    _event(request.user, "identity.recovery_approved")


def consume_recovery(*, token: str) -> User:
    request = RecoveryRequest.objects.filter(token_hash=_hash(token), state=RecoveryRequest.State.APPROVED, consumed_at__isnull=True).first()
    if request is None:
        raise ValidationError("La récupération est invalide, non approuvée ou déjà consommée.")
    if request.expires_at <= timezone.now():
        raise ValidationError("La récupération est expirée.")
    request.state = RecoveryRequest.State.CONSUMED
    request.consumed_at = timezone.now()
    request.save(update_fields=["state", "consumed_at"])
    _event(request.user, "identity.recovery_consumed")
    return request.user


def has_platform_permission(*, user: User, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS[user.platform_role] or user.platform_role == User.PlatformRole.ADMIN


def grant_step_up(*, user: User, action: str) -> MfaStepUpGrant:
    now = timezone.now()
    return MfaStepUpGrant.objects.create(user=user, action=action, verified_at=now, expires_at=now + timedelta(seconds=settings.IDENTITY_STEP_UP_TTL_SECONDS))


def require_step_up(*, user: User, action: str) -> None:
    if not MfaStepUpGrant.objects.filter(user=user, action=action, revoked_at__isnull=True, expires_at__gt=timezone.now()).exists():
        raise PermissionDenied("Une vérification MFA récente est obligatoire pour cette action.")
