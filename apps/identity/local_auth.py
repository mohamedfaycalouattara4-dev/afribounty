"""Authentification locale autonome : aucune livraison de code hors plateforme."""

import base64
import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from webauthn.authentication.generate_authentication_options import generate_authentication_options
from webauthn.authentication.verify_authentication_response import verify_authentication_response
from webauthn.helpers import bytes_to_base64url, options_to_json_dict
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from webauthn.registration.generate_registration_options import generate_registration_options
from webauthn.registration.verify_registration_response import verify_registration_response

from apps.core.correlation import current_correlation_id
from apps.identity.models import (
    AccountProfile,
    AuthenticationEvent,
    ConsentRecord,
    LocalAuthChallenge,
    LoginAttempt,
    RecoveryCode,
    User,
    WebAuthnCredential,
)
from apps.organizations.models import Organization, OrganizationMembership, OrganizationVerification

IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,47}$")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _challenge_digest(challenge: bytes) -> str:
    return base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")


def _session_hash(request) -> str:
    if not request.session.session_key:
        request.session.save()
    return _digest(request.session.session_key or "")


def _event(user: User | None, event_type: str, **metadata) -> AuthenticationEvent:
    return AuthenticationEvent.objects.create(
        user=user,
        event_type=event_type,
        correlation_id=current_correlation_id() or "not-provided",
        metadata=metadata,
    )


def normalize_identifier(value: str) -> str:
    identifier = value.strip().lower()
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise ValidationError("L’identifiant doit contenir 3 à 48 caractères : lettres minuscules, chiffres, point, tiret ou underscore.")
    return identifier


@transaction.atomic
def create_local_account(
    *,
    identifier: str,
    password: str,
    consent_version: str,
    account_intent: str,
    display_name: str,
    country_code: str,
    organization_name: str = "",
) -> tuple[User, list[str]]:
    identifier = normalize_identifier(identifier)
    if User.objects.filter(username__iexact=identifier).exists():
        raise ValidationError("Cet identifiant est déjà utilisé.")
    if account_intent not in AccountProfile.AccountIntent.values:
        raise ValidationError("Le type de compte est invalide.")
    if not display_name.strip() or len(country_code.strip()) != 2:
        raise ValidationError("Le nom affiché et le code pays sont obligatoires.")
    if account_intent == AccountProfile.AccountIntent.ORGANIZATION and not organization_name.strip():
        raise ValidationError("Le nom de l’organisation est obligatoire.")

    user = User(username=identifier, email=None, email_verified=True)
    password_validation.validate_password(password, user)
    user.set_password(password)
    user.platform_role = User.PlatformRole.RESEARCHER if account_intent == AccountProfile.AccountIntent.RESEARCHER else User.PlatformRole.ORGANIZATION
    user.save()
    AccountProfile.objects.create(
        user=user,
        display_name=display_name.strip(),
        country_code=country_code.strip().upper(),
        account_intent=account_intent,
    )
    ConsentRecord.objects.create(
        user=user,
        policy_code="terms",
        policy_version=consent_version,
        correlation_id=current_correlation_id() or "not-provided",
    )
    if account_intent == AccountProfile.AccountIntent.ORGANIZATION:
        organization = Organization.objects.create(name=organization_name.strip(), verification_status=Organization.VerificationStatus.PENDING)
        OrganizationMembership.objects.create(organization=organization, user=user, role=OrganizationMembership.Role.OWNER)
        OrganizationVerification.objects.create(organization=organization, status=Organization.VerificationStatus.PENDING)
    codes = issue_recovery_codes(user=user)
    _event(user, "identity.local_registered", identifier=identifier, recovery_code_count=len(codes))
    return user, codes


def issue_recovery_codes(*, user: User, count: int | None = None) -> list[str]:
    count = count or settings.AUTH_RECOVERY_CODE_COUNT
    RecoveryCode.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=timezone.now())
    raw_codes: list[str] = []
    for _ in range(count):
        raw = secrets.token_hex(8).upper()
        formatted = f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
        RecoveryCode.objects.create(user=user, code_hash=_digest(raw))
        raw_codes.append(formatted)
    return raw_codes


def _normalize_recovery_code(value: str) -> str:
    return value.replace("-", "").replace(" ", "").strip().upper()


@transaction.atomic
def consume_recovery_code(*, user: User, code: str) -> None:
    normalized = _normalize_recovery_code(code)
    if len(normalized) != 16:
        raise ValidationError("Le code de récupération est invalide.")
    recovery = RecoveryCode.objects.select_for_update().filter(user=user, code_hash=_digest(normalized), consumed_at__isnull=True).first()
    if recovery is None:
        _event(user, "identity.recovery_code_rejected")
        raise PermissionDenied("Le code de récupération est invalide ou déjà utilisé.")
    recovery.consumed_at = timezone.now()
    recovery.save(update_fields=["consumed_at"])
    user.managed_sessions.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    _event(user, "identity.recovery_code_consumed")


def _new_challenge(*, user: User, purpose: str, request) -> tuple[LocalAuthChallenge, bytes]:
    request.session.cycle_key()
    challenge = secrets.token_bytes(32)
    record = LocalAuthChallenge.objects.create(
        user=user,
        purpose=purpose,
        challenge=_challenge_digest(challenge),
        session_key_hash=_session_hash(request),
        expires_at=timezone.now() + timedelta(seconds=settings.AUTH_CHALLENGE_TTL_SECONDS),
    )
    return record, challenge


def registration_options_for(*, user: User, request) -> dict:
    record, challenge = _new_challenge(user=user, purpose=LocalAuthChallenge.Purpose.REGISTER, request=request)
    credentials = [
        PublicKeyCredentialDescriptor(id=base64.urlsafe_b64decode(credential.credential_id + "=" * (-len(credential.credential_id) % 4)))
        for credential in user.webauthn_credentials.filter(revoked_at__isnull=True)
    ]
    options = generate_registration_options(
        rp_id=settings.AUTH_RP_ID,
        rp_name="AfriBounty",
        user_name=user.username,
        user_id=hashlib.sha256(f"afribounty-user:{user.pk}".encode()).digest()[:32],
        user_display_name=user.account_profile.display_name,
        challenge=challenge,
        timeout=60000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=credentials,
        supported_pub_key_algs=[COSEAlgorithmIdentifier.EDDSA, COSEAlgorithmIdentifier.ECDSA_SHA_256, COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256],
    )
    request.session["local_registration_challenge_id"] = record.id
    return options_to_json_dict(options=options)


@transaction.atomic
def verify_registration(*, user: User, request, credential: dict) -> WebAuthnCredential:
    challenge_id = request.session.get("local_registration_challenge_id")
    challenge = (
        LocalAuthChallenge.objects.select_for_update()
        .filter(
            pk=challenge_id,
            user=user,
            purpose=LocalAuthChallenge.Purpose.REGISTER,
            consumed_at__isnull=True,
        )
        .first()
    )
    if not challenge or challenge.expires_at <= timezone.now() or challenge.session_key_hash != _session_hash(request):
        raise PermissionDenied("La cérémonie de sécurité est expirée ou invalide. Recommencez l’enregistrement.")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64.urlsafe_b64decode(challenge.challenge + "=" * (-len(challenge.challenge) % 4)),
            expected_rp_id=settings.AUTH_RP_ID,
            expected_origin=settings.AUTH_ORIGIN,
            require_user_presence=True,
            require_user_verification=True,
        )
    except Exception as exc:
        raise PermissionDenied("La clé de sécurité n’a pas pu être vérifiée. Aucun changement n’a été enregistré.") from exc
    if not verified.user_verified:
        raise PermissionDenied("La vérification locale de l’utilisateur est obligatoire.")
    credential_id = bytes_to_base64url(verified.credential_id)
    if WebAuthnCredential.objects.filter(credential_id=credential_id, revoked_at__isnull=True).exists():
        raise ValidationError("Cette clé de sécurité est déjà enregistrée.")
    saved = WebAuthnCredential.objects.create(
        user=user,
        credential_id=credential_id,
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=verified.sign_count,
    )
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])
    request.session.pop("local_registration_challenge_id", None)
    _event(user, "identity.passkey_registered", user_verified=True)
    return saved


def authentication_options_for(*, user: User, request) -> dict:
    credentials = [
        PublicKeyCredentialDescriptor(id=base64.urlsafe_b64decode(credential.credential_id + "=" * (-len(credential.credential_id) % 4)))
        for credential in user.webauthn_credentials.filter(revoked_at__isnull=True)
    ]
    if not credentials:
        raise PermissionDenied("Aucune passkey active n’est enregistrée pour ce compte.")
    record, challenge = _new_challenge(user=user, purpose=LocalAuthChallenge.Purpose.LOGIN, request=request)
    options = generate_authentication_options(
        rp_id=settings.AUTH_RP_ID,
        challenge=challenge,
        timeout=60000,
        allow_credentials=credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    request.session["local_login_challenge_id"] = record.id
    return options_to_json_dict(options=options)


@transaction.atomic
def verify_authentication(*, user: User, request, credential: dict) -> WebAuthnCredential:
    challenge_id = request.session.get("local_login_challenge_id")
    challenge = (
        LocalAuthChallenge.objects.select_for_update()
        .filter(
            pk=challenge_id,
            user=user,
            purpose=LocalAuthChallenge.Purpose.LOGIN,
            consumed_at__isnull=True,
        )
        .first()
    )
    if not challenge or challenge.expires_at <= timezone.now() or challenge.session_key_hash != _session_hash(request):
        raise PermissionDenied("La cérémonie de connexion est expirée ou invalide. Recommencez.")
    credential_id = str(credential.get("rawId") or credential.get("id") or "")
    stored = user.webauthn_credentials.filter(credential_id=credential_id, revoked_at__isnull=True).first()
    if stored is None:
        raise PermissionDenied("La clé de sécurité ne correspond pas à ce compte.")
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64.urlsafe_b64decode(challenge.challenge + "=" * (-len(challenge.challenge) % 4)),
            expected_rp_id=settings.AUTH_RP_ID,
            expected_origin=settings.AUTH_ORIGIN,
            credential_public_key=base64.urlsafe_b64decode(stored.public_key + "=" * (-len(stored.public_key) % 4)),
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        _event(user, "identity.passkey_rejected")
        raise PermissionDenied("La clé de sécurité n’a pas pu être vérifiée.") from exc
    if verified.new_sign_count and verified.new_sign_count <= stored.sign_count:
        stored.revoked_at = timezone.now()
        stored.save(update_fields=["revoked_at"])
        _event(user, "identity.passkey_revoked_counter_rollback")
        raise PermissionDenied("Une anomalie de compteur a été détectée ; cette clé a été révoquée par précaution.")
    stored.sign_count = verified.new_sign_count
    stored.save(update_fields=["sign_count"])
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])
    request.session.pop("local_login_challenge_id", None)
    _event(user, "identity.passkey_login_succeeded", user_verified=True)
    return stored


def authenticate_local_password(*, identifier: str, password: str, max_failures: int = 5) -> User:
    normalized = normalize_identifier(identifier)
    identity_hash = _digest(normalized)
    recent = list(
        LoginAttempt.objects.filter(
            identifier_hash=identity_hash,
            successful=False,
            occurred_at__gte=timezone.now() - timedelta(minutes=15),
        ).order_by("-occurred_at")[:max_failures]
    )
    if len(recent) >= max_failures:
        _event(None, "identity.local_login_blocked")
        raise PermissionDenied("Trop de tentatives. Réessayez plus tard.")
    user = User.objects.filter(username__iexact=normalized, is_active=True).first()
    successful = bool(user and user.check_password(password))
    LoginAttempt.objects.create(identifier_hash=identity_hash, successful=successful, correlation_id=current_correlation_id() or "not-provided")
    _event(user if successful else None, "identity.local_login_succeeded" if successful else "identity.local_login_failed")
    if not successful:
        raise PermissionDenied("Identifiant ou mot de passe invalide.")
    return user
