import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.common.errors import InvalidScope
from apps.identity.services import has_platform_permission
from apps.organizations.models import Organization
from apps.organizations.services import record_organization_change, require_organization_permission
from apps.programs.models import AssetOwnershipProof, AssetScope, Program, ProgramDecisionEvent, ProgramInvitation, ProgramPolicyVersion, ProgramServiceLevel
from apps.programs.access import emergency_close, resume_emergency_closed_program
from apps.security.action_gate import require_adaptive_action


def normalize_asset(asset: str) -> str:
    return asset.strip().lower().rstrip("/")


def assert_asset_is_submittable(*, program: Program, asset: str) -> AssetScope:
    """Vérifie un scope strict ; les wildcards sont volontairement hors ZIP 00."""
    if program.status != Program.Status.PRIVATE_ACTIVE:
        raise InvalidScope("Le programme n’accepte pas de soumission dans son état actuel.")
    target = normalize_asset(asset)
    scopes = list(program.scopes.all())
    if any(scope.is_excluded and normalize_asset(scope.asset) == target for scope in scopes):
        raise InvalidScope("L’actif est explicitement exclu du programme.")
    for scope in scopes:
        if not scope.is_excluded and scope.is_active and scope.is_verified and normalize_asset(scope.asset) == target:
            return scope
    raise InvalidScope("L’actif ne figure pas dans un scope actif et vérifié.")


@transaction.atomic
def create_program_draft(
    *,
    user,
    organization: Organization,
    name: str,
    asset: str,
    asset_type: str,
    safe_harbor_text: str,
    acknowledgement_hours: int,
    triage_hours: int,
    resolution_target_days: int,
) -> Program:
    """Crée un brouillon non publiable avec scope non vérifié et politique versionnée."""
    require_organization_permission(user=user, organization=organization, permission="program.manage")
    if organization.verification_status != Organization.VerificationStatus.VERIFIED:
        raise PermissionDenied("La vérification de l’organisation est requise avant la création d’un programme.")
    normalized_name = name.strip()
    normalized_asset = normalize_asset(asset)
    normalized_policy = safe_harbor_text.strip()
    if len(normalized_name) < 3 or len(normalized_asset) < 3 or len(normalized_policy) < 30:
        raise ValidationError("Le titre, un actif de scope et une politique safe-harbor détaillée sont obligatoires.")
    if asset_type not in AssetScope.AssetType.values:
        raise ValidationError("Le type d’actif est invalide.")
    if min(acknowledgement_hours, triage_hours, resolution_target_days) < 1:
        raise ValidationError("Les objectifs de délai doivent être strictement positifs.")
    if Program.objects.filter(organization=organization, name=normalized_name).exists():
        raise ValidationError("Un programme portant ce titre existe déjà pour cette organisation.")
    policy_version = "draft-v1"
    policy_hash = hashlib.sha256(normalized_policy.encode("utf-8")).hexdigest()
    program = Program.objects.create(
        organization=organization,
        name=normalized_name,
        status=Program.Status.DRAFT,
        policy_version=policy_version,
        policy_hash=policy_hash,
        safe_harbor_version=policy_version,
    )
    AssetScope.objects.create(program=program, asset=normalized_asset, asset_type=asset_type, is_verified=False)
    ProgramPolicyVersion.objects.create(
        program=program,
        version=policy_version,
        content_hash=policy_hash,
        safe_harbor_text=normalized_policy,
        active=False,
    )
    ProgramServiceLevel.objects.create(
        program=program,
        acknowledgement_hours=acknowledgement_hours,
        triage_hours=triage_hours,
        resolution_target_days=resolution_target_days,
    )
    record_organization_change(
        organization=organization,
        actor=user,
        action="program.draft_created",
        metadata={"program_id": program.id, "policy_version": policy_version},
    )
    return program


@transaction.atomic
def add_program_draft_scope(*, user, organization: Organization, program: Program, asset: str, asset_type: str) -> AssetScope:
    """Ajoute un scope non vérifié à un programme encore à l’état brouillon."""
    require_organization_permission(user=user, organization=organization, permission="program.manage")
    if organization.verification_status != Organization.VerificationStatus.VERIFIED:
        raise PermissionDenied("La vérification de l’organisation est requise avant toute modification de scope.")
    if program.organization_id != organization.id:
        raise PermissionDenied("Le programme ne relève pas de cette organisation.")
    if program.status != Program.Status.DRAFT:
        raise PermissionDenied("Seul un programme brouillon peut recevoir un nouveau scope.")
    normalized_asset = normalize_asset(asset)
    if len(normalized_asset) < 3:
        raise ValidationError("Un actif de scope valide est obligatoire.")
    if asset_type not in AssetScope.AssetType.values:
        raise ValidationError("Le type d’actif est invalide.")
    if AssetScope.objects.filter(program=program, asset=normalized_asset).exists():
        raise ValidationError("Cet actif est déjà déclaré dans le scope du programme.")
    scope = AssetScope.objects.create(
        program=program,
        asset=normalized_asset,
        asset_type=asset_type,
        is_verified=False,
        is_active=True,
        is_excluded=False,
    )
    record_organization_change(
        organization=organization,
        actor=user,
        action="program.draft_scope_added",
        metadata={"program_id": program.id, "scope_id": scope.id, "asset_type": scope.asset_type},
    )
    return scope


@transaction.atomic
def review_program_scope(*, administrator, scope: AssetScope, evidence_reference: str, reviewer_reference: str) -> AssetScope:
    if not has_platform_permission(user=administrator, permission="platform.admin"):
        raise PermissionDenied("Une autorisation administrateur est requise pour vérifier un scope.")
    if scope.program.status != Program.Status.DRAFT:
        raise ValidationError("Seul le scope d’un programme brouillon peut être vérifié dans ce parcours.")
    if len(evidence_reference.strip()) < 3 or len(reviewer_reference.strip()) < 3:
        raise ValidationError("Une référence de preuve et une référence de revue sont obligatoires.")
    proof, _ = AssetOwnershipProof.objects.update_or_create(
        scope=scope,
        defaults={
            "evidence_reference": evidence_reference.strip(),
            "reviewed_by_reference": reviewer_reference.strip(),
            "approved_at": timezone.now(),
        },
    )
    scope.is_verified = True
    scope.save(update_fields=["is_verified"])
    ProgramDecisionEvent.objects.create(
        program=scope.program,
        actor=administrator,
        action="scope.verified",
        metadata={"scope_id": scope.id, "proof_id": proof.id},
    )
    record_organization_change(
        organization=scope.program.organization,
        actor=administrator,
        action="program.scope_verified",
        metadata={"program_id": scope.program_id, "scope_id": scope.id},
    )
    return scope


@transaction.atomic
def publish_program_after_admin_review(*, administrator, program: Program, reviewer_reference: str) -> Program:
    if not has_platform_permission(user=administrator, permission="platform.admin"):
        raise PermissionDenied("Une autorisation administrateur est requise pour publier un programme.")
    if program.status != Program.Status.DRAFT:
        raise ValidationError("Seul un programme brouillon peut être publié par ce parcours de revue.")
    if program.organization.verification_status != Organization.VerificationStatus.VERIFIED:
        raise ValidationError("L’organisation doit être vérifiée avant publication.")
    active_scopes = list(program.scopes.filter(is_active=True, is_excluded=False).select_related("ownership_proof"))
    if not active_scopes or any(
        not scope.is_verified or not getattr(scope, "ownership_proof", None) or not scope.ownership_proof.approved_at for scope in active_scopes
    ):
        raise ValidationError("Chaque scope actif doit avoir une preuve de propriété approuvée avant publication.")
    if len(reviewer_reference.strip()) < 3:
        raise ValidationError("Une référence de revue administrative est obligatoire pour publier.")
    policy = program.policy_versions.order_by("-created_at", "-id").first()
    if policy is None or len(policy.safe_harbor_text.strip()) < 30:
        raise ValidationError("Une politique safe-harbor détaillée et versionnée est obligatoire avant publication.")
    program.policy_versions.update(active=False)
    policy.active = True
    policy.save(update_fields=["active"])
    program.status = Program.Status.PUBLIC_ACTIVE
    program.policy_version = policy.version
    program.policy_hash = policy.content_hash
    program.safe_harbor_version = policy.version
    program.save(update_fields=["status", "policy_version", "policy_hash", "safe_harbor_version", "updated_at"])
    ProgramDecisionEvent.objects.create(
        program=program,
        actor=administrator,
        action="program.published_after_review",
        metadata={"reviewer_reference": reviewer_reference.strip(), "policy_version": policy.version},
    )
    record_organization_change(
        organization=program.organization,
        actor=administrator,
        action="program.published_after_admin_review",
        metadata={"program_id": program.id, "reviewer_reference": reviewer_reference.strip()},
    )
    return program


@transaction.atomic
def invite_private_program_researcher(*, actor, organization: Organization, program: Program, researcher) -> ProgramInvitation:
    require_organization_permission(user=actor, organization=organization, permission="program.manage")
    if program.organization_id != organization.id:
        raise PermissionDenied("Le programme ne relève pas de cette organisation.")
    if organization.verification_status != Organization.VerificationStatus.VERIFIED:
        raise PermissionDenied("La vérification de l’organisation est requise avant toute invitation privée.")
    if program.status != Program.Status.PRIVATE_ACTIVE:
        raise ValidationError("Les invitations sont réservées aux programmes privés actifs.")
    if researcher.platform_role != researcher.PlatformRole.RESEARCHER or not researcher.email_verified:
        raise ValidationError("Le chercheur invité doit posséder un compte chercheur dont l’e-mail est vérifié.")
    invitation, created = ProgramInvitation.objects.get_or_create(program=program, researcher=researcher)
    if not created and invitation.revoked_at is None:
        raise ValidationError("Ce chercheur dispose déjà d’une invitation active ou déjà acceptée pour ce programme.")
    if not created:
        invitation.accepted_at = None
        invitation.rules_accepted_at = None
        invitation.revoked_at = None
        invitation.save(update_fields=["accepted_at", "rules_accepted_at", "revoked_at"])
    record_organization_change(
        organization=organization,
        actor=actor,
        action="program.invitation_created",
        metadata={"program_id": program.id, "researcher_id": researcher.id},
    )
    return invitation


@transaction.atomic
def revoke_private_program_invitation(*, actor, organization: Organization, invitation: ProgramInvitation) -> ProgramInvitation:
    require_organization_permission(user=actor, organization=organization, permission="program.manage")
    if invitation.program.organization_id != organization.id:
        raise PermissionDenied("Cette invitation ne relève pas de cette organisation.")
    if invitation.revoked_at is not None:
        raise ValidationError("Cette invitation est déjà révoquée.")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at"])
    record_organization_change(
        organization=organization,
        actor=actor,
        action="program.invitation_revoked",
        metadata={"program_id": invitation.program_id, "researcher_id": invitation.researcher_id},
    )
    return invitation


@transaction.atomic
def update_program_service_level(
    *,
    actor,
    organization: Organization,
    program: Program,
    acknowledgement_hours,
    triage_hours,
    resolution_target_days,
) -> ProgramServiceLevel:
    """Met à jour des objectifs SLA bornés et recalcule les rapports du programme."""
    require_organization_permission(user=actor, organization=organization, permission="program.manage")
    if program.organization_id != organization.id:
        raise PermissionDenied("Le programme ne relève pas de cette organisation.")

    def _normalize_delay(value, *, label: str, maximum: int) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label} doit être un nombre entier.") from exc
        if not 1 <= normalized <= maximum:
            raise ValidationError(f"{label} doit être compris entre 1 et {maximum}.")
        return normalized

    acknowledgement = _normalize_delay(acknowledgement_hours, label="L’accusé de réception", maximum=720)
    triage = _normalize_delay(triage_hours, label="Le délai de triage", maximum=2160)
    resolution = _normalize_delay(resolution_target_days, label="La résolution cible", maximum=365)
    service_level, _ = ProgramServiceLevel.objects.get_or_create(program=program)
    previous = {
        "acknowledgement_hours": service_level.acknowledgement_hours,
        "triage_hours": service_level.triage_hours,
        "resolution_target_days": service_level.resolution_target_days,
    }
    current = {
        "acknowledgement_hours": acknowledgement,
        "triage_hours": triage,
        "resolution_target_days": resolution,
    }
    if previous == current:
        return service_level

    service_level.acknowledgement_hours = acknowledgement
    service_level.triage_hours = triage
    service_level.resolution_target_days = resolution
    service_level.save(update_fields=["acknowledgement_hours", "triage_hours", "resolution_target_days"])

    from apps.reports.sla import ensure_report_sla_state

    refreshed_reports = 0
    for report in program.reports.select_related("program").order_by("id"):
        if ensure_report_sla_state(report=report) is not None:
            refreshed_reports += 1
    ProgramDecisionEvent.objects.create(
        program=program,
        actor=actor,
        action="program.service_level_updated",
        metadata={"previous": previous, "current": current, "refreshed_reports": refreshed_reports},
    )
    record_organization_change(
        organization=organization,
        actor=actor,
        action="program.service_level_updated",
        metadata={"program_id": program.id, "previous": previous, "current": current, "refreshed_reports": refreshed_reports},
    )
    return service_level


@transaction.atomic
def suspend_program_emergency(*, actor, organization: Organization, program: Program, reason: str) -> Program:
    require_organization_permission(user=actor, organization=organization, permission="settings.manage")
    if program.organization_id != organization.id:
        raise PermissionDenied("Le programme ne relève pas de cette organisation.")
    require_adaptive_action(user=actor, action="program.emergency_suspend")
    emergency_close(actor=actor, program=program, reason=reason)
    record_organization_change(
        organization=organization,
        actor=actor,
        action="program.emergency_suspended",
        metadata={"program_id": program.id},
    )
    return program


@transaction.atomic
def resume_program_emergency(*, actor, organization: Organization, program: Program, reason: str) -> Program:
    require_organization_permission(user=actor, organization=organization, permission="settings.manage")
    if program.organization_id != organization.id:
        raise PermissionDenied("Le programme ne relève pas de cette organisation.")
    require_adaptive_action(user=actor, action="program.emergency_resume")
    resume_emergency_closed_program(actor=actor, program=program, reason=reason)
    record_organization_change(
        organization=organization,
        actor=actor,
        action="program.emergency_resumed",
        metadata={"program_id": program.id},
    )
    return program
