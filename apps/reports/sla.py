from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.programs.models import ProgramServiceLevel
from apps.reports.models import Report, ReportEvent, ReportSlaEscalationEvent, ReportSlaState, TriageDecision


def _commitment_state(*, due_at, completed_at, warning_window, at):
    if completed_at:
        return ReportSlaState.CommitmentState.COMPLETED
    if at > due_at:
        return ReportSlaState.CommitmentState.OVERDUE
    if due_at - at <= warning_window:
        return ReportSlaState.CommitmentState.DUE
    return ReportSlaState.CommitmentState.UPCOMING


def _warning_window(*, duration: timedelta) -> timedelta:
    return min(timedelta(hours=24), max(timedelta(hours=1), duration / 5))


def _first_transition_at(*, report: Report, target_status: str):
    return ReportEvent.objects.filter(report=report, to_status=target_status).order_by("created_at", "id").values_list("created_at", flat=True).first()


@transaction.atomic
def ensure_report_sla_state(*, report: Report, at=None) -> ReportSlaState | None:
    """Crée ou rafraîchit les engagements SLA à partir des traces métier déjà présentes."""
    now = at or timezone.now()
    try:
        service_level = report.program.service_level
    except ProgramServiceLevel.DoesNotExist:
        return None

    acknowledgement_duration = timedelta(hours=service_level.acknowledgement_hours)
    triage_duration = timedelta(hours=service_level.triage_hours)
    resolution_duration = timedelta(days=service_level.resolution_target_days)
    acknowledgement_completed_at = _first_transition_at(report=report, target_status=Report.Status.IN_TRIAGE)
    triage_completed_at = TriageDecision.objects.filter(report=report).values_list("decided_at", flat=True).first()
    resolution_completed_at = _first_transition_at(report=report, target_status=Report.Status.RESOLVED)
    defaults = {
        "acknowledgement_due_at": report.created_at + acknowledgement_duration,
        "acknowledgement_completed_at": acknowledgement_completed_at,
        "acknowledgement_state": _commitment_state(
            due_at=report.created_at + acknowledgement_duration,
            completed_at=acknowledgement_completed_at,
            warning_window=_warning_window(duration=acknowledgement_duration),
            at=now,
        ),
        "triage_due_at": report.created_at + triage_duration,
        "triage_completed_at": triage_completed_at,
        "triage_state": _commitment_state(
            due_at=report.created_at + triage_duration,
            completed_at=triage_completed_at,
            warning_window=_warning_window(duration=triage_duration),
            at=now,
        ),
        "resolution_due_at": report.created_at + resolution_duration,
        "resolution_completed_at": resolution_completed_at,
        "resolution_state": _commitment_state(
            due_at=report.created_at + resolution_duration,
            completed_at=resolution_completed_at,
            warning_window=_warning_window(duration=resolution_duration),
            at=now,
        ),
    }
    state, _ = ReportSlaState.objects.update_or_create(report=report, defaults=defaults)
    return state


def _refresh_states(*, reports, at):
    return [state for report in reports for state in [ensure_report_sla_state(report=report, at=at)] if state]


@transaction.atomic
def collect_sla_escalations(*, at=None) -> list[ReportSlaEscalationEvent]:
    """Enregistre une seule escalade locale par engagement dépassé, sans envoi externe."""
    now = at or timezone.now()
    created = []
    reports = Report.objects.select_related("program").all().order_by("id")
    for state in _refresh_states(reports=reports, at=now):
        for checkpoint, status, due_at in (
            (ReportSlaEscalationEvent.Checkpoint.ACKNOWLEDGEMENT, state.acknowledgement_state, state.acknowledgement_due_at),
            (ReportSlaEscalationEvent.Checkpoint.TRIAGE, state.triage_state, state.triage_due_at),
            (ReportSlaEscalationEvent.Checkpoint.RESOLUTION, state.resolution_state, state.resolution_due_at),
        ):
            if status != ReportSlaState.CommitmentState.OVERDUE:
                continue
            event, was_created = ReportSlaEscalationEvent.objects.get_or_create(
                idempotency_key=f"report-sla:{state.report_id}:{checkpoint}:{due_at.isoformat()}",
                defaults={"report": state.report, "checkpoint": checkpoint, "due_at": due_at},
            )
            if was_created:
                created.append(event)
    return created


def sla_metrics_for_program(*, program, at=None) -> dict:
    """Retourne des comptes SLA agrégés, sans contenu de rapport ni élément de preuve."""
    now = at or timezone.now()
    try:
        program.service_level
    except ProgramServiceLevel.DoesNotExist:
        empty_commitments = {state: 0 for state in ReportSlaState.CommitmentState.values}
        return {
            "configured": False,
            "reports_total": Report.objects.filter(program=program).count(),
            "escalations_total": 0,
            "acknowledgement": empty_commitments.copy(),
            "triage": empty_commitments.copy(),
            "resolution": empty_commitments.copy(),
        }
    states = _refresh_states(reports=Report.objects.filter(program=program).select_related("program").order_by("id"), at=now)
    metrics = {
        "configured": True,
        "reports_total": len(states),
        "escalations_total": ReportSlaEscalationEvent.objects.filter(report__program=program).count(),
    }
    for name in ("acknowledgement", "triage", "resolution"):
        counts = Counter(getattr(state, f"{name}_state") for state in states)
        metrics[name] = {state: counts.get(state, 0) for state in ReportSlaState.CommitmentState.values}
    return metrics


def sla_metrics_for_organization(*, organization, at=None) -> dict:
    aggregate = {"reports_total": 0, "escalations_total": 0, "configured_programs": 0, "programs_without_sla": 0}
    for name in ("acknowledgement", "triage", "resolution"):
        aggregate[name] = {state: 0 for state in ReportSlaState.CommitmentState.values}
    for program in organization.programs.all().order_by("id"):
        metrics = sla_metrics_for_program(program=program, at=at)
        aggregate["reports_total"] += metrics["reports_total"]
        aggregate["escalations_total"] += metrics["escalations_total"]
        if metrics["configured"]:
            aggregate["configured_programs"] += 1
        else:
            aggregate["programs_without_sla"] += 1
        for name in ("acknowledgement", "triage", "resolution"):
            for state, total in metrics[name].items():
                aggregate[name][state] += total
    return aggregate
