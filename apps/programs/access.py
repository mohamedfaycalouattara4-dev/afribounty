from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.programs.models import AssetScope, Program, ProgramDecisionEvent, ProgramInvitation


def can_research_program(*, user, program: Program) -> bool:
    if program.organization.verification_status != "verified":
        return False
    if program.status == Program.Status.PUBLIC_ACTIVE:
        return True
    return ProgramInvitation.objects.filter(
        program=program, researcher=user, accepted_at__isnull=False, rules_accepted_at__isnull=False, revoked_at__isnull=True
    ).exists()


def require_research_scope(*, user, program: Program, asset: str) -> AssetScope:
    if program.status in {Program.Status.SUSPENDED, Program.Status.CLOSED} or program.emergency_closed_at:
        raise PermissionDenied("Le programme est fermé ou suspendu.")
    if not can_research_program(user=user, program=program):
        raise PermissionDenied("Accès chercheur refusé pour ce programme.")
    scope = AssetScope.objects.filter(program=program, asset=asset, is_active=True, is_verified=True).first()
    if scope is None or scope.is_excluded or not hasattr(scope, "ownership_proof") or scope.ownership_proof.approved_at is None:
        raise PermissionDenied("Actif hors périmètre ou non vérifié.")
    return scope


def emergency_close(*, actor, program: Program, reason: str) -> None:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 12:
        raise ValidationError("Une justification d’au moins 12 caractères est requise pour la suspension d’urgence.")
    previous_status = program.status
    program.status = Program.Status.SUSPENDED
    program.emergency_closed_at = timezone.now()
    program.save(update_fields=["status", "emergency_closed_at"])
    ProgramDecisionEvent.objects.create(
        program=program,
        actor=actor,
        action="program.emergency_closed",
        metadata={"reason": normalized_reason, "previous_status": previous_status},
    )


def resume_emergency_closed_program(*, actor, program: Program, reason: str) -> None:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 12:
        raise ValidationError("Une justification d’au moins 12 caractères est requise pour la reprise.")
    if program.status != Program.Status.SUSPENDED or program.emergency_closed_at is None:
        raise ValidationError("Ce programme ne se trouve pas dans un état de suspension d’urgence à reprendre.")
    close_event = program.decision_events.filter(action="program.emergency_closed").order_by("-created_at", "-id").first()
    previous_status = (close_event.metadata if close_event else {}).get("previous_status")
    if previous_status not in Program.Status.values or previous_status == Program.Status.SUSPENDED:
        raise ValidationError("L’état de reprise du programme ne peut pas être déterminé de manière sûre.")
    program.status = previous_status
    program.emergency_closed_at = None
    program.save(update_fields=["status", "emergency_closed_at"])
    ProgramDecisionEvent.objects.create(
        program=program,
        actor=actor,
        action="program.emergency_resumed",
        metadata={"reason": normalized_reason, "restored_status": previous_status},
    )
