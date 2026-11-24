from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.organizations.models import ConflictDeclaration
from apps.organizations.services import record_organization_change, require_organization_permission
from apps.reports.models import (
    FixValidation,
    MediationCase,
    RemediationTracking,
    Report,
    ReportRelation,
    SeverityAssessment,
    TriageAssignment,
    TriageDecision,
    TriageDecisionEvent,
    TriageExportEvent,
)
from apps.reports.services import transition_report
from apps.reports.sla import ensure_report_sla_state


def _assert_no_conflict(*, user, report: Report) -> None:
    if user == report.author:
        raise PermissionDenied("L’auteur d’un rapport ne peut pas le trier ou le médiatiser.")
    if ConflictDeclaration.objects.filter(organization=report.organization, user=user, active=True).exists():
        raise PermissionDenied("Cette personne a un conflit d’intérêt actif pour l’organisation concernée.")


def _record(*, report: Report, actor, action: str, **detail) -> None:
    TriageDecisionEvent.objects.create(report=report, actor=actor, action=action, detail=detail)


@transaction.atomic
def assign_triage(*, report: Report, actor, assignee, reason: str, queue: str = TriageAssignment.Queue.PRE_TRIAGE) -> TriageAssignment:
    if report.status not in {Report.Status.SUBMITTED, Report.Status.IN_TRIAGE, Report.Status.INFORMATION_REQUIRED}:
        raise ValidationError("Le rapport n’est pas dans une file assignable.")
    if not reason.strip():
        raise ValidationError("Une assignation exige une justification.")
    _assert_no_conflict(user=assignee, report=report)
    assignment, _ = TriageAssignment.objects.update_or_create(
        report=report,
        defaults={"assigned_to": assignee, "reason": reason.strip(), "queue": queue},
    )
    if report.status == Report.Status.SUBMITTED:
        transition_report(report=report, actor=actor, target_status=Report.Status.IN_TRIAGE, reason="Entrée dans la file de pré-triage.")
    _record(report=report, actor=actor, action="triage.assigned", assignee_id=assignee.id, queue=queue)
    return assignment


@transaction.atomic
def record_severity(*, report: Report, evaluator, technical_severity: str, justification: str, scoring_vector: str = "") -> SeverityAssessment:
    _assert_no_conflict(user=evaluator, report=report)
    if report.status != Report.Status.IN_TRIAGE:
        raise ValidationError("La sévérité ne peut être évaluée que durant le triage.")
    if not justification.strip():
        raise ValidationError("Une évaluation de sévérité exige une justification.")
    current = SeverityAssessment.objects.filter(report=report).order_by("-version").first()
    assessment = SeverityAssessment.objects.create(
        report=report,
        evaluator=evaluator,
        technical_severity=technical_severity,
        justification=justification.strip(),
        scoring_vector=scoring_vector.strip(),
        version=(current.version + 1) if current else 1,
    )
    _record(report=report, actor=evaluator, action="triage.severity_recorded", version=assessment.version)
    return assessment


@transaction.atomic
def record_triage_decision(
    *, report: Report, decider, business_priority: str, reward_eligibility: str, justification: str, reason_code: str = TriageDecision.ReasonCode.PENDING
) -> TriageDecision:
    _assert_no_conflict(user=decider, report=report)
    if not SeverityAssessment.objects.filter(report=report).exists():
        raise ValidationError("Une décision de priorité exige une évaluation de sévérité préalable.")
    if not justification.strip():
        raise ValidationError("La priorité et l’éligibilité exigent une justification.")
    if reason_code not in TriageDecision.ReasonCode.values:
        raise ValidationError("Le motif structuré de décision est invalide.")
    decision, _ = TriageDecision.objects.update_or_create(
        report=report,
        defaults={
            "decided_by": decider,
            "business_priority": business_priority,
            "reward_eligibility": reward_eligibility,
            "reason_code": reason_code,
            "justification": justification.strip(),
        },
    )
    _record(
        report=report,
        actor=decider,
        action="triage.decision_recorded",
        priority=business_priority,
        eligibility=reward_eligibility,
        reason_code=reason_code,
    )
    ensure_report_sla_state(report=report)
    return decision


@transaction.atomic
def relate_reports(*, report: Report, related_report: Report, actor, relation_type: str, rationale: str) -> ReportRelation:
    _assert_no_conflict(user=actor, report=report)
    if report.program_id != related_report.program_id:
        raise ValidationError("Un doublon ou impact lié doit appartenir au même programme.")
    if report.id == related_report.id:
        raise ValidationError("Un rapport ne peut pas être son propre doublon.")
    if not rationale.strip():
        raise ValidationError("La relation entre rapports exige une justification.")
    relation, _ = ReportRelation.objects.get_or_create(
        report=report,
        related_report=related_report,
        relation_type=relation_type,
        defaults={"created_by": actor, "rationale": rationale.strip()},
    )
    if relation_type == ReportRelation.RelationType.DUPLICATE_OF and report.status == Report.Status.IN_TRIAGE:
        transition_report(report=report, actor=actor, target_status=Report.Status.DUPLICATE, reason="Doublon confirmé avec justification enregistrée.")
    _record(report=report, actor=actor, action="triage.relation_recorded", related_report_id=related_report.id, relation_type=relation_type)
    return relation


@transaction.atomic
def start_remediation(*, report: Report, actor, owner, target_due_at, plan: str) -> RemediationTracking:
    _assert_no_conflict(user=actor, report=report)
    if report.status != Report.Status.VALID:
        raise ValidationError("Seul un rapport validé peut entrer en remédiation.")
    if target_due_at <= timezone.now():
        raise ValidationError("L’échéance de remédiation doit être future.")
    if not plan.strip():
        raise ValidationError("Un plan de remédiation explicite est obligatoire.")
    remediation = RemediationTracking.objects.create(report=report, owner=owner, target_due_at=target_due_at, plan=plan.strip())
    transition_report(report=report, actor=actor, target_status=Report.Status.REMEDIATION, reason="Plan de remédiation créé.")
    _record(report=report, actor=actor, action="triage.remediation_started", owner_id=owner.id)
    return remediation


@transaction.atomic
def submit_fix_for_validation(*, remediation: RemediationTracking, actor) -> RemediationTracking:
    if remediation.owner_id != actor.id:
        raise PermissionDenied("Seul le propriétaire de la correction peut demander sa validation.")
    if remediation.status not in {RemediationTracking.Status.PLANNED, RemediationTracking.Status.IN_PROGRESS, RemediationTracking.Status.REJECTED}:
        raise ValidationError("Cette remédiation ne peut pas être soumise à validation dans son état actuel.")
    remediation.status = RemediationTracking.Status.READY_FOR_VALIDATION
    remediation.save(update_fields=["status", "updated_at"])
    _record(report=remediation.report, actor=actor, action="triage.fix_submitted")
    return remediation


@transaction.atomic
def validate_fix(*, remediation: RemediationTracking, validator, outcome: str, notes: str) -> FixValidation:
    _assert_no_conflict(user=validator, report=remediation.report)
    if remediation.owner_id == validator.id:
        raise PermissionDenied("Le propriétaire de la correction ne peut pas valider sa propre correction.")
    if remediation.status != RemediationTracking.Status.READY_FOR_VALIDATION:
        raise ValidationError("La correction n’est pas prête à être validée.")
    if not notes.strip():
        raise ValidationError("Toute validation exige des notes de contrôle.")
    validation = FixValidation.objects.create(remediation=remediation, validator=validator, outcome=outcome, notes=notes.strip())
    if outcome == FixValidation.Outcome.ACCEPTED:
        remediation.status = RemediationTracking.Status.VERIFIED
        transition_report(report=remediation.report, actor=validator, target_status=Report.Status.RESOLVED, reason="Correction validée indépendamment.")
    else:
        remediation.status = RemediationTracking.Status.REJECTED
    remediation.save(update_fields=["status", "updated_at"])
    _record(report=remediation.report, actor=validator, action="triage.fix_validated", outcome=outcome)
    return validation


@transaction.atomic
def request_mediation(*, report: Report, requester, reason: str) -> MediationCase:
    if requester != report.author:
        raise PermissionDenied("Seul le chercheur auteur peut demander une médiation dans ce lot.")
    if not reason.strip():
        raise ValidationError("Une demande de médiation exige un motif explicite.")
    decision = getattr(report, "triage_decision", None)
    if not decision:
        raise ValidationError("Une médiation exige une première décision de triage.")
    case = MediationCase.objects.create(
        report=report,
        requested_by=requester,
        initial_decider=decision.decided_by,
        request_reason=reason.strip(),
    )
    _record(report=report, actor=requester, action="triage.mediation_requested")
    return case


@transaction.atomic
def decide_mediation(*, case: MediationCase, mediator, independent_reviewer, decision: str) -> MediationCase:
    report = case.report
    _assert_no_conflict(user=mediator, report=report)
    _assert_no_conflict(user=independent_reviewer, report=report)
    prohibited_ids = {case.requested_by_id, case.initial_decider_id}
    if mediator.id in prohibited_ids or independent_reviewer.id in prohibited_ids:
        raise PermissionDenied("Le requérant et le premier décideur ne peuvent pas revoir la médiation.")
    if mediator.id == independent_reviewer.id:
        raise PermissionDenied("Le second regard doit être assuré par une personne distincte du médiateur.")
    if not decision.strip():
        raise ValidationError("Une médiation exige une décision motivée.")
    case.mediator = mediator
    case.independent_reviewer = independent_reviewer
    case.status = MediationCase.Status.DECIDED
    case.decision = decision.strip()
    case.decided_at = timezone.now()
    case.save(update_fields=["mediator", "independent_reviewer", "status", "decision", "decided_at"])
    _record(report=report, actor=mediator, action="triage.mediation_decided", independent_reviewer_id=independent_reviewer.id)
    return case


def triage_metrics_for_program(*, program):
    """Retourne seulement des comptes et délais agrégés, jamais le contenu des rapports ou preuves."""
    reports = Report.objects.filter(program=program)
    now = timezone.now()
    open_remediations = RemediationTracking.objects.filter(report__program=program).exclude(status=RemediationTracking.Status.VERIFIED)
    return {
        "reports_total": reports.count(),
        "reports_in_triage": reports.filter(status=Report.Status.IN_TRIAGE).count(),
        "remediations_open": open_remediations.count(),
        "remediations_overdue": open_remediations.filter(target_due_at__lt=now).count(),
    }


@transaction.atomic
def export_triage_aggregate(*, organization, program, actor) -> dict:
    """Exporte exclusivement des métriques agrégées après autorisation explicite de l’organisation."""
    require_organization_permission(user=actor, organization=organization, permission="export.request")
    if not organization.exports_enabled:
        raise PermissionDenied("Les exports de triage sont désactivés pour cette organisation.")
    if program.organization_id != organization.id:
        raise PermissionDenied("Le programme ne relève pas de l’organisation autorisée.")

    reports = list(Report.objects.filter(program=program).prefetch_related("events", "severity_assessments"))
    now = timezone.now()
    status_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    triage_delays: list[float] = []
    decision_coverage = 0
    for report in reports:
        status_counts[report.status] = status_counts.get(report.status, 0) + 1
        first_triage = next((event for event in report.events.all() if event.to_status == Report.Status.IN_TRIAGE), None)
        if first_triage:
            triage_delays.append((first_triage.created_at - report.created_at).total_seconds() / 3600)
        latest_assessment = report.severity_assessments.order_by("-version").first()
        if latest_assessment:
            severity_counts[latest_assessment.technical_severity] = severity_counts.get(latest_assessment.technical_severity, 0) + 1
        if hasattr(report, "triage_decision"):
            decision_coverage += 1

    remediations = RemediationTracking.objects.filter(report__program=program)
    overdue = remediations.exclude(status=RemediationTracking.Status.VERIFIED).filter(target_due_at__lt=now).count()
    payload = {
        "reports_total": len(reports),
        "status_counts": status_counts,
        "severity_counts": severity_counts,
        "triage_delay_average_hours": round(sum(triage_delays) / len(triage_delays), 2) if triage_delays else None,
        "triage_delay_samples": len(triage_delays),
        "decision_coverage_count": decision_coverage,
        "decision_coverage_rate": round(decision_coverage / len(reports), 4) if reports else 0,
        "remediations_total": remediations.count(),
        "remediations_overdue": overdue,
        "remediations_verified": remediations.filter(status=RemediationTracking.Status.VERIFIED).count(),
    }
    TriageExportEvent.objects.create(organization=organization, program=program, actor=actor, aggregate=payload)
    record_organization_change(
        organization=organization,
        actor=actor,
        action="triage.aggregate_exported",
        metadata={"program_id": program.id, "reports_total": payload["reports_total"]},
    )
    return payload
