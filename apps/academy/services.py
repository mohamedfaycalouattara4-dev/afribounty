import hashlib
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academy.models import (
    AcademyBadge,
    EthicsAcceptance,
    LabInstance,
    LearnerBadge,
    LearnerConductIncident,
    LearningProgress,
    RemediationExerciseSubmission,
    ReportingExerciseSubmission,
)
from apps.academy.providers import SandboxLabProvider, default_sandbox_provider
from apps.security.audit import record_audit
from apps.security.freeze import freeze_subject
from apps.security.models import SecuritySubject

CURRENT_ETHICS_RULES_VERSION = "ethics-v1"
CURRENT_ETHICS_RULES_TEXT = (
    "Je m’engage à respecter le scope autorisé, à éviter toute perturbation, à protéger les données et à signaler toute vulnérabilité de façon responsable."
)
CURRENT_ETHICS_RULES_HASH = hashlib.sha256(CURRENT_ETHICS_RULES_TEXT.encode("utf-8")).hexdigest()


def has_current_ethics_acceptance(*, learner) -> bool:
    return EthicsAcceptance.objects.filter(learner=learner, rules_hash=CURRENT_ETHICS_RULES_HASH).exists()


def accept_current_ethics(*, learner) -> EthicsAcceptance:
    acceptance, _ = EthicsAcceptance.objects.get_or_create(
        learner=learner,
        rules_hash=CURRENT_ETHICS_RULES_HASH,
        defaults={"rules_version": CURRENT_ETHICS_RULES_VERSION},
    )
    return acceptance


def _assert_ethics_accepted(*, learner) -> None:
    if not has_current_ethics_acceptance(learner=learner):
        raise PermissionDenied("L’acceptation de la version courante des règles d’éthique est obligatoire avant un laboratoire.")


@transaction.atomic
def provision_lab_instance(*, laboratory, learner, quota_minutes: int | None = None, provider: SandboxLabProvider = default_sandbox_provider) -> LabInstance:
    _assert_ethics_accepted(learner=learner)
    if not laboratory.active or not laboratory.is_isolated or laboratory.contains_external_target:
        raise PermissionDenied("Seul un laboratoire actif, isolé et sans cible externe peut être provisionné.")
    quota = quota_minutes if quota_minutes is not None else laboratory.default_quota_minutes
    if quota <= 0 or quota > laboratory.default_quota_minutes:
        raise ValidationError("Le quota demandé est invalide pour ce laboratoire.")
    receipt = provider.provision(laboratory_code=laboratory.code, learner_reference=str(learner.id), quota_minutes=quota)
    isolation_proof = provider.verify_isolation(reference=receipt.reference)
    if isolation_proof != SandboxLabProvider.isolation_policy:
        raise ValidationError("Le fournisseur ne fournit pas la politique d’isolation obligatoire.")
    instance = LabInstance.objects.create(
        laboratory=laboratory,
        learner=learner,
        network_isolated=True,
        quota_minutes=quota,
        expires_at=timezone.now() + timedelta(minutes=quota),
        provider_reference=receipt.reference,
        isolation_proof={"provider": provider.provider_name, "policy": isolation_proof},
    )
    record_audit(action="academy.lab.provisioned", resource_type="lab_instance", resource_reference=str(instance.id), actor_reference=str(learner.id))
    return instance


@transaction.atomic
def destroy_lab_instance(*, instance: LabInstance, actor, reason: str, provider: SandboxLabProvider = default_sandbox_provider) -> LabInstance:
    if instance.status != LabInstance.Status.PROVISIONED:
        raise ValidationError("Seule une instance provisionnée peut être détruite.")
    if actor.id != instance.learner_id and not actor.is_staff:
        raise PermissionDenied("Seul l’apprenant concerné ou un administrateur peut détruire cette instance.")
    if not reason.strip():
        raise ValidationError("La destruction exige un motif pour conserver la traçabilité.")
    if not instance.provider_reference:
        raise ValidationError("L’instance héritée ne dispose pas de référence fournisseur vérifiable.")
    destruction_proof = provider.destroy(reference=instance.provider_reference)
    if destruction_proof.get("state") != "destroyed":
        raise ValidationError("Le fournisseur n’a pas confirmé la destruction de l’instance.")
    instance.status = LabInstance.Status.DESTROYED
    instance.destroyed_at = timezone.now()
    instance.destruction_reason = reason.strip()
    instance.destruction_proof = destruction_proof
    instance.save(update_fields=["status", "destroyed_at", "destruction_reason", "destruction_proof"])
    record_audit(action="academy.lab.destroyed", resource_type="lab_instance", resource_reference=str(instance.id), actor_reference=str(actor.id))
    return instance


@transaction.atomic
def complete_lesson(*, learner, lesson, score: int | None = None) -> LearningProgress:
    if score is not None and not 0 <= score <= 100:
        raise ValidationError("Le score doit être compris entre 0 et 100.")
    progress, _ = LearningProgress.objects.update_or_create(
        learner=learner,
        lesson=lesson,
        defaults={"completed_at": timezone.now(), "score": score},
    )
    return progress


@transaction.atomic
def assess_reporting_exercise(*, submission: ReportingExerciseSubmission, reviewer, score: int) -> ReportingExerciseSubmission:
    if reviewer.id == submission.learner_id:
        raise PermissionDenied("Un apprenant ne peut pas évaluer son propre exercice.")
    if not 0 <= score <= 100:
        raise ValidationError("Le score doit être compris entre 0 et 100.")
    submission.score = score
    submission.assessed_at = timezone.now()
    submission.save(update_fields=["score", "assessed_at"])
    return submission


@transaction.atomic
def assess_remediation_exercise(*, submission: RemediationExerciseSubmission, reviewer, score: int) -> RemediationExerciseSubmission:
    if reviewer.id == submission.learner_id:
        raise PermissionDenied("Un apprenant ne peut pas évaluer son propre exercice de remédiation.")
    if not 0 <= score <= 100:
        raise ValidationError("Le score doit être compris entre 0 et 100.")
    submission.score = score
    submission.assessed_at = timezone.now()
    submission.save(update_fields=["score", "assessed_at"])
    return submission


@transaction.atomic
def request_badge(*, badge: AcademyBadge, learner) -> LearnerBadge:
    award, _ = LearnerBadge.objects.get_or_create(badge=badge, learner=learner)
    return award


@transaction.atomic
def review_badge(*, award: LearnerBadge, reviewer, award_badge: bool, reason: str) -> LearnerBadge:
    if reviewer.id == award.learner_id:
        raise PermissionDenied("Un apprenant ne peut pas revoir son propre badge.")
    if not reason.strip():
        raise ValidationError("Toute attribution ou retrait exige une justification.")
    award.reviewed_by = reviewer
    award.review_reason = reason.strip()
    if award_badge:
        award.status = LearnerBadge.Status.AWARDED
        award.awarded_at = timezone.now()
        award.revoked_at = None
    else:
        award.status = LearnerBadge.Status.REVOKED
        award.revoked_at = timezone.now()
    award.save(update_fields=["reviewed_by", "review_reason", "status", "awarded_at", "revoked_at"])
    record_audit(action="academy.badge.reviewed", resource_type="learner_badge", resource_reference=str(award.id), actor_reference=str(reviewer.id))
    return award


@transaction.atomic
def freeze_for_conduct(*, incident: LearnerConductIncident, reviewer, reason: str) -> LearnerConductIncident:
    if reviewer.id == incident.learner_id:
        raise PermissionDenied("Un apprenant ne peut pas traiter son propre incident de conduite.")
    if not incident.security_subject_id:
        raise ValidationError("Un sujet de sécurité doit être associé avant tout gel de compte.")
    if not reason.strip():
        raise ValidationError("Le gel exige une décision motivée.")
    freeze_subject(subject=incident.security_subject, reason=reason.strip(), actor_reference=str(reviewer.id))
    incident.status = LearnerConductIncident.Status.FROZEN
    incident.decision_reason = reason.strip()
    incident.reviewed_at = timezone.now()
    incident.save(update_fields=["status", "decision_reason", "reviewed_at"])
    return incident


@transaction.atomic
def appeal_conduct(*, incident: LearnerConductIncident, learner, reason: str) -> LearnerConductIncident:
    if learner.id != incident.learner_id:
        raise PermissionDenied("Seul l’apprenant concerné peut déposer un recours.")
    if incident.status != LearnerConductIncident.Status.FROZEN:
        raise ValidationError("Un recours est recevable uniquement après un gel.")
    if not reason.strip():
        raise ValidationError("Le recours exige un motif.")
    incident.status = LearnerConductIncident.Status.APPEALED
    incident.appeal_reason = reason.strip()
    incident.save(update_fields=["status", "appeal_reason"])
    record_audit(action="academy.conduct.appealed", resource_type="academy_incident", resource_reference=str(incident.id), actor_reference=str(learner.id))
    return incident


@transaction.atomic
def resolve_conduct_appeal(*, incident: LearnerConductIncident, reviewer, overturn_freeze: bool, reason: str) -> LearnerConductIncident:
    if reviewer.id == incident.learner_id:
        raise PermissionDenied("Un apprenant ne peut pas trancher son propre recours.")
    if incident.status != LearnerConductIncident.Status.APPEALED:
        raise ValidationError("Seul un recours en cours peut être tranché.")
    if not reason.strip():
        raise ValidationError("La décision de recours exige une justification.")
    if overturn_freeze and incident.security_subject_id:
        subject = incident.security_subject
        subject.status = SecuritySubject.Status.ACTIVE
        subject.frozen_reason = ""
        subject.frozen_at = None
        subject.review_required = False
        subject.save(update_fields=["status", "frozen_reason", "frozen_at", "review_required"])
        record_audit(
            action="academy.conduct.freeze_overturned",
            resource_type="security_subject",
            resource_reference=subject.reference,
            actor_reference=str(reviewer.id),
        )
    incident.status = LearnerConductIncident.Status.CLOSED
    incident.decision_reason = reason.strip()
    incident.reviewed_at = timezone.now()
    incident.save(update_fields=["status", "decision_reason", "reviewed_at"])
    return incident
