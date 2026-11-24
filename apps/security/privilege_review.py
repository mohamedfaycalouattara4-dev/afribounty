import hashlib
import json
import re
from collections import Counter

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.identity.models import MfaStepUpGrant, User, UserSession
from apps.integrations.models import ApiKey
from apps.organizations.models import OrganizationMembership
from apps.security.models import PrivilegeReviewSnapshot
from apps.identity.services import has_platform_permission


SENSITIVE_PLATFORM_ROLES = {
    User.PlatformRole.TRIAGER,
    User.PlatformRole.SECURITY,
    User.PlatformRole.FINANCE,
    User.PlatformRole.ADMIN,
}

SENSITIVE_ORGANIZATION_ROLES = {
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.PROGRAM_MANAGER,
    OrganizationMembership.Role.TRIAGER,
}


def privilege_review_snapshot_digest(*, snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def privilege_review_snapshot(*, now=None) -> dict:
    """Retourne uniquement des compteurs locaux ; aucun identifiant, secret ou jeton n'est divulgué."""
    now = now or timezone.now()
    expired_sessions = UserSession.objects.filter(revoked_at__isnull=True, expires_at__lte=now).count()
    expired_keys = ApiKey.objects.filter(revoked_at__isnull=True, expires_at__lte=now).count()
    return {
        "active_api_keys": ApiKey.objects.filter(revoked_at__isnull=True, expires_at__gt=now).count(),
        "active_step_up_grants": MfaStepUpGrant.objects.filter(revoked_at__isnull=True, expires_at__gt=now).count(),
        "active_user_sessions": UserSession.objects.filter(revoked_at__isnull=True, expires_at__gt=now).count(),
        "expired_unrevoked_api_keys": expired_keys,
        "expired_unrevoked_step_up_grants": MfaStepUpGrant.objects.filter(revoked_at__isnull=True, expires_at__lte=now).count(),
        "expired_unrevoked_user_sessions": expired_sessions,
        "sensitive_organization_roles": dict(
            sorted(Counter(OrganizationMembership.objects.filter(role__in=SENSITIVE_ORGANIZATION_ROLES).values_list("role", flat=True)).items())
        ),
        "sensitive_platform_roles": dict(
            sorted(Counter(User.objects.filter(platform_role__in=SENSITIVE_PLATFORM_ROLES).values_list("platform_role", flat=True)).items())
        ),
    }


def privilege_review_has_strict_failure(*, snapshot: dict) -> bool:
    return bool(snapshot["expired_unrevoked_api_keys"] or snapshot["expired_unrevoked_user_sessions"])


def privilege_review_snapshot_integrity_report() -> dict:
    checked_count = 0
    invalid_count = 0
    for archived in PrivilegeReviewSnapshot.objects.only("id", "snapshot", "snapshot_digest").iterator():
        checked_count += 1
        if privilege_review_snapshot_digest(snapshot=archived.snapshot) != archived.snapshot_digest:
            invalid_count += 1
    return {"checked_count": checked_count, "invalid_count": invalid_count, "valid": invalid_count == 0}


def _require_privilege_reviewer(*, user) -> None:
    if not (has_platform_permission(user=user, permission="platform.admin") or has_platform_permission(user=user, permission="security.review")):
        raise PermissionDenied("Un rôle sécurité ou administrateur est requis pour archiver une revue des privilèges.")


@transaction.atomic
def record_privilege_review_snapshot(*, actor, review_reference: str) -> PrivilegeReviewSnapshot:
    _require_privilege_reviewer(user=actor)
    normalized_reference = review_reference.strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{3,128}", normalized_reference):
        raise ValidationError("La référence doit contenir de 3 à 128 caractères alphanumériques, points, traits, deux-points ou soulignés.")
    snapshot = privilege_review_snapshot()
    snapshot_digest = privilege_review_snapshot_digest(snapshot=snapshot)
    return PrivilegeReviewSnapshot.objects.create(
        recorded_by=actor,
        review_reference=normalized_reference,
        snapshot=snapshot,
        snapshot_digest=snapshot_digest,
    )
